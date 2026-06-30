using System.Drawing.Imaging;
using PersonalAssistant.Windows.Session;

namespace PersonalAssistant.Windows.Screen;

public static class ScreenCapture
{
    public static byte[] CaptureActiveMonitorJpeg(long quality)
    {
        var handle = NativeWindow.ForegroundWindowHandle;
        var screen = handle == IntPtr.Zero ? System.Windows.Forms.Screen.PrimaryScreen : System.Windows.Forms.Screen.FromHandle(handle);
        if (screen is null)
        {
            throw new InvalidOperationException("No active screen is available.");
        }

        using var bitmap = new Bitmap(screen.Bounds.Width, screen.Bounds.Height);
        using (var graphics = Graphics.FromImage(bitmap))
        {
            graphics.CopyFromScreen(screen.Bounds.Left, screen.Bounds.Top, 0, 0, screen.Bounds.Size);
        }

        using var stream = new MemoryStream();
        var encoder = ImageCodecInfo.GetImageEncoders().First(codec => codec.MimeType == "image/jpeg");
        using var parameters = new EncoderParameters(1);
        parameters.Param[0] = new EncoderParameter(Encoder.Quality, Math.Clamp(quality, 25, 95));
        bitmap.Save(stream, encoder, parameters);
        return stream.ToArray();
    }
}
