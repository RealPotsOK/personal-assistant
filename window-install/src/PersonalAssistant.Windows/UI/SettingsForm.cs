using NAudio.Wave;
using PersonalAssistant.Windows.Config;

namespace PersonalAssistant.Windows.UI;

public sealed class SettingsForm : Form
{
    private readonly AppConfig _config;
    private readonly ComboBox _thinking = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 140 };
    private readonly NumericUpDown _jpeg = new() { Minimum = 25, Maximum = 95, Width = 80 };
    private readonly ComboBox _input = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 260 };
    private readonly ComboBox _output = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 260 };
    private readonly ComboBox _mirror = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 260 };
    private readonly TextBox _server = new() { Width = 300 };

    public SettingsForm(AppConfig config)
    {
        _config = config;
        Text = "Personal Assistant Settings";
        Width = 460;
        Height = 340;
        _server.Text = config.ServerBaseUrl;
        _thinking.Items.AddRange(new object[] { "instant", "medium", "long" });
        _thinking.SelectedItem = config.Thinking;
        _jpeg.Value = config.JpegQuality;
        for (var index = 0; index < WaveIn.DeviceCount; index++)
        {
            _input.Items.Add($"{index}: {WaveIn.GetCapabilities(index).ProductName}");
        }
        if (_input.Items.Count > 0)
        {
            _input.SelectedIndex = Math.Clamp(config.InputDeviceNumber, 0, _input.Items.Count - 1);
        }
        _output.Items.Add("Windows default output");
        _mirror.Items.Add("No mirror output");
        for (var index = 0; index < WaveOut.DeviceCount; index++)
        {
            var name = $"{index}: {WaveOut.GetCapabilities(index).ProductName}";
            _output.Items.Add(name);
            _mirror.Items.Add(name);
        }
        _output.SelectedIndex = config.OutputDeviceNumber < 0
            ? 0
            : Math.Clamp(config.OutputDeviceNumber + 1, 0, _output.Items.Count - 1);
        _mirror.SelectedIndex = config.MirrorOutputDeviceNumber is int mirror
            ? Math.Clamp(mirror + 1, 0, _mirror.Items.Count - 1)
            : 0;

        var save = new Button { Text = "Save", Width = 80 };
        save.Click += (_, _) =>
        {
            _config.ServerBaseUrl = _server.Text.Trim();
            _config.Thinking = _thinking.SelectedItem?.ToString() ?? "medium";
            _config.JpegQuality = (int)_jpeg.Value;
            _config.InputDeviceNumber = Math.Max(0, _input.SelectedIndex);
            _config.OutputDeviceNumber = _output.SelectedIndex <= 0 ? -1 : _output.SelectedIndex - 1;
            _config.MirrorOutputDeviceNumber = _mirror.SelectedIndex <= 0 ? null : _mirror.SelectedIndex - 1;
            DialogResult = DialogResult.OK;
            Close();
        };

        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(14), ColumnCount = 2 };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        Add(layout, 0, "Server URL", _server);
        Add(layout, 1, "Thinking", _thinking);
        Add(layout, 2, "JPEG quality", _jpeg);
        Add(layout, 3, "Microphone", _input);
        Add(layout, 4, "Output", _output);
        Add(layout, 5, "Mirror output", _mirror);
        layout.Controls.Add(save, 1, 6);
        Controls.Add(layout);
    }

    private static void Add(TableLayoutPanel layout, int row, string label, Control control)
    {
        layout.Controls.Add(new Label { Text = label, TextAlign = ContentAlignment.MiddleRight, AutoSize = true }, 0, row);
        layout.Controls.Add(control, 1, row);
    }
}
