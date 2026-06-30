# Personal Assistant Windows Companion

This is the Windows 10/11 tray client for the basement-server controller at:

```text
ws://basement-server:10112/session
```

The client opens one outbound WebSocket. It streams microphone PCM to the controller, sends a
screenshot only when requested or when you choose “Send Screen Context,” receives streamed Qwen text
events, plays returned XTTS PCM audio, and clears playback when the controller emits
`playback.cancel`.

## First-run setup

On first launch the setup form asks for:

- controller URL, usually `http://basement-server:10112`
- device name
- optional WAV/MP3 XTTS reference voice
- whether to share one assistant profile across Windows accounts on this PC

Setup calls:

1. `POST /pair` to receive `device_id`, `profile_id`, and `device_token`.
2. `POST /setup/voice` to proxy the voice reference to XTTS.

The device token is stored with Windows DPAPI. Per-user config lives in:

```text
%LocalAppData%\PersonalAssistant\settings.json
```

When shared-profile mode is enabled, the shared identity is stored in:

```text
%ProgramData%\PersonalAssistant\machine-profile.json
```

Audio device preferences remain per-user.

## Audio and screen formats

- Microphone: binary `PA01` kind `0x01`, PCM16 little-endian, mono, 16 kHz, 20 ms / 640-byte chunks.
- Returned audio: binary `PA01` kind `0x81`, PCM16 little-endian, mono, 24 kHz.
- Screenshots: JPEG `PA01` kind `0x02`, active monitor containing the foreground window.

The tray menu includes Connect, Disconnect, Mute/Unmute, Send Screen Context, Settings, Reset
Pairing, and Exit. VNyan integration is audio-lip-sync-first: use the optional mirror output device
for a lip-sync input path. Direct VNyan hotkeys/UDP can be added later.

## Build

Install the .NET 8 SDK on Windows, then:

```powershell
cd \path\to\personal-assistant\window-install
dotnet test .\PersonalAssistant.Windows.sln
.\scripts\publish-win-x64.ps1
.\install.ps1
```

The publish script creates a self-contained `win-x64` build under `publish\win-x64`.

For normal use, double-click this from File Explorer:

```text
install-or-update.cmd
```

That wrapper runs tests, publishes the app, installs it under `%LocalAppData%\Programs\PersonalAssistant`,
creates a Start Menu shortcut named “Personal Assistant,” launches the app, and pauses so you can
read any error.

## Protocol summary

The binary frame header is 16 bytes, big-endian:

| Offset | Size | Meaning |
|---:|---:|---|
| 0 | 4 | ASCII magic `PA01` |
| 4 | 1 | payload kind |
| 5 | 1 | flags |
| 6 | 2 | reserved zero bytes |
| 8 | 4 | sequence number |
| 12 | 4 | milliseconds since session start |

Every WebSocket connection starts with:

```json
{
  "type": "session.start",
  "protocol": 1,
  "profile_id": "returned-by-pair",
  "voice_id": "optional-voice-id",
  "language": "en",
  "thinking": "medium"
}
```

The client discards stale audio/text by obeying controller `playback.cancel` and `turn_id` events.
