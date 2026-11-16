using System.Text.Json;
using System.Text.Json.Serialization;

namespace TokensWatch.Models;

/// <summary>
/// GET /state 的强类型视图。
/// 字段来源：docs/ai-protocol.md 第 185-231 行 + src/tm_watch_ai.py 的 st.get(...) 调用点。
/// 未知字段一律忽略（服务端会随版本加字段，前端不能因此崩溃）。
/// </summary>
public sealed class WatchState
{
    [JsonPropertyName("tick")] public int Tick { get; set; }

    [JsonPropertyName("equity")] public double Equity { get; set; }
    [JsonPropertyName("balance")] public double Balance { get; set; }
    [JsonPropertyName("pnl")] public double Pnl { get; set; }
    [JsonPropertyName("pnl_pct")] public double PnlPct { get; set; }

    [JsonPropertyName("positions")] public List<Position> Positions { get; set; } = new();

    /// <summary>净值 ÷ (名义敞口 × 10%)。空仓时为 null。</summary>
    [JsonPropertyName("margin_level")] public double? MarginLevel { get; set; }

    [JsonPropertyName("prices")] public Dictionary<string, Quote> Prices { get; set; } = new();

    [JsonPropertyName("loan")] public LoanInfo? Loan { get; set; }
    [JsonPropertyName("total_borrowed")] public double TotalBorrowed { get; set; }

    /// <summary>生效中的临时Rules。服务端可能是对象数组，也可能是字符串数组，用 JsonElement 兜住。</summary>
    [JsonPropertyName("active_mods")] public JsonElement? ActiveMods { get; set; }

    [JsonPropertyName("special")] public SpecialFlags? Special { get; set; }

    [JsonPropertyName("gap_level")] public string? GapLevel { get; set; }
    [JsonPropertyName("liq_level")] public string? LiqLevel { get; set; }

    [JsonPropertyName("ff")] public FastForward? Ff { get; set; }

    [JsonPropertyName("target")] public double Target { get; set; }
    [JsonPropertyName("target_pct")] public double TargetPct { get; set; }
    [JsonPropertyName("target_bonus")] public double TargetBonus { get; set; }
    [JsonPropertyName("loan_bump_range")] public List<double>? LoanBumpRange { get; set; }
    [JsonPropertyName("loan_bump_remain")] public double? LoanBumpRemain { get; set; }
    [JsonPropertyName("loan_pool_event")] public string? LoanPoolEvent { get; set; }

    [JsonPropertyName("trader")] public string? Trader { get; set; }
    [JsonPropertyName("events_on")] public bool EventsOn { get; set; } = true;

    [JsonPropertyName("session_minutes")] public double SessionMinutes { get; set; } = 45;
    [JsonPropertyName("elapsed_seconds")] public double ElapsedSeconds { get; set; }
    [JsonPropertyName("order_count")] public int OrderCount { get; set; }

    [JsonPropertyName("max_drawdown")] public double? MaxDrawdown { get; set; }
    [JsonPropertyName("sharpe")] public double? Sharpe { get; set; }
    [JsonPropertyName("closed_n")] public int ClosedN { get; set; }
    [JsonPropertyName("win_n")] public int WinN { get; set; }
    [JsonPropertyName("fees")] public double Fees { get; set; }
    [JsonPropertyName("swap")] public double Swap { get; set; }
    [JsonPropertyName("blowups")] public int Blowups { get; set; }
    [JsonPropertyName("abnormal_exits")] public int AbnormalExits { get; set; }

    [JsonPropertyName("audit")] public List<JsonElement> Audit { get; set; } = new();
    [JsonPropertyName("events")] public List<GameEvent> Events { get; set; } = new();
    [JsonPropertyName("equity_curve")] public List<EquityPoint> EquityCurve { get; set; } = new();
    [JsonPropertyName("price_history")] public Dictionary<string, List<double>>? PriceHistory { get; set; }

    [JsonPropertyName("rolled")] public bool Rolled { get; set; }
    [JsonPropertyName("roll_left")] public double? RollLeft { get; set; }

    [JsonPropertyName("finished")] public bool Finished { get; set; }
    [JsonPropertyName("settlement")] public JsonElement? Settlement { get; set; }
    [JsonPropertyName("seed")] public JsonElement? Seed { get; set; }

    // ---- 异常/紧急状态：不是 null 就代表正在倒计时 ----
    [JsonPropertyName("negative_remain")] public double? NegativeRemain { get; set; }
    [JsonPropertyName("margin_call_remain")] public double? MarginCallRemain { get; set; }
    [JsonPropertyName("tampered")] public bool Tampered { get; set; }
    [JsonPropertyName("clock_cheat")] public bool ClockCheat { get; set; }
    [JsonPropertyName("unnamed")] public bool Unnamed { get; set; }

    /// <summary>active_mods 归一化成可显示的短文本（兼容对象数组与字符串数组两种形态）。</summary>
    public string ActiveModsText()
    {
        if (ActiveMods is not { } el) return string.Empty;

        try
        {
            if (el.ValueKind == JsonValueKind.Array)
            {
                var parts = new List<string>();
                foreach (var item in el.EnumerateArray())
                {
                    if (item.ValueKind == JsonValueKind.String)
                    {
                        parts.Add(item.GetString() ?? string.Empty);
                    }
                    else if (item.ValueKind == JsonValueKind.Object)
                    {
                        // 优先用 label，其次 name
                        if (item.TryGetProperty("label", out var lb) && lb.ValueKind == JsonValueKind.String)
                            parts.Add(lb.GetString()!);
                        else if (item.TryGetProperty("name", out var nm) && nm.ValueKind == JsonValueKind.String)
                            parts.Add(nm.GetString()!);
                    }
                }
                return string.Join("  ", parts.Where(p => p.Length > 0));
            }

            if (el.ValueKind == JsonValueKind.String)
                return el.GetString() ?? string.Empty;
        }
        catch (JsonException)
        {
            // 结构异常时安静降级，不要因为一个装饰性字段把整屏数据丢掉
        }

        return string.Empty;
    }
}

public sealed class Position
{
    [JsonPropertyName("pair")] public string Pair { get; set; } = "";
    [JsonPropertyName("side")] public string Side { get; set; } = "";
    [JsonPropertyName("lots")] public double Lots { get; set; }
    [JsonPropertyName("leverage")] public double Leverage { get; set; }
    [JsonPropertyName("entry")] public double Entry { get; set; }
    [JsonPropertyName("price")] public double Price { get; set; }
    [JsonPropertyName("upnl")] public double Upnl { get; set; }
    [JsonPropertyName("margin")] public double Margin { get; set; }
}

public sealed class Quote
{
    [JsonPropertyName("price")] public double Price { get; set; }
    [JsonPropertyName("spread_pct")] public double SpreadPct { get; set; }
}

public sealed class LoanInfo
{
    [JsonPropertyName("balance")] public double Balance { get; set; }
    [JsonPropertyName("limit")] public double Limit { get; set; }
    [JsonPropertyName("borrowed")] public double Borrowed { get; set; }
    [JsonPropertyName("interest")] public double Interest { get; set; }
    [JsonPropertyName("rate_pct")] public double RatePct { get; set; }
}

public sealed class SpecialFlags
{
    [JsonPropertyName("fr")] public bool Fr { get; set; }
    [JsonPropertyName("fr_left")] public JsonElement? FrLeft { get; set; }
    [JsonPropertyName("slot")] public bool Slot { get; set; }
    // 引擎在「老虎机未开启」时把 slot_left 输出成 null（tm_engine.py:1817 的
    // `... if slot else None`）。这里必须是可空类型，否则整个 /state 反序列化失败，
    // 界面会整块变空并弹「连接失败」。
    [JsonPropertyName("slot_left")] public JsonElement? SlotLeft { get; set; }
    [JsonPropertyName("slot_win")] public double SlotWin { get; set; }
    [JsonPropertyName("fr_lo_pct")] public double FrLoPct { get; set; }
}

public sealed class FastForward
{
    [JsonPropertyName("total")] public double Total { get; set; }
    [JsonPropertyName("used")] public double Used { get; set; }
    [JsonPropertyName("remain")] public double Remain { get; set; }
    [JsonPropertyName("records")] public List<double> Records { get; set; } = new();
    [JsonPropertyName("cool_left")] public double CoolLeft { get; set; }
    [JsonPropertyName("can5")] public bool Can5 { get; set; }
    [JsonPropertyName("can3")] public bool Can3 { get; set; }
    [JsonPropertyName("left5")] public int Left5 { get; set; }
    [JsonPropertyName("left3")] public int Left3 { get; set; }
}

public sealed class GameEvent
{
    [JsonPropertyName("tick")] public int Tick { get; set; }
    [JsonPropertyName("kind")] public string Kind { get; set; } = "info";
    [JsonPropertyName("text")] public string Text { get; set; } = "";
    [JsonPropertyName("time")] public double Time { get; set; }
}

public sealed class EquityPoint
{
    [JsonPropertyName("equity")] public double Equity { get; set; }
    [JsonPropertyName("tick")] public int Tick { get; set; }
}
