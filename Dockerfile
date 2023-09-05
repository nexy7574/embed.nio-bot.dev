FROM python:3.11-alpine
RUN apk update
RUN apk add gcc musl-dev libffi-dev openssl-dev
RUN pip install -U pip wheel setuptools
WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt marko

COPY src/embed_server src
RUN python -m marko src/static/about.md > src/static/about.html

EXPOSE 8000
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
