using System.Windows.Media;

namespace TokensWatch.Helpers;

/// <summary>
/// 与 src/tm_watch_ai.py 第 127-152 行的配色/字体保持一一对应。
/// 数值改动时请同步 Python 侧，两个观众席必须看着是同一个产品。
/// </summary>
public static class Theme
{
    // ---- 颜色（与 Python 常量同名同值）----
    public const string BgHex = "#F3F3F3";
    public const string CardHex = "#FFFFFF";
    public const string BorderHex = "#E1E1E1";
    public const string TextHex = "#1A1A1A";
    public const string MutedHex = "#6B6B6B";
    public const string BlueHex = "#0078D4";
    public const string GreenHex = "#107C10";
    public const string RedHex = "#C42B1C";
    public const string OrangeHex = "#CA5010";

    // ---- 事件流分类颜色（对应 _write_rows 的 kind_color）----
    public const string LogGapHex = "#C42B1C";      // 黑天鹅
    public const string LogLiqHex = "#8E562E";      // 流动性枯竭
    public const string LogNewsHex = "#CA5010";     // 随机事件
    public const string LogTradeHex = "#0078D4";    // 开仓/平仓
    public const string LogRiskHex = "#A4262C";     // 风险
    public const string LogLoanHex = "#8764B8";     // 借款
    public const string LogEndHex = "#444444";      // 对局结束
    public const string LogTraderHex = "#44546A";   // 身份

    // ---- 字体 ----
    /// <summary>中文界面用雅黑；Segoe UI Variable 不含中文字形，不能替代。</summary>
    public const string UiFont = "Microsoft YaHei UI";
    public const string MonoFont = "Consolas";

    // ---- 报价台品种顺序与配色（PAIR_ORDER / PAIR_COLORS）----
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

    // ---- 涨跌/借款映射表（_GAP_PCT / _LIQ_PCT）----
    public static readonly Dictionary<string, string> GapPct = new()
    {
        ["极低"] = "0.24%", ["低"] = "0.60%", ["中"] = "1.50%",
        ["高"] = "3.75%", ["极高"] = "9.38%",
    };

    public static readonly Dictionary<string, string> LiqPct = new()
    {
        ["充裕"] = "3.5%", ["正常"] = "7.0%", ["纤薄"] = "14.0%",
        ["枯竭"] = "28%", ["黑洞"] = "56%",
    };

    public const string FrName = "优惠融资";
    public const string SlotName = "老虎机";

    // ---- 活动流标签页（LOG_TABS）----
    public static readonly (string Key, string Label)[] LogTabs =
    {
        ("all", "全部"),
        ("gap", "黑天鹅"),
        ("liq", "流动性枯竭"),
        ("news", "随机事件"),
        ("trade", "开仓/平仓"),
        ("risk", "风险"),
    };

    // ---- Brush 缓存：SolidColorBrush 必须 Freeze 才能在多线程/动画里安全复用 ----
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

    /// <summary>正文色别名。XAML 里叫 Ink，C# 里两个名字都能用，避免风格分裂。</summary>
    public static readonly SolidColorBrush Ink = Text;
    public static readonly SolidColorBrush Muted = Brush(MutedHex);
    public static readonly SolidColorBrush Blue = Brush(BlueHex);
    public static readonly SolidColorBrush Green = Brush(GreenHex);
    public static readonly SolidColorBrush Red = Brush(RedHex);
    public static readonly SolidColorBrush Orange = Brush(OrangeHex);
}
