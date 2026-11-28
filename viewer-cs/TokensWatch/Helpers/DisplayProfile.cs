using System.Globalization;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;

namespace TokensWatch.Helpers;

internal static class DisplayProfile
{
    internal readonly record struct WindowSize(int Width, int Height);

    private const int CompactWidth = 1280;
    private const int CompactHeight = 720;
    private const int DefaultDpi = 96;
    private const uint MonitorDefaultToNearest = 2;
    private const uint KeepZOrderAndActivation = 0x0004 | 0x0010;
    private const int WmSettingChange = 0x001A;
    private const int WmDisplayChange = 0x007E;
    private const int WmExitSizeMove = 0x0232;

    [StructLayout(LayoutKind.Sequential)]
    private struct NativeRect
    {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;

        public readonly int Width => Right - Left;
        public readonly int Height => Bottom - Top;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MonitorInfo
    {
        public uint Size;
        public NativeRect Monitor;
        public NativeRect Work;
        public uint Flags;
    }

    [DllImport("user32.dll")]
    private static extern IntPtr MonitorFromWindow(IntPtr window, uint flags);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetMonitorInfo(IntPtr monitor, ref MonitorInfo info);

    [DllImport("user32.dll")]
    private static extern uint GetDpiForWindow(IntPtr window);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetWindowRect(IntPtr window, out NativeRect bounds);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetWindowPos(IntPtr window, IntPtr after, int x, int y, int width, int height, uint flags);

    internal static WindowSize Select(int screenWidth, int screenHeight) =>
        screenWidth >= 2560 && screenHeight >= 1440 ? new(1920, 1080) :
        screenWidth >= 1920 && screenHeight >= 1080 ? new(1600, 900) :
        new(CompactWidth, CompactHeight);

    internal static WindowSize Fit(WindowSize requested, int workWidth, int workHeight)
    {
        double scale = Math.Min(1, Math.Min((double)workWidth / requested.Width, (double)workHeight / requested.Height));
        return new(Math.Max(1, (int)Math.Floor(requested.Width * scale)),
                   Math.Max(1, (int)Math.Floor(requested.Height * scale)));
    }

    internal static WindowSize? ParseOverride(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return null;
        var parts = value.Split('x', 'X', '×');
        if (parts.Length != 2 ||
            !int.TryParse(parts[0], NumberStyles.Integer, CultureInfo.InvariantCulture, out int width) ||
            !int.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out int height) ||
            width < CompactWidth || height < CompactHeight)
            return null;

        return new(width, height);
    }

    internal static void Configure(Window window, FrameworkElement layout, Action<WindowSize> applyLayout)
    {
        var requestedOverride = ParseOverride(Environment.GetEnvironmentVariable("TM_WATCH_SIZE"));
        string baseTitle = window.Title;
        IntPtr handle = IntPtr.Zero;
        DispatcherOperation? pending = null;

        void Apply(bool center)
        {
            if (handle == IntPtr.Zero || window.WindowState != WindowState.Normal) return;

            var monitor = MonitorFromWindow(handle, MonitorDefaultToNearest);
            var info = new MonitorInfo { Size = (uint)Marshal.SizeOf<MonitorInfo>() };
            if (!GetMonitorInfo(monitor, ref info) || info.Work.Width <= 0 || info.Work.Height <= 0 ||
                !GetWindowRect(handle, out var bounds)) return;

            var requested = requestedOverride ?? Select(info.Monitor.Width, info.Monitor.Height);
            var size = Fit(requested, info.Work.Width, info.Work.Height);
            uint dpi = GetDpiForWindow(handle);
            double fitScale = Math.Min(1, Math.Min((double)size.Width / CompactWidth, (double)size.Height / CompactHeight));
            double scale = fitScale * DefaultDpi / (dpi == 0 ? DefaultDpi : dpi);
            if (layout.LayoutTransform is not ScaleTransform current || current.ScaleX != scale)
                layout.LayoutTransform = new ScaleTransform(scale, scale);

            applyLayout(size);
            string suffix = requestedOverride is null ? "" : " (TM_WATCH_SIZE)";
            window.Title = $"{baseTitle} [{size.Width}x{size.Height}{suffix}]";

            int x = center ? info.Work.Left + (info.Work.Width - size.Width) / 2 :
                Math.Clamp(bounds.Left, info.Work.Left, info.Work.Right - size.Width);
            int y = center ? info.Work.Top + (info.Work.Height - size.Height) / 2 :
                Math.Clamp(bounds.Top, info.Work.Top, info.Work.Bottom - size.Height);
            if (x != bounds.Left || y != bounds.Top || size.Width != bounds.Width || size.Height != bounds.Height)
                SetWindowPos(handle, IntPtr.Zero, x, y, size.Width, size.Height, KeepZOrderAndActivation);
        }

        void QueueApply()
        {
            if (pending?.Status == DispatcherOperationStatus.Pending) return;
            pending = window.Dispatcher.BeginInvoke(DispatcherPriority.Loaded, new Action(() => Apply(center: false)));
        }

        window.SourceInitialized += (_, _) =>
        {
            handle = new WindowInteropHelper(window).Handle;
            HwndSource.FromHwnd(handle)?.AddHook(
                (IntPtr _, int message, IntPtr wParam, IntPtr lParam, ref bool handled) =>
                {
                    if (message is WmExitSizeMove or WmDisplayChange or WmSettingChange)
                        QueueApply();
                    return IntPtr.Zero;
                });
        };
        window.Loaded += (_, _) => Apply(center: true);
        window.DpiChanged += (_, _) => QueueApply();
        window.StateChanged += (_, _) => QueueApply();
        window.Closed += (_, _) =>
        {
            handle = IntPtr.Zero;
            pending?.Abort();
        };
    }
}
