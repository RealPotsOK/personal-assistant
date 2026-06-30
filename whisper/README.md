# Whisper Small Speech-to-Text API

A stateless, Dockerized speech-to-text service using `faster-whisper` and one locally mounted
CTranslate2 Whisper model. The default is English `small.en`; multilingual `small` can be selected
through configuration and a container restart.

The API accepts WAV and MP3 uploads, returns OpenAI-compatible transcripts, streams completed file
segments over SSE, and supports live PCM microphone audio over WebSocket.

## Shared authentication

Qwen, XTTS, Whisper, and server-side controllers read the same untracked secret from:

```text
/home/kevin/projects/personal-assistant/.env.ai-services
```

Export it for command-line calls without printing the value:

```bash
set -a
. /home/kevin/projects/personal-assistant/.env.ai-services
set +a
```

## Download the model

Download the pinned, checksum-verified English model:

```bash
cd /home/kevin/projects/personal-assistant/whisper
make download-model
```

For multilingual transcription and translation:

```bash
make download-model MODEL_VARIANT=small MODEL_PATH_HOST=/home/kevin/models/whisper/small
```

Weights remain on the host and are mounted read-only; startup never downloads a model.

## Run

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f whisper-api
```

The API listens at `http://localhost:11113`. `/live` and `/health` are public; model operations
require `Authorization: Bearer $AI_API_KEY`.

## File transcription

JSON response:

```bash
curl http://localhost:11113/v1/audio/transcriptions \
  -H "Authorization: Bearer $AI_API_KEY" \
  -F file=@recording.wav \
  -F model=whisper-small.en
```

Verbose timestamps:

```bash
curl http://localhost:11113/v1/audio/transcriptions \
  -H "Authorization: Bearer $AI_API_KEY" \
  -F file=@recording.mp3 \
  -F response_format=verbose_json \
  -F word_timestamps=true
```

Response formats are `json`, `text`, and `verbose_json`. Optional fields include `language`,
`prompt`, and `temperature`. The English model rejects non-English languages and translation with a
clear error.

With multilingual `small`, translation to English uses:

```bash
curl http://localhost:11113/v1/audio/translations \
  -H "Authorization: Bearer $AI_API_KEY" \
  -F file=@recording.mp3 \
  -F model=whisper-small
```

## SSE file streaming

The complete file is uploaded first, then completed Whisper segments arrive incrementally:

```bash
curl -N http://localhost:11113/transcribe/stream \
  -H "Authorization: Bearer $AI_API_KEY" \
  -F file=@recording.wav
```

Events are `transcript.segment`, `transcript.completed`, and `error`.

## Live WebSocket transcription

Connect to `ws://localhost:11113/ws/transcribe` with the bearer header. Send this first:

```json
{
  "type": "start",
  "sample_rate": 16000,
  "channels": 1,
  "sample_format": "s16le",
  "language": "en"
}
```

Then send raw binary mono PCM16 little-endian frames. The server emits revisable `partial` events
about every 800 ms and stable `final` events after approximately 700 ms of silence. Control events:

```json
{"type":"commit"}
{"type":"finish"}
{"type":"cancel"}
```

Whisper is a windowed model, so partial text may change. Forced 28-second utterance boundaries use a
one-second overlap and remove duplicated words from the following final result.

Browser WebSockets cannot set an Authorization header. Browser microphone clients should proxy the
connection through the personal-assistant backend so the shared key never reaches browser code.

## Switch models

Only one model is mounted and loaded. To switch to multilingual `small`, edit `.env`:

```dotenv
WHISPER_MODEL_VARIANT=small
WHISPER_MODEL_PATH_HOST=/home/kevin/models/whisper/small
MODEL_ID=whisper-small
```

Then recreate the service:

```bash
docker compose down
docker compose up -d
```

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check app tests scripts
.venv/bin/python -m pytest -q
docker compose config --services
```

Uploads and transcripts are never persisted. The service uses one model instance, one GPU inference
lock, and a bounded queue. CUDA capacity failures return HTTP 503 without switching to CPU.
