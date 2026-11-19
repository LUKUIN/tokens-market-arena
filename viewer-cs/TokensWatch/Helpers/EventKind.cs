using TokensWatch.Helpers;
using TokensWatch.Models;

namespace TokensWatch.Helpers;

/// <summary>
/// /// Event classification and colors. Mirrors tm_watch_ai.py lines 1068-1080 (_log_cat) and 1206-1228 (kind_color).
/// /// The main window and the "Activity (all)" popup must share one set of rules, or the two disagree on categories.
/// </summary>
public static class EventKind
{
    private static readonly string[] LiqMarks = { "[Liquidity drained]", "\u3010Liquidity drained\u3011", "[Liquidity drained]" };

    /// /// <summary>Assign to all / gap / liq / news / trade / risk / other.</summary>
    public static string Category(GameEvent e)
    {
        string k = e.Kind ?? "info";
        string t = e.Text ?? "";

        if (k == "gap")
            return LiqMarks.Any(m => t.Contains(m)) ? "liq" : "gap";
        if (k == "news") return "news";
        if (k is "open" or "close") return "trade";
        if (k is "stopout" or "blowup" or "margin_call" or "warn") return "risk";
        return "other";
    }

    public static string ColorHex(GameEvent e)
    {
        string k = e.Kind ?? "info";
        string t = e.Text ?? "";

        if (k == "gap")
        {
            bool isLiq = LiqMarks.Any(m => t.Contains(m));
            return isLiq ? Theme.LogLiqHex : Theme.LogGapHex;
        }

        return k switch
        {
            "news" => Theme.LogNewsHex,
            "open" => Theme.LogTradeHex,
            "close" => Theme.LogCloseHex,
            "stopout" or "blowup" or "margin_call" or "warn" => Theme.LogRiskHex,
            "loan" => Theme.LogLoanHex,
            "end" => Theme.LogEndHex,
            "trader" => Theme.LogTraderHex,
            _ => Theme.MutedHex,
        };
    }
}
