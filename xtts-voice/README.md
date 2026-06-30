# XTTS Voice API

A private, Dockerized XTTS-v2 service for the RTX 5060 Ti. It accepts text and a cached cloned
voice, then returns a complete WAV or streams 24 kHz mono PCM audio. A WebSocket endpoint accepts
incremental text and returns audio while later text is still arriving.

The project is a sibling service under `/home/kevin/projects/personal-assistant`. Qwen can remain running; every XTTS
GPU operation is serialized and a VRAM conflict returns `503 gpu_capacity_unavailable` instead of
falling back to CPU.

## 1. Download the model

XTTS-v2 uses the [Coqui Public Model License](https://coqui.ai/cpml). Read it first. If you accept
its terms, download the pinned and checksum-verified model files to the host:

```bash
cd /home/kevin/projects/personal-assistant/xtts-voice
COQUI_TOS_AGREED=1 make download-model
```

The files are stored under `/home/kevin/models/xtts-v2` and mounted read-only in Docker. They are
not copied into the image.

## 2. Configure and run

```bash
cp .env.example .env
# The shared AI_API_KEY is loaded from personal-assistant/.env.ai-services.
docker compose up -d --build
docker compose logs -f xtts-api
```

The API listens at `http://localhost:11112`. Liveness does not require authentication:

```bash
curl http://localhost:11112/live
curl http://localhost:11112/health
```

All other routes require:

```bash
set -a
. /home/kevin/projects/personal-assistant/.env.ai-services
set +a
export AUTH="Authorization: Bearer $AI_API_KEY"
```

## Voices

Reference uploads accept WAV or MP3, default to a 20 MB limit, and must be 3–30 seconds long. Raw
audio is normalized in temporary storage and deleted immediately. Cached voices retain only the
XTTS conditioning tensors and metadata in the `xtts_voice_data` Docker volume.

Preview without saving:

```bash
curl http://localhost:11112/voices/preview \
  -H "$AUTH" \
  -F reference_audio=@speaker.wav \
  -F language=en \
  -F 'text=This uses the reference once and saves no voice.' \
  --output preview.wav
```

Cache a voice and retain the returned `voice_id`:

```bash
curl http://localhost:11112/voices/cache \
  -H "$AUTH" \
  -F reference_audio=@speaker.mp3 \
  -F 'name=Assistant voice'
```

List or delete cached voices:

```bash
curl -H "$AUTH" http://localhost:11112/voices
curl -X DELETE -H "$AUTH" http://localhost:11112/voices/voice_abc123
```

## Speech generation

Complete WAV:

```bash
curl http://localhost:11112/tts \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"text":"Hello, I am your assistant.","voice_id":"voice_abc123","language":"en"}' \
  --output speech.wav
```

OpenAI-style alias:

```bash
curl http://localhost:11112/v1/audio/speech \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"model":"xtts-v2","input":"Hello.","voice":"voice_abc123","response_format":"wav"}' \
  --output speech.wav
```

HTTP audio streaming accepts the complete text and returns headerless signed PCM16 little-endian:

```bash
curl -N http://localhost:11112/tts/stream \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"text":"Audio starts before the whole clip is rendered.","voice_id":"voice_abc123"}' \
  --output speech.pcm
```

Response headers describe the audio as 24,000 Hz, one channel, `s16le`. Convert it for inspection:

```bash
ffmpeg -f s16le -ar 24000 -ac 1 -i speech.pcm speech-from-stream.wav
```

## Duplex WebSocket streaming

`/ws/tts` is the text-in/audio-out interface for streaming LLM output. Authenticate with the normal
Bearer header, then send JSON events:

```json
{"type":"start","voice_id":"voice_abc123","language":"en"}
{"type":"text_delta","text":"This text can arrive "}
{"type":"text_delta","text":"token by token. The first sentence is committed here. "}
{"type":"text_delta","text":"The next sentence may arrive while audio is playing."}
{"type":"finish"}
```

The server buffers deltas to punctuation or 240 characters, preserves segment order, and emits:

- JSON `ready`, `segment_start`, `segment_end`, and `done` events.
- Binary PCM16 audio frames between segment events.
- JSON `error` or `cancelled` events when appropriate.

Send `commit` to flush an unfinished sentence or `cancel` to stop. Direct browser WebSockets cannot
set an Authorization header, so browser apps should connect through their own authenticated backend
proxy rather than exposing the XTTS key.

## Development

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check app tests scripts
.venv/bin/python -m pytest -q
docker compose config
```

The test suite uses a fake inference engine and does not load model weights. GPU smoke tests require
the licensed model files. The service has one Uvicorn worker and one bounded inference queue because
XTTS streaming is not safe for concurrent access to a single model instance.
