using System.Windows.Media;

namespace TokensWatch.Helpers;

/// <summary>
/// /// One-to-one match with the colors and fonts at src/tm_watch_ai.py lines 127-152.
/// /// Change a value here and change Python too: the two spectators must look like the same product.
/// </summary>
public static class Theme
{
    //     // ---- Colors (same names and values as the Python constants) ----
    public const string BgHex = "#F3F3F3";
    public const string CardHex = "#FFFFFF";
    public const string BorderHex = "#E1E1E1";
    public const string TextHex = "#1A1A1A";
    public const string MutedHex = "#6B6B6B";
    public const string BlueHex = "#0078D4";
    public const string GreenHex = "#107C10";
    public const string RedHex = "#C42B1C";
    public const string OrangeHex = "#CA5010";

    //     // ---- Event-stream category colors (mirrors kind_color in _write_rows) ----
    public const string LogGapHex = "#C42B1C";      // Black swan
    public const string LogLiqHex = "#8E562E";      // Liquidity drained
    public const string LogNewsHex = "#CA5010";     // Events
    public const string LogTradeHex = "#0078D4";    // Open position
    public const string LogCloseHex = "#038387";    // Close position (distinct from open)
    public const string LogRiskHex = "#A4262C";     // Risk
    public const string LogLoanHex = "#8764B8";     // Borrow
    public const string LogEndHex = "#444444";      // match end
    public const string LogTraderHex = "#44546A";   // identity

    //     // ---- Fonts ----
    ///     /// <summary>Microsoft YaHei UI carries the CJK glyphs; Segoe UI Variable has none and cannot replace it.</summary>
    public const string UiFont = "Microsoft YaHei UI";
    public const string MonoFont = "Consolas";

    //     // ---- Quote instrument order and colors (PAIR_ORDER / PAIR_COLORS) ----
    public static readonly string[] PairOrder =
    {
        "AURA/CORE", "FROST/CORE", "AMBER/CORE", "TIDE/CORE",
        "LUMEN/CORE", "NEON/CORE", "ASH/CORE",
    };

    private static readonly Dictionary<string, string> PairColorMap = new(StringComparer.OrdinalIgnoreCase)
    {
        ["AURA/CORE"] = "#0078D4",
        ["FROST/CORE"] = "#107C10",
        ["AMBER/CORE"] = "#C42B1C",
        ["TIDE/CORE"] = "#8764B8",
        ["LUMEN/CORE"] = "#CA5010",
        ["NEON/CORE"] = "#0F7B6C",
        ["ASH/CORE"] = "#8E562E",
    };

    public static string PairColor(string pair) =>
        PairColorMap.TryGetValue(pair, out var hex) ? hex : MutedHex;

    //     // ---- Gap / Borrow lookup tables (_GAP_PCT / _LIQ_PCT) ----
    public static readonly Dictionary<string, string> GapPct = new()
    {
        ["very low"] = "0.24%", ["low"] = "0.60%", ["medium"] = "1.50%",
        ["high"] = "3.75%", ["very high"] = "9.38%",
    };

    public static readonly Dictionary<string, string> LiqPct = new()
    {
        ["abundant"] = "3.5%", ["normal"] = "7.0%", ["thin"] = "14.0%",
        ["drained"] = "28%", ["black hole"] = "56%",
    };

    public const string FrName = "Preferred Financing";
    public const string SlotName = "Slot machine";

    //     // ---- Activity tabs (LOG_TABS) ----
    public static readonly (string Key, string Label)[] LogTabs =
    {
        ("all", "All"),
        ("gap", "Black swan"),
        ("liq", "Liquidity drained"),
        ("news", "Events"),
        ("trade", "Trades"),
        ("risk", "Risk"),
    };

    //     // ---- Brush cache: a SolidColorBrush must be frozen to be reused safely across threads and animations ----
    private static readonly Dictionary<string, SolidColorBrush> BrushCache = new();

    public static SolidColorBrush Brush(string hex)
    {
        lock (BrushCache)
        {
            if (BrushCache.TryGetValue(hex, out var b)) return b;
            var color = (Color)ColorConverter.ConvertFromString(hex)!;
            var brush = new SolidColorBrush(color);
            brush.Freeze();
            BrushCache[hex] = brush;
            return brush;
        }
    }

    public static readonly SolidColorBrush Bg = Brush(BgHex);
    public static readonly SolidColorBrush Card = Brush(CardHex);
    public static readonly SolidColorBrush BorderBrush = Brush(BorderHex);
    public static readonly SolidColorBrush Text = Brush(TextHex);

    ///     /// <summary>Body-text color alias. XAML calls it Ink, C# accepts either name, so styling never splits.</summary>
    public static readonly SolidColorBrush Ink = Text;
    public static readonly SolidColorBrush Muted = Brush(MutedHex);
    public static readonly SolidColorBrush Blue = Brush(BlueHex);
    public static readonly SolidColorBrush Green = Brush(GreenHex);
    public static readonly SolidColorBrush Red = Brush(RedHex);
    public static readonly SolidColorBrush Orange = Brush(OrangeHex);
}
