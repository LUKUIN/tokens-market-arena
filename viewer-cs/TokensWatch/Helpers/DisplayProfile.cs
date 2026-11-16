using System;
using System.Windows;

namespace TokensWatch.Helpers;

/// <summary>
/// 按显示器可用区域挑窗口尺寸。
///
/// 观察员反馈：固定 1920×1080 在 1080p 屏上几乎占满整块屏，看着太大。
/// 这里按屏幕分两档：
///   2K 及以上（工作区 DIP 宽 ≥ 2400）→ 1920×1080
///   1080p（工作区 DIP 宽 ≥ 1700）    → 1600×900
///   更小的屏                        → 收到工作区的 88%，不低于 1280×720
///
/// 用 <see cref="SystemParameters.WorkArea"/> 而不是物理分辨率：WPF 的窗口尺寸是 DIP，
/// 拿物理像素比会踩到系统缩放（2K@150% 的物理宽 2560，DIP 只有 1707 —— 按物理像素判会
/// 给一个 1920 DIP 的窗口，直接超出屏幕）。
/// </summary>
public static class DisplayProfile
{
    public readonly record struct WindowSize(double Width, double Height, string Label, double RightColumn);

    public const double MinWidth = 1280;
    public const double MinHeight = 720;

    /// <summary>右栏（运行状态 + 活动流）宽度：1920 档用 400，收窄的档位用 360 换回左区画布。</summary>
    private const double RightColumnWide = 400;
    private const double RightColumnNarrow = 360;

    private static WindowSize? ParseForced(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return null;
        var parts = raw.Trim().ToLowerInvariant().Split('x', '×');
        if (parts.Length != 2) return null;
        if (!double.TryParse(parts[0].Trim(), out double w)) return null;
        if (!double.TryParse(parts[1].Trim(), out double h)) return null;
        if (w < MinWidth || h < MinHeight) return null;
        double right = w >= 1800 ? RightColumnWide : RightColumnNarrow;
        return new WindowSize(w, h, string.Format("{0:0}x{1:0} (TM_WATCH_SIZE)", w, h), right);
    }

    public static WindowSize Pick()
    {
        // 手动覆盖：TM_WATCH_SIZE="1600x900"。既方便在 2K 屏上验收 1080p 档，
        // 也让人可以固定自己想要的尺寸而不受检测结果影响。
        var forced = ParseForced(Environment.GetEnvironmentVariable("TM_WATCH_SIZE"));
        if (forced is { } f)
            return f;

        Rect wa;
        try
        {
            wa = SystemParameters.WorkArea;
        }
        catch
        {
            return new WindowSize(1600, 900, "1600x900 (fallback)", RightColumnNarrow);
        }

        double w = wa.Width > 0 ? wa.Width : 1920;
        double h = wa.Height > 0 ? wa.Height : 1080;

        // 2K / 4K：工作区足够放下 1920×1080
        if (w >= 2400 && h >= 1200)
            return new WindowSize(1920, 1080, "1920x1080", RightColumnWide);

        // 1080p：1920×1080 会顶满整屏，换成 1600×900
        if (w >= 1700 && h >= 880)
            return new WindowSize(1600, 900, "1600x900", RightColumnNarrow);

        // 更小的屏：按可用区等比收，保持 16:9
        double sw = Math.Min(1600.0, w * 0.88);
        double sh = sw * 9.0 / 16.0;
        if (sh > h * 0.88)
        {
            sh = h * 0.88;
            sw = sh * 16.0 / 9.0;
        }
        sw = Math.Max(MinWidth, Math.Round(sw));
        sh = Math.Max(MinHeight, Math.Round(sh));
        return new WindowSize(sw, sh, string.Format("{0:0}x{1:0} auto", sw, sh), RightColumnNarrow);
    }
}
