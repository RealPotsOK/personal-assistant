FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    HF_HOME=/tmp/huggingface \
    NUMBA_CACHE_DIR=/tmp/numba \
    MODEL_PATH=/models/xtts-v2 \
    VOICE_DIR=/data/voices

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10002 app \
    && useradd --uid 10002 --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/voices \
    && chown -R app:app /data

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install --index-url https://download.pytorch.org/whl/cu128 torchaudio==2.8.0 \
    && python -m pip install -r requirements.txt

COPY --chown=app:app app ./app

USER app
EXPOSE 11112

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:11112/live', timeout=3)"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "11112", "--workers", "1"]
