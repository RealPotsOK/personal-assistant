# Personal Assistant Session Controller

The controller exposes one authenticated, multiplexed WebSocket at:

```text
ws://basement-server:10112/session
```

It forwards live microphone audio to Whisper, streams Qwen text, optionally attaches fresh screen
context, feeds completed sentences to XTTS, returns PCM audio, maintains bounded profile memory, and
emits VNyan-friendly avatar states. The Windows capture/playback client is intentionally outside
this repository.

## Authentication and startup

Internal model calls use `AI_API_KEY`. The controller accepts either the admin `PA_CLIENT_TOKEN` or
a paired Windows device token on `/session`; never copy `AI_API_KEY` to the PC. The admin secrets are
stored in the untracked mode-0600 file:

```text
/home/kevin/projects/personal-assistant/.env.ai-services
```

Run the service:

```bash
cd /home/kevin/projects/personal-assistant
docker compose up -d --build
curl http://localhost:10112/live
curl http://localhost:10112/health
```

`/live` reports controller process health. `/health` reports Qwen, Whisper, and XTTS status. Qwen
and Whisper are required for full readiness; unavailable XTTS produces a text-only session.

## Getting the assistant's attention

The v1 Windows companion has no wake word yet. Once the tray app is connected and unmuted, it is
always listening through Whisper. Speak naturally, then pause; after Whisper finalizes your utterance
the controller sends it to Qwen. While Qwen/XTTS is thinking or speaking, talking again triggers
barge-in and cancels the old turn.

Barge-in intentionally waits briefly after Whisper finalizes your phrase so leftover mic audio does
not cancel the answer before it starts. The defaults require sustained speech-like audio after that
grace period. If your room is still too noisy, increase `BARGE_IN_GRACE_SECONDS` or
`BARGE_IN_TRIGGER_FRAMES`; if interruptions feel sluggish, lower them slightly.

For visual questions, say something like “what is this on my screen?” or use the tray menu’s
“Send Screen Context” action. The controller will request one fresh screenshot only when it needs
screen context.

## Conversation debug log

The controller writes a local JSONL debug log for final Whisper transcripts, completed Qwen answers,
interruptions, TTS fallback notices, and turn errors. It never logs raw audio or screenshot bytes.

Default host path:

```text
/home/kevin/projects/personal-assistant/logs/conversation.log
```

Watch it live:

```bash
cd /home/kevin/projects/personal-assistant
tail -f logs/conversation.log
```

Each line is JSON, for example:

```json
{"ts":"2026-06-30T18:00:00+00:00","event":"whisper.final","profile_id":"...","text":"what time is it"}
{"ts":"2026-06-30T18:00:02+00:00","event":"qwen.completed","profile_id":"...","turn_id":"...","transcript":"what time is it","response":"..."}
```

Disable it or change its location with:

```dotenv
CONVERSATION_LOG_ENABLED=false
CONVERSATION_LOG_PATH=/logs/conversation.log
CONVERSATION_LOG_MAX_BYTES=10485760
```

## Windows client pairing

The normal PC setup flow is:

1. The Windows companion posts to `POST /pair` on the LAN.
2. The controller returns a generated `device_id`, `profile_id`, and `device_token`.
3. The Windows app stores that device token with DPAPI and uses it as
   `Authorization: Bearer <device_token>` for `/session`.

Manual pairing example:

```bash
curl http://basement-server:10112/pair \
  -H 'Content-Type: application/json' \
  -d '{"device_name":"Kevin Desktop"}'
```

The response includes the only copy of `device_token`; store it somewhere private if you are testing
without the Windows app. Device tokens are bound to their returned `profile_id`, so reconnecting with
the same token restores that profile’s recent turns and durable memories. `PAIRING_ENABLED=false`
disables new pairings after setup while existing device tokens continue to work.

To revoke a paired Windows token from the client:

```bash
curl -X POST http://basement-server:10112/device/revoke-self \
  -H "Authorization: Bearer $PA_DEVICE_TOKEN"
```

## Voice setup proxy

The Windows client can upload a WAV or MP3 reference through the controller. The controller forwards
the file to XTTS with the internal `AI_API_KEY`; the PC never sees that key.

```bash
curl http://basement-server:10112/setup/voice \
  -H "Authorization: Bearer $PA_DEVICE_TOKEN" \
  -F reference_audio=@speaker.wav \
  -F 'name=Kevin voice'
```

If XTTS is unavailable or its model weights are missing, the endpoint returns a recoverable
`xtts_unavailable` response. The Windows client should keep the reference locally only while a retry
is pending.

## Session handshake

Connect with `Authorization: Bearer $PA_CLIENT_TOKEN` for admin/manual testing, or with a paired
device token for the Windows client. Then send:

```json
{
  "type": "session.start",
  "protocol": 1,
  "profile_id": "kevin-pc",
  "voice_id": "voice_abc123",
  "language": "en",
  "thinking": "medium"
}
```

`profile_id` accepts 1–64 letters, numbers, dots, dashes, or underscores. `voice_id` may be omitted
when `DEFAULT_XTTS_VOICE_ID` is configured. Thinking modes are `instant`, `medium`, and `long`.
Only one PC session may be active; another connection is closed with code `4429`. A paired device
token may only use its assigned `profile_id`.

## Binary frame format

Every binary WebSocket message contains a 16-byte network-byte-order header followed by its payload:

| Offset | Size | Meaning |
|---:|---:|---|
| 0 | 4 | ASCII magic `PA01` |
| 4 | 1 | Payload kind |
| 5 | 1 | Flags, currently zero |
| 6 | 2 | Reserved, must be zero |
| 8 | 4 | Unsigned sequence number |
| 12 | 4 | Unsigned milliseconds since session start |

Payload kinds:

| Hex | Direction | Payload |
|---:|---|---|
| `01` | PC → server | PCM16 little-endian, mono, 16 kHz microphone audio |
| `02` | PC → server | JPEG screen frame |
| `03` | PC → server | PNG screen frame |
| `81` | Server → PC | PCM16 little-endian, mono, 24 kHz XTTS audio |

Sequence numbers must increase independently for each payload kind. Audio can be sent in 20 ms
chunks: 320 samples or 640 bytes before the header. JPEG/PNG frames are limited to 5 MiB and are
downsampled to the configured Qwen pixel limit. Audio and screen bytes are never persisted.

Before a screen binary frame, optional metadata can be sent with the same sequence:

```json
{
  "type": "screen.metadata",
  "sequence": 42,
  "explicit": true,
  "application": "Visual Studio Code",
  "window_title": "app.py"
}
```

The controller uses a frame only for visually referential speech. If no frame newer than 10 seconds
exists, it emits `screen.request` and waits up to 750 ms before continuing without it.

## JSON events

PC-to-controller control events:

```json
{"type":"audio.commit"}
{"type":"interrupt"}
{"type":"session.update","thinking":"instant","voice_id":"voice_abc123"}
{"type":"memory.list"}
{"type":"memory.delete","memory_id":"..."}
{"type":"memory.clear"}
{"type":"conversation.clear"}
{"type":"ping","id":"client-value"}
{"type":"disconnect"}
```

The controller emits:

- `session.ready`, `session.updated`, `pong`
- `transcript.partial`, `transcript.final`
- `assistant.delta`, `assistant.completed`, `sources`
- `screen.request`
- `audio.start`, binary kind `81` frames, `audio.end`
- `playback.cancel`
- `memory.used`, `memory.updated`, `memory.list`, `memory.deleted`, `memory.cleared`
- `conversation.cleared`, `error`
- `avatar.state` with `idle`, `listening`, `thinking`, or `speaking`

Turn-related events include `turn_id`. The PC must discard stale events and immediately clear its
playback buffer on `playback.cancel`. The microphone stays live while audio plays; headphones or
client-side acoustic echo cancellation are required for reliable barge-in.

## Minimal Python protocol example

This demonstrates framing only; the full Windows tray client lives in `window-install/`:

```python
import asyncio, json, os, struct, time
import websockets

HEADER = struct.Struct(">4sBBHII")

def frame(kind: int, sequence: int, payload: bytes, started: float) -> bytes:
    elapsed_ms = int((time.monotonic() - started) * 1000) & 0xFFFFFFFF
    return HEADER.pack(b"PA01", kind, 0, 0, sequence, elapsed_ms) + payload

async def main():
    started = time.monotonic()
    async with websockets.connect(
        "ws://basement-server:10112/session",
        additional_headers={"Authorization": f"Bearer {os.environ['PA_CLIENT_TOKEN']}"},
    ) as ws:
        await ws.send(json.dumps({
            "type": "session.start", "protocol": 1, "profile_id": "kevin-pc",
            "language": "en", "thinking": "medium"
        }))
        print(await ws.recv())
        # pcm_20ms must contain 640 bytes of mono 16 kHz PCM16 audio.
        # await ws.send(frame(0x01, 1, pcm_20ms, started))
        async for message in ws:
            if isinstance(message, bytes):
                magic, kind, flags, reserved, sequence, timestamp = HEADER.unpack_from(message)
                if kind == 0x81:
                    pcm_24khz = message[HEADER.size:]
                    # Send pcm_24khz to the playback device.
            else:
                event = json.loads(message)
                print(event)

asyncio.run(main())
```

## Persistence and interruption

SQLite retains the latest 24 completed transcript/answer turns and up to 100 deduplicated durable
memories per profile. Memory extraction runs as a low-priority Qwen task. Partial, failed, and
interrupted answers are not added to future context.

While Qwen or XTTS is active, sustained microphone speech triggers barge-in. The controller cancels
generation, closes XTTS streaming, emits `playback.cancel`, discards stale output, and continues the
Whisper stream for the new utterance.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check app tests
.venv/bin/python -m pytest -q
docker compose config --services
```

The controller runs without a GPU. Qwen, Whisper, and XTTS remain independent Docker services on
ports 11111, 11113, and 11112 respectively.

## Windows companion source

The Windows tray companion lives in:

```text
window-install/
```

It is a .NET 8 WinForms app that pairs through `/pair`, stores its device token with Windows DPAPI,
streams 16 kHz mic PCM over the controller WebSocket, sends active-monitor screenshots on request,
plays returned 24 kHz PCM audio, supports optional mirror output for VNyan audio lip sync, and
packages with `window-install/scripts/publish-win-x64.ps1`.
