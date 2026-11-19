using System;
using System.Windows;

namespace TokensWatch.Helpers;

/// <summary>
/// Picks a window size from the display's work area.
///
/// Observer feedback: a fixed 1920×1080 window nearly fills a 1080p screen.
/// Two tiers by screen:
///   2K and up (work-area DIP width >= 2400) -> 1920×1080
///   1080p (work-area DIP width >= 1700)     -> 1600×900
///   anything smaller                        -> 88% of the work area, never below 1280×720
///
/// Uses <see cref="SystemParameters.WorkArea"/> rather than the physical resolution: WPF window
/// sizes are DIP, so comparing against physical pixels trips over display scaling (a 2K panel at
/// 150% is 2560 physical but only 1707 DIP — judging by physical pixels would hand out a 1920 DIP
/// window that simply does not fit).
/// </summary>
public static class DisplayProfile
{
    public readonly record struct WindowSize(double Width, double Height, string Label, double RightColumn);

    public const double MinWidth = 1280;
    public const double MinHeight = 720;

    /// <summary>Right column (run state + activity feed): 400 on the 1920 tier, 360 on narrower ones to give the chart more room.</summary>
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
        // // Manual override: TM_WATCH_SIZE="1600x900". Convenient for validating the 1080p tier on a 2K panel,
        // // and it lets anyone pin a size regardless of what detection reports.
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

        // 2K / 4K: the work area fits 1920×1080
        if (w >= 2400 && h >= 1200)
            return new WindowSize(1920, 1080, "1920x1080", RightColumnWide);

        // 1080p: 1920×1080 would fill the screen, so use 1600×900
        if (w >= 1700 && h >= 880)
            return new WindowSize(1600, 900, "1600x900", RightColumnNarrow);

        // Smaller screens: scale down from the work area, keeping 16:9
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
