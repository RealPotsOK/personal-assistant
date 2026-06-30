using System.Text;
using System.Runtime.InteropServices;

namespace PersonalAssistant.Windows.Session;

internal static class NativeWindow
{
    public static string GetForegroundWindowTitle()
    {
        var handle = GetForegroundWindow();
        if (handle == IntPtr.Zero)
        {
            return "";
        }

        var builder = new StringBuilder(512);
        _ = GetWindowText(handle, builder, builder.Capacity);
        return builder.ToString();
    }

    public static IntPtr ForegroundWindowHandle => GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
}
