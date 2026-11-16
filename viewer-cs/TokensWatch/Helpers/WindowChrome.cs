using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace TokensWatch.Helpers;

/// <summary>
/// 窗口外观：标题栏配色 + 隐藏系统按钮。
/// 主窗口已有内联实现，这里抽成公共件供附属窗口复用，避免每个窗口抄一遍 P/Invoke。
/// </summary>
public static class WindowChrome
{
    private const int DWMWA_CAPTION_COLOR = 35;
    private const int DWMWA_TEXT_COLOR = 36;

    private const int GWL_STYLE = -16;
    private const int WS_SYSMENU = 0x00080000;

    private const uint SWP_NOSIZE = 0x0001;
    private const uint SWP_NOMOVE = 0x0002;
    private const uint SWP_NOZORDER = 0x0004;
    private const uint SWP_FRAMECHANGED = 0x0020;

    [DllImport("dwmapi.dll", PreserveSig = true)]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int value, int size);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter,
        int X, int Y, int cx, int cy, uint uFlags);

    /// <summary>
    /// 在 Window 的 OnSourceInitialized 里调用。
    /// </summary>
    /// <param name="hideSystemButtons">是否去掉最小化/最大化/关闭（对齐 Python 的 _hide_close_button）</param>
    public static void Apply(Window window, bool hideSystemButtons = true, bool lightCaption = true)
    {
        IntPtr hwnd;
        try
        {
            hwnd = new WindowInteropHelper(window).Handle;
        }
        catch
        {
            return;
        }

        if (lightCaption)
        {
            try
            {
                int caption = 0x00F3F3F3;   // COLORREF 是 0x00BBGGRR
                DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ref caption, sizeof(int));
                int text = 0x001A1A1A;
                DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR, ref text, sizeof(int));
            }
            catch
            {
                // Win10 没有这两个属性
            }
        }

        if (!hideSystemButtons) return;

        try
        {
            int style = GetWindowLong(hwnd, GWL_STYLE);
            if ((style & WS_SYSMENU) != 0)
            {
                SetWindowLong(hwnd, GWL_STYLE, style & ~WS_SYSMENU);
                SetWindowPos(hwnd, IntPtr.Zero, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED);
            }
        }
        catch
        {
            // 失败就保留系统按钮
        }
    }
}
