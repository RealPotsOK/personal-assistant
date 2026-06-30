FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp

WORKDIR /app

RUN groupadd --gid 10004 app \
    && useradd --uid 10004 --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown app:app /data

COPY requirements.txt ./
RUN python -m pip install --upgrade pip==25.1.1 \
    && python -m pip install -r requirements.txt

COPY --chown=app:app app ./app

USER app
EXPOSE 10112

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10112/live', timeout=3)"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10112", "--workers", "1", "--ws-max-size", "6291456"]
