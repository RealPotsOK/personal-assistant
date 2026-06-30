using PersonalAssistant.Windows.Config;
using PersonalAssistant.Windows.Setup;

namespace PersonalAssistant.Windows.UI;

public sealed class SetupForm : Form
{
    private readonly ConfigStore _store;
    private readonly TextBox _server = new() { Width = 340, Text = "http://basement-server:10112" };
    private readonly TextBox _deviceName = new() { Width = 340, Text = Environment.MachineName };
    private readonly TextBox _voicePath = new() { Width = 260 };
    private readonly CheckBox _shared = new() { Text = "Share one assistant profile across Windows accounts on this PC", AutoSize = true };
    private readonly Label _status = new() { AutoSize = true, Text = "Ready" };

    public AppConfig? Result { get; private set; }

    public SetupForm(ConfigStore store)
    {
        _store = store;
        Text = "Personal Assistant Setup";
        Width = 520;
        Height = 300;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;

        var chooseVoice = new Button { Text = "Browse...", Width = 80 };
        chooseVoice.Click += (_, _) =>
        {
            using var dialog = new OpenFileDialog
            {
                Filter = "Audio reference (*.wav;*.mp3)|*.wav;*.mp3",
                Title = "Choose XTTS voice reference",
            };
            if (dialog.ShowDialog(this) == DialogResult.OK)
            {
                _voicePath.Text = dialog.FileName;
            }
        };

        var pair = new Button { Text = "Pair and Save", Width = 120 };
        pair.Click += async (_, _) => await PairAsync();

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(14),
            ColumnCount = 3,
            RowCount = 7,
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90));
        AddRow(layout, 0, "Server URL", _server, null);
        AddRow(layout, 1, "Device name", _deviceName, null);
        AddRow(layout, 2, "Voice file", _voicePath, chooseVoice);
        layout.Controls.Add(_shared, 1, 3);
        layout.SetColumnSpan(_shared, 2);
        layout.Controls.Add(_status, 1, 4);
        layout.SetColumnSpan(_status, 2);
        layout.Controls.Add(pair, 1, 5);
        Controls.Add(layout);
    }

    private static void AddRow(TableLayoutPanel layout, int row, string label, Control main, Control? extra)
    {
        layout.Controls.Add(new Label { Text = label, TextAlign = ContentAlignment.MiddleRight, AutoSize = true }, 0, row);
        layout.Controls.Add(main, 1, row);
        if (extra is not null)
        {
            layout.Controls.Add(extra, 2, row);
        }
    }

    private async Task PairAsync()
    {
        try
        {
            _status.Text = "Pairing...";
            var config = new AppConfig
            {
                ServerBaseUrl = _server.Text.Trim(),
                DeviceName = _deviceName.Text.Trim(),
                ShareAssistantProfileAcrossWindowsAccounts = _shared.Checked,
            };
            var pairing = new PairingClient();
            config = await pairing.PairAsync(config, CancellationToken.None);

            VoiceUploadResult? voice = null;
            var voicePath = _voicePath.Text.Trim();
            if (!string.IsNullOrWhiteSpace(voicePath))
            {
                voice = await pairing.UploadVoiceReferenceAsync(
                    config,
                    voicePath,
                    config.DeviceName,
                    CancellationToken.None);
                if (voice.Success)
                {
                    config.VoiceId = voice.VoiceId;
                }
            }

            _store.Save(config);
            Result = config;
            _status.Text = voice switch
            {
                null => "Paired. Upload a voice later from the tray menu.",
                { Success: true, Warnings.Count: > 0 } => $"Paired with voice {voice.VoiceId}. Warning: {voice.Warnings[0].Message}",
                { Success: true } => $"Paired with voice {voice.VoiceId}.",
                _ => $"Paired, but voice setup failed: {voice.ErrorMessage}",
            };
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (Exception ex)
        {
            _status.Text = "Setup failed: " + ex.Message;
        }
    }
}
