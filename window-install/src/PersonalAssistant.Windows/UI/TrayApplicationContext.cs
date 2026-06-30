using PersonalAssistant.Windows.Audio;
using PersonalAssistant.Windows.Config;
using PersonalAssistant.Windows.Screen;
using PersonalAssistant.Windows.Session;

namespace PersonalAssistant.Windows.UI;

public sealed class TrayApplicationContext : ApplicationContext
{
    private readonly ConfigStore _store = new();
    private readonly NotifyIcon _tray;
    private readonly CancellationTokenSource _shutdown = new();
    private AppConfig? _config;
    private AssistantSessionClient? _session;
    private MicrophoneStreamer? _microphone;
    private PcmPlayback? _playback;
    private bool _muted;

    public TrayApplicationContext()
    {
        _tray = new NotifyIcon
        {
            Icon = SystemIcons.Application,
            Text = "Personal Assistant",
            Visible = true,
            ContextMenuStrip = BuildMenu(),
        };
        Application.ApplicationExit += (_, _) => Cleanup();
        _ = StartAsync();
    }

    private ContextMenuStrip BuildMenu()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("Connect", null, async (_, _) => await ConnectAsync());
        menu.Items.Add("Disconnect", null, async (_, _) => await DisconnectAsync());
        menu.Items.Add("Mute / Unmute", null, (_, _) => ToggleMute());
        menu.Items.Add("Send Screen Context", null, async (_, _) => await SendScreenAsync(true));
        menu.Items.Add("Settings", null, (_, _) => OpenSettings());
        menu.Items.Add("Reset Pairing", null, (_, _) => ResetPairing());
        menu.Items.Add("Exit", null, (_, _) => ExitThread());
        return menu;
    }

    private async Task StartAsync()
    {
        _config = _store.Load();
        if (_config is null)
        {
            using var setup = new SetupForm(_store);
            if (setup.ShowDialog() != DialogResult.OK)
            {
                ExitThread();
                return;
            }
            _config = setup.Result;
        }
        await ConnectAsync();
    }

    private async Task ConnectAsync()
    {
        if (_config is null)
        {
            return;
        }

        await DisconnectAsync();
        _session = new AssistantSessionClient();
        _session.AudioReceived += bytes => _playback?.AddSamples(bytes);
        _session.PlaybackCancelRequested += () => _playback?.Clear();
        _session.ScreenRequested += async () => await SendScreenAsync(false);
        _session.StatusChanged += status =>
        {
            _tray.Text = ("Assistant: " + status)[..Math.Min(63, ("Assistant: " + status).Length)];
        };

        _playback = new PcmPlayback();
        _playback.Start(_config.OutputDeviceNumber, _config.MirrorOutputDeviceNumber);
        await _session.ConnectAsync(_config, _shutdown.Token);
        _microphone = new MicrophoneStreamer(_session, _shutdown.Token);
        if (!_muted)
        {
            _microphone.Start(_config.InputDeviceNumber);
        }
    }

    private async Task DisconnectAsync()
    {
        _microphone?.Dispose();
        _microphone = null;
        _playback?.Dispose();
        _playback = null;
        if (_session is not null)
        {
            await _session.DisconnectAsync();
            await _session.DisposeAsync();
            _session = null;
        }
    }

    private void ToggleMute()
    {
        _muted = !_muted;
        if (_muted)
        {
            _microphone?.Stop();
        }
        else if (_config is not null && _session is not null)
        {
            _microphone ??= new MicrophoneStreamer(_session, _shutdown.Token);
            _microphone.Start(_config.InputDeviceNumber);
        }
    }

    private async Task SendScreenAsync(bool explicitRequest)
    {
        if (_config is null || _session is null || !_session.IsConnected)
        {
            return;
        }

        try
        {
            var jpeg = ScreenCapture.CaptureActiveMonitorJpeg(_config.JpegQuality);
            await _session.SendScreenJpegAsync(jpeg, explicitRequest, _shutdown.Token);
        }
        catch (Exception ex)
        {
            _tray.ShowBalloonTip(3000, "Screen capture failed", ex.Message, ToolTipIcon.Warning);
        }
    }

    private void OpenSettings()
    {
        if (_config is null)
        {
            return;
        }

        using var settings = new SettingsForm(_config);
        if (settings.ShowDialog() == DialogResult.OK)
        {
            _store.Save(_config);
        }
    }

    private void ResetPairing()
    {
        var path = _store.UserConfigPath;
        if (File.Exists(path))
        {
            File.Delete(path);
        }
        _tray.ShowBalloonTip(3000, "Pairing reset", "Restart the app to pair again.", ToolTipIcon.Info);
    }

    private void Cleanup()
    {
        _shutdown.Cancel();
        _tray.Visible = false;
        _tray.Dispose();
        _microphone?.Dispose();
        _playback?.Dispose();
        _session?.DisposeAsync().AsTask().GetAwaiter().GetResult();
        _shutdown.Dispose();
    }
}
