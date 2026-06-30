# Qwen3-VL API

A stateless, OpenAI-compatible FastAPI server for the local
`qwen3-vl-8b-instruct` model. It accepts text and images, retrieves public
webpages mentioned in the latest user message, follows a bounded set of relevant
same-site links, and supports regular or streamed responses.

## Requirements

- Linux with Docker Engine and Docker Compose
- NVIDIA driver and NVIDIA Container Toolkit
- An NVIDIA GPU with enough memory for the selected quantization
- Model files at `/home/kevin/models/qwen3-vl-8b-instruct` by default

The service uses 4-bit quantization by default for the 16 GB RTX 5060 Ti. Model
loading is offline: the model directory is mounted read-only and no weights are
downloaded into the image.

## Start the server

```bash
cp .env.example .env
docker compose build
docker compose up -d
docker compose logs -f qwen-api
```

If the model is elsewhere, change `MODEL_PATH_HOST` in `.env`. The API listens
on `http://localhost:11111`. Model routes require the shared bearer key from
`/home/kevin/projects/personal-assistant/.env.ai-services`; `/health` remains public.

```bash
set -a
. /home/kevin/projects/personal-assistant/.env.ai-services
set +a
export AUTH="Authorization: Bearer $AI_API_KEY"
```

Check readiness:

```bash
curl -s http://localhost:11111/health
curl -s -H "$AUTH" http://localhost:11111/v1/models
```

## Text request

```bash
curl http://localhost:11111/v1/chat/completions \
  -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-vl-8b-instruct",
    "messages": [
      {"role": "user", "content": "Explain why the sky is blue in two sentences."}
    ]
  }'
```

## Remote image

```bash
curl http://localhost:11111/v1/chat/completions \
  -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-vl-8b-instruct",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "Describe this image."},
        {"type": "image_url", "image_url": {"url": "https://example.com/photo.jpg"}}
      ]
    }]
  }'
```

For a local image, send a data URL:

```bash
IMAGE_DATA=$(base64 -w 0 ./photo.jpg)
curl http://localhost:11111/v1/chat/completions \
  -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d "{\
    \"model\":\"qwen3-vl-8b-instruct\",\
    \"messages\":[{\"role\":\"user\",\"content\":[\
      {\"type\":\"text\",\"text\":\"What is in this image?\"},\
      {\"type\":\"image_url\",\"image_url\":{\"url\":\"data:image/jpeg;base64,$IMAGE_DATA\"}}\
    ]}]\
  }"
```

## Website request

URLs and bare domains in the latest user message are detected automatically:

```bash
curl http://localhost:11111/v1/chat/completions \
  -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-vl-8b-instruct",
    "messages": [{
      "role": "user",
      "content": "Tell me about coffeeandcafe.com and summarize its menu."
    }]
  }'
```

The server retrieves the starting page and ranks same-origin links such as
`/menu`, `/products`, and `/about` against the question. It returns the pages it
used in the top-level `web_sources` array. Retrieval is request-scoped and does
not create a persistent index.

Only server-rendered HTML is supported. JavaScript-only sites may expose little
or no readable content. Private, loopback, link-local, reserved, and cloud
metadata network addresses are blocked. Redirects are validated, crawl limits
are enforced, and `robots.txt` is respected.

## Streaming

Set `stream` to `true` to receive server-sent events:

```bash
curl -N http://localhost:11111/v1/chat/completions \
  -H "$AUTH" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3-vl-8b-instruct",
    "messages": [{"role": "user", "content": "Write a short haiku about coffee."}],
    "stream": true
  }'
```

The stream ends with `data: [DONE]`.

Streaming generation stops promptly when the client disconnects. Trusted internal callers may set
`X-AI-Priority` to `realtime`, `normal`, or `background`; priority affects queued work only and never
preempts an active generation.

## Multi-turn conversations

The server stores no conversation state. Resend the complete history:

```json
{
  "model": "qwen3-vl-8b-instruct",
  "messages": [
    {"role": "user", "content": "My favorite roast is medium."},
    {"role": "assistant", "content": "Got it."},
    {"role": "user", "content": "What roast did I say I prefer?"}
  ]
}
```

Only URLs in the latest user message are fetched, preventing old URLs from being
downloaded again whenever history is resent.

## Configuration

All limits are environment variables documented in `.env.example`. The main
controls are:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `QUANTIZATION` | `4bit` | `4bit` or `8bit` bitsandbytes loading |
| `DEFAULT_MAX_TOKENS` | `512` | Default generated token limit |
| `MAX_TOKENS` | `2048` | Maximum client-requested token limit |
| `MAX_IMAGES` | `4` | Images accepted in one request |
| `MAX_IMAGE_BYTES` | `10485760` | Maximum bytes per image |
| `MAX_IMAGE_PIXELS` | `1048576` | Images are resized to this pixel budget |
| `MAX_WEB_PAGES` | `5` | Maximum pages retrieved per request |
| `MAX_WEB_DEPTH` | `1` | Same-site link traversal depth |
| `MAX_WEB_TOTAL_CHARS` | `40000` | Total webpage context budget |
| `FETCH_TIMEOUT_SECONDS` | `10` | Timeout for one HTTP operation |
| `CRAWL_TIMEOUT_SECONDS` | `20` | Total crawl deadline |

Generation requests are serialized through a priority-aware queue because one model instance owns the GPU.
Website and image retrieval can occur concurrently before a request enters the
generation queue.

## Development tests

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
docker compose config
```

The unit suite mocks inference and does not load model weights. A final GPU smoke
test requires starting the Docker service and sending the examples above.
