import datetime
import fnmatch
import hashlib
import os
import asyncio
import logging
import typing
import importlib.metadata

import asyncpg
from pathlib import Path
from fastapi import FastAPI, status, Path as PathArg, Query, Request, Header
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
try:
    from . import config
except ImportError:
    pass

from .ratelimiting import RateLimitHandler
from .models import EmbedPayload, RateLimitedException

try:
    version = importlib.metadata.version("nio-bot")
except importlib.metadata.PackageNotFoundError:
    version = "1.1.0b1"

logging.basicConfig(level=logging.INFO)
app = FastAPI(
    title="nio-bot embed server",
    description="The server that provides \"rich embeds\" for matrix clients.\n"
                "Take a look at /about.html for more information.",
    version=version,
    base_url=os.getenv("base_url", None),
    contact={
        "name": "Matrix Room (support)",
        "url": "https://matrix.to/#/#nio-bot:nexy7574.co.uk",
    },
    license_info={
        "name": "GNU GPLv3",
        "url": "https://www.gnu.org/licenses/gpl-3.0.en.html",
    }
)
log = logging.getLogger(__name__)
app.state.EMBED_CODE_SIZE = min(256, max(4, int(os.getenv("EMBED_CODE_SIZE", 6))))
app.state.EMBED_CODE_CHARSET = os.getenv("EMBED_CODE_CHARSET", "0123456789abcdef")
log.info("Initialised embed server.")
if (_max_codes := (len(app.state.EMBED_CODE_CHARSET) ** app.state.EMBED_CODE_SIZE)) < 1000000:
    log.warning("Embed size is too small - there are only {:,} possible codes.".format(_max_codes))

app.state.BASE = BASE = Path(__file__).parent
app.state.templates = Jinja2Templates(
    directory=BASE / "static" / "templates",
    autoescape=True,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "HEAD", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.on_event("startup")
async def on_startup():
    PG_URI = os.getenv(
        "PG_URI",
        "postgresql://postgres:postgres@localhost:5432/postgres"
    )
    log.info("Connecting to database: {}.".format(PG_URI))
    for i in range(5):
        try:
            app.state.db = await asyncpg.connect(
                PG_URI,
            )
        except ConnectionRefusedError:
            log.warning("Could not connect to database. Retrying... (%d/5)", i + 1)
            await asyncio.sleep(i)
    await app.state.db.execute(
        """
        CREATE TABLE IF NOT EXISTS embeds (
            code VARCHAR(256) PRIMARY KEY,
            title VARCHAR(256),
            description VARCHAR(4096),
            colour INTEGER,
            timestamp TIMESTAMP,
            author_name VARCHAR(256),
            media_url VARCHAR(10240),
            owner VARCHAR(64)
        );
        """
    )
    app.state.redis = RateLimitHandler(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        password=os.getenv("REDIS_PASSWORD", None),
        db=int(os.getenv("REDIS_DB", 0))
    )
    log.info("Connected to database.")


@app.on_event("shutdown")
async def on_shutdown():
    log.info("Closing database connection.")
    await app.state.db.close()
    log.info("Closed database connection.")


def check_ratelimit(request: Request, bucket: str = "global", update: bool = True) -> typing.Dict[str, str]:
    """
    Checks if a request is rate limited.

    This function will raise a RateLimitedException if the request is rate limited.
    """
    if update:
        app.state.redis.update(request, bucket=bucket)
    headers = app.state.redis.generate_ratelimit_headers(
        request,
        bucket=bucket
    )

    if app.state.redis.check(request, bucket=bucket):
        raise RateLimitedException(headers)
    return headers


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    try:
        check_ratelimit(request)
    except RateLimitedException as e:
        return JSONResponse(
            {
                "detail": e.detail,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers=e.headers
        )
    response = await call_next(request)
    if "X-Ratelimit-Limit" not in response.headers:
        # Add global ratelimit headers
        response.headers.update(
            app.state.redis.generate_ratelimit_headers(
                request,
                bucket="global"
            )
        )
    return response


@app.get("/", include_in_schema=False)
async def direct_to_docs():
    return RedirectResponse(
        "/docs",
        status_code=status.HTTP_308_PERMANENT_REDIRECT,
    )


@app.get("/embed/quick", response_class=HTMLResponse)
def render_quick_embed(
        req: Request,
        title: str = Query(
            None,
            title="Title",
            description="The title of the embed.",
        ),
        description: str = Query(
            None,
            title="Description",
            description="The description of the embed.",
        ),
        colour: int = Query(
            None,
            title="Colour",
            description="The colour value of the embed.",
            alias="color",
        ),
):
    """Renders an embed on-the-fly without saving it."""
    if title is None and description is None:
        return HTMLResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content="You must provide at least one of title or description."
        )
    colour = colour or 0x1
    if colour > 0xFFFFFF or colour < 0:
        return HTMLResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content="Colour must be a valid hex colour value."
        )
    rl = check_ratelimit(req, bucket="generate")
    tags = {
        "title": title,
        "description": description,
        "colour": colour,
    }
    return app.state.templates.TemplateResponse(
        "embed.html",
        {
            "request": req,
            "embed": {
                "title": title,
                "description": description,
                "colour": colour,
                "colour_hex": "#" + hex(colour)[2:].zfill(6),
                "og_tags": tags
            }
        },
        headers=rl
    )


@app.get(
    "/embed/{code}",
)
async def render_embed(
        req: Request,
        code: str = PathArg(
            ...,
            title="Embed code",
            description="The code of the saved embed to render.",
        ),
        accept: str = Header(
            "text/html;q=0.9,application/json;q=0.8,*/*;q=0.7",
            title="Accept",
            description="The accept header of the request.",
        )
):
    """
    Renders an embed from the given parameters.

    If code is None, you must perform an on-the-fly embed with at least one of the other parameters.
    """
    def parse_accept(h: str):
        ql = []
        for ct in h.split(","):
            ct = ct.strip()
            if ";" in ct:
                ct, quality = ct.split(";")
                quality = quality.strip()
                if quality.startswith("q="):
                    quality = float(quality[2:])
                else:
                    quality = 1.0
            else:
                quality = 1.0
            ql.append((ct, quality))
        return list(sorted(ql, key=lambda x: x[1], reverse=True))

    json = False
    if accept:
        accept_parsed = parse_accept(accept)
        json = fnmatch.fnmatch("application/json", accept_parsed[0][0])

    rl = check_ratelimit(req, bucket="generate")
    result = await app.state.db.fetchrow(
        """
        SELECT * FROM embeds WHERE code = $1;
        """,
        code
    )
    if result is None:
        return HTMLResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content="Embed not found.",
            headers=rl
        )
    tags = {}
    for key, value in result.items():
        if key == "media_url":
            tags["image"] = value
        elif key in ("owner", "colour", "code"):
            continue
        else:
            tags[key] = value or tags[key]
        if value is None:
            tags.pop(key, None)
        elif not isinstance(value, (str, int, float, bool, list, dict, tuple, type(None))):
            tags[key] = str(value)
    if json:
        return JSONResponse(
            {
                "embed": {
                    "title": result["title"],
                    "description": result["description"],
                    "colour": result["colour"],
                    "code": code,
                    "colour_hex": "#" + hex(result["colour"])[2:].zfill(6),
                    "owner": result["owner"],
                    "og_tags": tags,
                    "media_url": result["media_url"]
                }
            },
            headers=rl
        )
    # noinspection PyTypeChecker
    return app.state.templates.TemplateResponse(
        "embed.html",
        {
            "request": req,
            "embed": {
                "title": result["title"],
                "description": result["description"],
                "colour": result["colour"],
                "code": code,
                "colour_hex": "#" + hex(result["colour"])[2:].zfill(6),
                "owner": result["owner"],
                "og_tags": tags,
                "media_url": result["media_url"]
            }
        },
        headers=rl
    )


@app.post("/embed/create", response_class=JSONResponse, status_code=status.HTTP_201_CREATED)
async def save_embed(
        req: Request,
        body: EmbedPayload,
):
    """Creates & saves an embed, returning the code & URL."""
    rl = check_ratelimit(req, bucket="create")

    def code_generator():
        import random
        return "".join(
            random.choice(app.state.EMBED_CODE_CHARSET)
            for _ in range(app.state.EMBED_CODE_SIZE)
        )

    code = code_generator()
    while await app.state.db.fetchrow(
        """
        SELECT * FROM embeds WHERE code = $1;
        """,
        code
    ) is not None:
        code = code_generator()

    await app.state.db.execute(
        """
        INSERT INTO embeds (code, title, description, colour, timestamp, author_name, media_url, owner)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
        """,
        code,
        body.title,
        body.description,
        body.colour,
        datetime.datetime.utcfromtimestamp(body.timestamp),
        body.author_name,
        body.media_url,
        hashlib.sha256(req.client.host.encode()).hexdigest()
    )
    return JSONResponse(
        {
            "code": code,
            "url": str(req.base_url.replace(path="/embed/" + code))
        },
        status.HTTP_201_CREATED,
        headers=rl
    )


@app.put("/embed/{code}", response_class=Response, status_code=status.HTTP_204_NO_CONTENT)
async def update_embed(
        req: Request,
        body: EmbedPayload,
        code: str = PathArg(
            ...,
            title="Embed code",
            description="The code of the saved embed to update.",
        ),
):
    """Updates an existing embed"""
    rl = check_ratelimit(req, bucket="update")
    result = await app.state.db.fetchrow(
        """
        SELECT * FROM embeds WHERE code = $1;
        """,
        code
    )
    if result is None:
        return JSONResponse(
            {
                "detail": "Embed not found."
            },
            status.HTTP_404_NOT_FOUND,
            headers=rl
        )
    if result["owner"] != hashlib.sha256(req.client.host.encode()).hexdigest():
        return JSONResponse(
            {
                "detail": "You do not own this embed."
            },
            status.HTTP_403_FORBIDDEN,
            headers=rl
        )
    await app.state.db.execute(
        """
        UPDATE embeds SET
            title = $2,
            description = $3,
            colour = $4,
            timestamp = $5,
            author_name = $6,
            media_url = $7
        WHERE code = $1;
        """,
        code,
        body.title,
        body.description,
        body.colour,
        datetime.datetime.utcfromtimestamp(body.timestamp),
        body.author_name,
        body.media_url,
    )
    return Response(
        None,
        status.HTTP_204_NO_CONTENT,
        headers=rl
    )


@app.delete("/embed/{code}")
async def delete_embed(
        req: Request,
        code: str = PathArg(
            ...,
            title="Embed code",
            description="The code of the saved embed to delete.",
        ),
):
    """Deletes an embed. The embed code is immediately available for reuse."""
    rl = check_ratelimit(req, bucket="delete")
    result = await app.state.db.fetchrow(
        """
        SELECT * FROM embeds WHERE code = $1;
        """,
        code
    )
    if result is None:
        return JSONResponse(
            {
                "detail": "Embed not found."
            },
            status.HTTP_404_NOT_FOUND,
            headers=rl
        )
    if result["owner"] != hashlib.sha256(req.client.host.encode()).hexdigest():
        return JSONResponse(
            {
                "detail": "You do not own this embed."
            },
            status.HTTP_403_FORBIDDEN,
            headers=rl
        )
    await app.state.db.execute(
        """
        DELETE FROM embeds WHERE code = $1;
        """,
        code
    )
    return Response(
        None,
        status.HTTP_204_NO_CONTENT,
        headers=rl
    )


app.mount(
    "/",
    StaticFiles(
        directory=BASE / "static",
        html=True,
        follow_symlink=True
    ),
    name="static"
)
