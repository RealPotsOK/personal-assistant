using NAudio.Wave;
using PersonalAssistant.Windows.Config;

namespace PersonalAssistant.Windows.UI;

public sealed class SettingsForm : Form
{
    private readonly AppConfig _config;
    private readonly ComboBox _thinking = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 140 };
    private readonly NumericUpDown _jpeg = new() { Minimum = 25, Maximum = 95, Width = 80 };
    private readonly ComboBox _input = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 260 };
    private readonly TextBox _server = new() { Width = 300 };

    public SettingsForm(AppConfig config)
    {
        _config = config;
        Text = "Personal Assistant Settings";
        Width = 460;
        Height = 260;
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

        var save = new Button { Text = "Save", Width = 80 };
        save.Click += (_, _) =>
        {
            _config.ServerBaseUrl = _server.Text.Trim();
            _config.Thinking = _thinking.SelectedItem?.ToString() ?? "medium";
            _config.JpegQuality = (int)_jpeg.Value;
            _config.InputDeviceNumber = Math.Max(0, _input.SelectedIndex);
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
        layout.Controls.Add(save, 1, 4);
        Controls.Add(layout);
    }

    private static void Add(TableLayoutPanel layout, int row, string label, Control control)
    {
        layout.Controls.Add(new Label { Text = label, TextAlign = ContentAlignment.MiddleRight, AutoSize = true }, 0, row);
        layout.Controls.Add(control, 1, row);
    }
}
