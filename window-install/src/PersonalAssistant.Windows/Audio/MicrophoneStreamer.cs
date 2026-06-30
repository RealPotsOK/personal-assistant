using NAudio.Wave;
using PersonalAssistant.Windows.Session;

namespace PersonalAssistant.Windows.Audio;

public sealed class MicrophoneStreamer : IDisposable
{
    private readonly AssistantSessionClient _session;
    private readonly CancellationToken _cancellationToken;
    private WaveInEvent? _capture;
    private readonly MemoryStream _buffer = new();

    public MicrophoneStreamer(AssistantSessionClient session, CancellationToken cancellationToken)
    {
        _session = session;
        _cancellationToken = cancellationToken;
    }

    public void Start(int deviceNumber)
    {
        Stop();
        _capture = new WaveInEvent
        {
            DeviceNumber = Math.Max(0, deviceNumber),
            WaveFormat = new WaveFormat(16_000, 16, 1),
            BufferMilliseconds = 20,
        };
        _capture.DataAvailable += OnDataAvailable;
        _capture.StartRecording();
    }

    public void Stop()
    {
        if (_capture is null)
        {
            return;
        }

        _capture.DataAvailable -= OnDataAvailable;
        _capture.StopRecording();
        _capture.Dispose();
        _capture = null;
        _buffer.SetLength(0);
    }

    public void Dispose()
    {
        Stop();
        _buffer.Dispose();
    }

    private void OnDataAvailable(object? sender, WaveInEventArgs args)
    {
        _buffer.Write(args.Buffer, 0, args.BytesRecorded);
        while (_buffer.Length >= 640)
        {
            var data = _buffer.ToArray();
            var frame = data[..640];
            var remaining = data[640..];
            _buffer.SetLength(0);
            _buffer.Write(remaining);
            _ = _session.SendMicPcmAsync(frame, _cancellationToken);
        }
    }
}
