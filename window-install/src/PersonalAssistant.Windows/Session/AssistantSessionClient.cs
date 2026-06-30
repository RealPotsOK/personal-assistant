using System.Diagnostics;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using PersonalAssistant.Windows.Config;
using PersonalAssistant.Windows.Protocol;

namespace PersonalAssistant.Windows.Session;

public sealed class AssistantSessionClient : IAsyncDisposable
{
    private const int MaxFrameBytes = 8 * 1024 * 1024;
    private readonly SemaphoreSlim _sendLock = new(1, 1);
    private ClientWebSocket? _socket;
    private readonly Stopwatch _clock = new();
    private uint _micSequence;
    private uint _screenSequence;

    public event Action<string>? JsonReceived;
    public event Action<byte[]>? AudioReceived;
    public event Action? PlaybackCancelRequested;
    public event Action? ScreenRequested;
    public event Action<string>? StatusChanged;

    public bool IsConnected => _socket?.State == WebSocketState.Open;

    public async Task ConnectAsync(AppConfig config, CancellationToken cancellationToken)
    {
        config.ValidateForSession();
        _socket = new ClientWebSocket();
        _socket.Options.SetRequestHeader("Authorization", $"Bearer {config.DeviceToken}");
        await _socket.ConnectAsync(config.SessionUri, cancellationToken);
        _clock.Restart();
        await SendJsonAsync(new
        {
            type = "session.start",
            protocol = 1,
            profile_id = config.ProfileId,
            voice_id = config.VoiceId,
            language = config.Language,
            thinking = config.Thinking,
        }, cancellationToken);
        _ = Task.Run(() => ReceiveLoopAsync(cancellationToken), cancellationToken);
        StatusChanged?.Invoke("connected");
    }

    public Task SendMicPcmAsync(ReadOnlyMemory<byte> pcm, CancellationToken cancellationToken)
        => SendBinaryAsync(PayloadKind.MicPcm16, pcm, ++_micSequence, cancellationToken);

    public async Task SendScreenJpegAsync(byte[] jpeg, bool explicitRequest, CancellationToken cancellationToken)
    {
        var sequence = ++_screenSequence;
        await SendJsonAsync(new
        {
            type = "screen.metadata",
            sequence,
            @explicit = explicitRequest,
            application = "Windows",
            window_title = NativeWindow.GetForegroundWindowTitle(),
        }, cancellationToken);
        await SendBinaryAsync(PayloadKind.ScreenJpeg, jpeg, sequence, cancellationToken);
    }

    public Task InterruptAsync(CancellationToken cancellationToken)
        => SendJsonAsync(new { type = "interrupt" }, cancellationToken);

    public Task UpdateThinkingAsync(string thinking, CancellationToken cancellationToken)
        => SendJsonAsync(new { type = "session.update", thinking }, cancellationToken);

    public async Task DisconnectAsync()
    {
        if (_socket is { State: WebSocketState.Open } socket)
        {
            await SendJsonAsync(new { type = "disconnect" }, CancellationToken.None);
            await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "disconnect", CancellationToken.None);
        }
    }

    public async ValueTask DisposeAsync()
    {
        _sendLock.Dispose();
        if (_socket is not null)
        {
            _socket.Dispose();
        }
        await Task.CompletedTask;
    }

    private async Task SendJsonAsync(object payload, CancellationToken cancellationToken)
    {
        var json = JsonSerializer.Serialize(payload);
        await SendRawAsync(Encoding.UTF8.GetBytes(json), WebSocketMessageType.Text, cancellationToken);
    }

    private Task SendBinaryAsync(PayloadKind kind, ReadOnlyMemory<byte> payload, uint sequence, CancellationToken cancellationToken)
    {
        var timestamp = (uint)Math.Min(uint.MaxValue, _clock.ElapsedMilliseconds);
        var frame = FrameCodec.Encode(kind, payload.Span, sequence, timestamp);
        return SendRawAsync(frame, WebSocketMessageType.Binary, cancellationToken);
    }

    private async Task SendRawAsync(byte[] bytes, WebSocketMessageType type, CancellationToken cancellationToken)
    {
        if (_socket is not { State: WebSocketState.Open } socket)
        {
            return;
        }

        await _sendLock.WaitAsync(cancellationToken);
        try
        {
            await socket.SendAsync(bytes.AsMemory(), type, true, cancellationToken);
        }
        finally
        {
            _sendLock.Release();
        }
    }

    private async Task ReceiveLoopAsync(CancellationToken cancellationToken)
    {
        var buffer = new byte[MaxFrameBytes];
        try
        {
            while (_socket is { State: WebSocketState.Open } socket && !cancellationToken.IsCancellationRequested)
            {
                using var message = new MemoryStream();
                WebSocketReceiveResult result;
                do
                {
                    result = await socket.ReceiveAsync(buffer.AsMemory(), cancellationToken);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        StatusChanged?.Invoke("disconnected");
                        return;
                    }
                    message.Write(buffer, 0, result.Count);
                } while (!result.EndOfMessage);

                var bytes = message.ToArray();
                if (result.MessageType == WebSocketMessageType.Text)
                {
                    HandleJson(Encoding.UTF8.GetString(bytes));
                }
                else
                {
                    var frame = FrameCodec.Decode(bytes, MaxFrameBytes);
                    if (frame.Kind == PayloadKind.TtsPcm16)
                    {
                        AudioReceived?.Invoke(frame.Payload);
                    }
                }
            }
        }
        catch (OperationCanceledException)
        {
        }
        catch (Exception ex)
        {
            StatusChanged?.Invoke($"error: {ex.Message}");
        }
    }

    private void HandleJson(string json)
    {
        JsonReceived?.Invoke(json);
        using var doc = JsonDocument.Parse(json);
        var type = doc.RootElement.TryGetProperty("type", out var value) ? value.GetString() : "";
        switch (type)
        {
            case "screen.request":
                ScreenRequested?.Invoke();
                break;
            case "playback.cancel":
                PlaybackCancelRequested?.Invoke();
                break;
            case "avatar.state":
                if (doc.RootElement.TryGetProperty("state", out var state))
                {
                    StatusChanged?.Invoke(state.GetString() ?? "state");
                }
                break;
        }
    }
}
