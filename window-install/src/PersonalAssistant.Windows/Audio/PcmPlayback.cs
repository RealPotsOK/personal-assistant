using NAudio.Wave;

namespace PersonalAssistant.Windows.Audio;

public sealed class PcmPlayback : IDisposable
{
    private readonly BufferedWaveProvider _primaryBuffer = new(new WaveFormat(24_000, 16, 1))
    {
        BufferDuration = TimeSpan.FromSeconds(10),
        DiscardOnBufferOverflow = true,
    };
    private readonly BufferedWaveProvider _mirrorBuffer = new(new WaveFormat(24_000, 16, 1))
    {
        BufferDuration = TimeSpan.FromSeconds(10),
        DiscardOnBufferOverflow = true,
    };

    private WaveOutEvent? _primary;
    private WaveOutEvent? _mirror;

    public void Start(int outputDeviceNumber, int? mirrorDeviceNumber)
    {
        Stop();
        _primary = new WaveOutEvent { DeviceNumber = outputDeviceNumber };
        _primary.Init(_primaryBuffer);
        _primary.Play();

        if (mirrorDeviceNumber is int mirror)
        {
            _mirror = new WaveOutEvent { DeviceNumber = mirror };
            _mirror.Init(_mirrorBuffer);
            _mirror.Play();
        }
    }

    public void AddSamples(byte[] pcm)
    {
        _primaryBuffer.AddSamples(pcm, 0, pcm.Length);
        _mirrorBuffer.AddSamples(pcm, 0, pcm.Length);
    }

    public void Clear()
    {
        _primaryBuffer.ClearBuffer();
        _mirrorBuffer.ClearBuffer();
    }

    public void Stop()
    {
        _primary?.Stop();
        _primary?.Dispose();
        _primary = null;
        _mirror?.Stop();
        _mirror?.Dispose();
        _mirror = null;
        Clear();
    }

    public void Dispose() => Stop();
}
