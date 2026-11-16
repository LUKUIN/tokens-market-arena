using TokensWatch.Helpers;
using TokensWatch.Models;

namespace TokensWatch.Helpers;

/// <summary>
/// 事件归类与配色。对应 tm_watch_ai.py 第 1068-1080 行（_log_cat）与第 1206-1228 行（kind_color）。
/// 主窗口与「Activity (all)」必须用同一套Rules，否则两处会显示不同的分类结果。
/// </summary>
public static class EventKind
{
    private static readonly string[] LiqMarks = { "[Liquidity drained]", "【Liquidity drained】", "[Liquidity drained]" };

    /// <summary>归入 all / gap / liq / news / trade / risk / other。</summary>
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
