using PersonalAssistant.Windows.Audio;
using PersonalAssistant.Windows.Config;
using PersonalAssistant.Windows.Screen;
using PersonalAssistant.Windows.Session;
using PersonalAssistant.Windows.Setup;

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
    private ToolStripMenuItem? _connectItem;
    private ToolStripMenuItem? _muteItem;
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
        _tray.DoubleClick += async (_, _) => await OpenSettingsAsync();
        Application.ApplicationExit += (_, _) => Cleanup();
        _ = StartAsync();
    }

    private ContextMenuStrip BuildMenu()
    {
        var menu = new ContextMenuStrip();
        _connectItem = new ToolStripMenuItem("Connect", null, async (_, _) => await ToggleConnectionAsync());
        _muteItem = new ToolStripMenuItem("Mute", null, (_, _) => ToggleMute());
        menu.Items.Add(_connectItem);
        menu.Items.Add(_muteItem);
        menu.Items.Add("Send Screen Context", null, async (_, _) => await SendScreenAsync(true));
        menu.Items.Add("Upload / Replace Voice...", null, async (_, _) => await UploadVoiceAsync());
        menu.Items.Add("Settings", null, async (_, _) => await OpenSettingsAsync());
        menu.Items.Add("Reset Pairing", null, (_, _) => ResetPairing());
        menu.Items.Add("Exit", null, (_, _) => ExitThread());
        RefreshMenuLabels();
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

    private async Task ToggleConnectionAsync()
    {
        if (_session?.IsConnected == true)
        {
            await DisconnectAsync();
        }
        else
        {
            await ConnectAsync();
        }
        RefreshMenuLabels();
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
        RefreshMenuLabels();
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
        RefreshMenuLabels();
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
        RefreshMenuLabels();
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

    private async Task UploadVoiceAsync()
    {
        if (_config is null)
        {
            return;
        }

        using var dialog = new OpenFileDialog
        {
            Filter = "Audio reference (*.wav;*.mp3)|*.wav;*.mp3",
            Title = "Choose XTTS voice reference",
        };
        if (dialog.ShowDialog() != DialogResult.OK)
        {
            return;
        }

        try
        {
            _tray.ShowBalloonTip(2000, "Uploading voice", "Caching XTTS voice reference...", ToolTipIcon.Info);
            var result = await new PairingClient().UploadVoiceReferenceAsync(
                _config,
                dialog.FileName,
                _config.DeviceName,
                _shutdown.Token);
            if (!result.Success)
            {
                _tray.ShowBalloonTip(
                    6000,
                    "Voice upload failed",
                    result.ErrorMessage ?? "The server rejected the voice reference.",
                    ToolTipIcon.Warning);
                return;
            }

            _config.VoiceId = result.VoiceId;
            _store.Save(_config);
            var warning = result.Warnings.FirstOrDefault(w => !string.IsNullOrWhiteSpace(w.Message));
            if (warning is not null)
            {
                _tray.ShowBalloonTip(
                    5000,
                    "Voice cached with warning",
                    "Voice cached, but sample is outside recommended 20–30 seconds.",
                    ToolTipIcon.Warning);
            }
            else
            {
                _tray.ShowBalloonTip(
                    3000,
                    "Voice ready",
                    $"Saved {result.VoiceId}. Reconnecting with voice enabled.",
                    ToolTipIcon.Info);
            }
            if (_session?.IsConnected == true)
            {
                await ConnectAsync();
            }
        }
        catch (Exception ex)
        {
            _tray.ShowBalloonTip(5000, "Voice upload failed", ex.Message, ToolTipIcon.Error);
        }
    }

    private async Task OpenSettingsAsync()
    {
        if (_config is null)
        {
            return;
        }

        using var settings = new SettingsForm(_config);
        if (settings.ShowDialog() == DialogResult.OK)
        {
            _store.Save(_config);
            if (_session?.IsConnected == true)
            {
                await ConnectAsync();
            }
        }
    }

    private void RefreshMenuLabels()
    {
        if (_connectItem is not null)
        {
            _connectItem.Text = _session?.IsConnected == true ? "Disconnect" : "Connect";
        }
        if (_muteItem is not null)
        {
            _muteItem.Text = _muted ? "Unmute" : "Mute";
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
