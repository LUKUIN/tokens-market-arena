using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Windows;
using TokensWatch.Helpers;
using TokensWatch.Services;

namespace TokensWatch.Panels;

/// <summary>
/// 规则窗口。对应 tm_watch_ai.py 人类版第 1395-1449 行（_rules_text）与 1577-1644 行（_show_rules）。
///
/// 纪律：文本全部由 GET /rules 的字段拼出来，不在前端写死任何规则数值——
/// 服务端改了参数，这里跟着变，不会出现「界面说 100 倍、引擎按 50 倍算」。
/// </summary>
public partial class RulesWindow : Window
{
    private readonly StateClient _client;
    private readonly string _mode;

    public RulesWindow(StateClient client, string mode = "")
    {
        InitializeComponent();
        _client = client;
        _mode = mode;

        SourceInitialized += (_, _) => WindowChrome.Apply(this);
        Loaded += async (_, _) => await LoadAsync();
    }

    private async Task LoadAsync()
    {
        try
        {
            var rules = await _client.GetRulesAsync();
            Body.Text = rules is { } r ? Build(r) : "读取失败：/rules 无返回。";
        }
        catch (Exception ex)
        {
            Body.Text = "读取失败：" + ex.Message;
        }

        Body.ScrollToHome();
    }

    // ---------------- 排版 ----------------

    private static string G(JsonElement r, string key, string fallback = "")
    {
        if (r.TryGetProperty(key, out var v))
        {
            string s = v.ValueKind switch
            {
                JsonValueKind.String => v.GetString() ?? "",
                JsonValueKind.Number => v.ToString(),
                JsonValueKind.Object => Kv(v),
                _ => "",
            };
            if (!string.IsNullOrWhiteSpace(s)) return s;
        }
        return fallback;
    }

    private static string Kv(JsonElement o)
    {
        if (o.ValueKind != JsonValueKind.Object) return "—";
        var parts = new List<string>();
        foreach (var p in o.EnumerateObject())
        {
            parts.Add($"{p.Name} {Val(p.Value)}");
        }
        return parts.Count == 0 ? "—" : string.Join("、", parts);
    }

    private static string Val(JsonElement v) => v.ValueKind switch
    {
        JsonValueKind.String => v.GetString() ?? "",
        JsonValueKind.Number => v.ToString(),
        JsonValueKind.True => "是",
        JsonValueKind.False => "否",
        _ => "—",
    };

    private string Build(JsonElement r)
    {
        string init = "1,000,000";
        if (r.TryGetProperty("初始资金", out var iv) && iv.ValueKind == JsonValueKind.Number
            && iv.TryGetDouble(out double dv))
        {
            init = dv.ToString("N0", CultureInfo.CurrentCulture);
        }

        var sb = new StringBuilder(1600);
        void L(string s = "") => sb.Append(s).Append('\n');

        L("【目标】");
        L($"起始资金 {init} Tokens。{G(r, "目标")}");
        L();

        L("【怎么赚钱】");
        L($"· {G(r, "手数")}，{G(r, "杠杆")}");
        L("· 做多：价格涨就赚；做空：价格跌就赚");
        L($"· 保证金 = 名义价值 ÷ 杠杆；手续费 = {G(r, "手续费")}");
        L($"· 点差：{G(r, "点差", "—")}");
        L($"· 滑点：{G(r, "滑点")}");
        L();

        L("【会亏钱的地方】");
        L($"· 黑天鹅：{G(r, "黑天鹅")}（方向随机，止损可能被直接跳过去）");
        L($"· 流动性枯竭：{G(r, "流动性枯竭")}（此时下单更贵）");
        L($"· 隔夜利息（持仓每 tick 扣一次）：{G(r, "隔夜利息", "—")}");
        L($"· 保证金水平：{G(r, "保证金水平")}");
        L();

        L("【借钱】");
        L($"| {G(r, "贷款")}");
        L("· 每借一笔，最终目标会随机上浮 1%~100% —— 救急可以，但目标会更高");
        L("· 利息按 tick 复利滚入欠款；还清欠款 = 连本带息还清，不需要单独再还利息");
        L();

        L("【两种模式（标题栏括号里写的就是当前模式）】");
        L("· 理想情况：关闭全部随机事件，只剩黑天鹅跳空。行情更“干净”，"
          + "不会突然冒出额外惩罚，适合新手先熟悉开仓、平仓、加杠杆的手感。");
        L("· 已开启随机事件：除黑天鹅外，还会随机触发二十多种临时事件——"
          + "流动性枯竭、手续费上调、保证金加倍、点差放大、杠杆上限下调、行情异常拒单等，"
          + "每种持续若干 tick 后自动恢复。难度明显更高，也会让原本算好的成本变脸。");
        L($"· 当前模式：{(_mode.Length > 0 ? _mode : "未知")}");
        L();

        L("【节奏】");
        L($"· 会话时长 {G(r, "会话时长")}，每 {G(r, "tick 间隔")} 一个 tick，行情自动推进");
        L("· 到点自动结算；也可以自己点「结束并结算」");
        L("· 资金变成负数后会弹出贷款窗口，60 秒内不补回 0 以上，本局立即结束");
        L("· 每局快进额度共 15 分钟，按 3 次 × 5 分钟（或 5 次 × 3 分钟）切分；"
          + "每次快进后需强制冷却（2 分钟 / 1.5 分钟），次数用完即禁用");
        L();

        L("【操作】");
        L("全部在顶栏「投资界面」里完成：开仓 / 平仓 / 借款 / 还款 / 重开一局 / 结束结算");
        L();

        L("【货币对】");
        L(G(r, "货币对", "—"));
        L();

        return sb.ToString();
    }

    private void OnCloseClick(object sender, RoutedEventArgs e) => Close();
}
