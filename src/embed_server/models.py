import datetime
import os

import pydantic as pd
from fastapi import HTTPException, status


class EmbedPayload(pd.BaseModel):
    """Represents the body of an embed request."""
    code: str | None = pd.Field(
        None,
        title="Embed code",
        description="The code of the saved embed. This is only ever returned to you.",
        examples=[os.urandom(8).hex()],
        max_length=255,
        min_length=4,
        frozen=True
    )

    title: str | None = pd.Field(
        None,
        title="Title",
        description="The title of the embed.",
        examples=["My title", "My Embed"],
        max_length=255,
        min_length=1,
    )
    description: str | None = pd.Field(
        None,
        title="Description",
        description="The description of the embed.",
        examples=["My description", "My Embed"],
        max_length=2048,
        min_length=1,
    )
    colour: int | None = pd.Field(
        None,
        title="Colour",
        description="The colour value of the embed. You should convert your hex values or whatever to decimal.",
        alias="color",
        examples=[0xFFFFFF, 0x000000, 0xFF00FF],
        gt=0,
        le=0xFFFFFF,
    )
    timestamp: float | None = pd.Field(
        default_factory=lambda: datetime.datetime.utcnow().timestamp(),
        title="Timestamp",
        description="The timestamp of the embed. This should be a UNIX timestamp (seconds).",
        examples=[datetime.datetime.utcnow().timestamp()],
        ge=0,
    )
    author_name: str | None = pd.Field(
        None,
        title="Author name",
        description="The name of the author of the embed.",
        examples=["My author"],
        max_length=255,
        min_length=1,
    )
    media_url: str | None = pd.Field(
        None,
        title="Media URL",
        description="The URL of the media of the embed.",
        examples=["https://example.com/media.png"],
        max_length=2048,
        min_length=1,
    )


class RateLimitedException(HTTPException):
    def __init__(
            self,
            headers: dict[str, str]
    ):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You are being rate limited.",
            headers=headers
        )
