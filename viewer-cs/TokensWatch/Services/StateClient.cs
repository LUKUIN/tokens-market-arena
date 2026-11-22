using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using TokensWatch.Models;

namespace TokensWatch.Services;

/// <summary>
/// 只读 HTTP 客户端，对接既有服务。
///
/// 与 src/tm_watch_ai.py 的两处关键对齐：
///  1. 第 23 行：地址取 TM_WATCH_API 环境变量，默认 http://127.0.0.1:8734
///  2. 第 28 行：显式绕过系统代理。Python 用 ProxyHandler({})，
///     .NET 的 HttpClientHandler.UseProxy 默认 true，必须手动关——
///     否则用户开着 Clash 时 127.0.0.1 会被塞进代理，一次握手失败就是一条“连接中断”。
/// 超时也对齐 3 秒（Python 的 timeout=3）。
/// </summary>
public sealed class StateClient : IDisposable
{
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
        NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.AllowReadingFromString,
    };

    private readonly HttpClient _http;

    public string BaseUrl { get; }

    public StateClient()
    {
        var raw = Environment.GetEnvironmentVariable("TM_WATCH_API");
        BaseUrl = string.IsNullOrWhiteSpace(raw)
            ? "http://127.0.0.1:8734"
            : raw.TrimEnd('/');

        var handler = new HttpClientHandler
        {
            UseProxy = false,                                  // ← 关键：绕开 Clash / HTTP_PROXY
            AutomaticDecompression = DecompressionMethods.All,
            AllowAutoRedirect = false,
        };

        _http = new HttpClient(handler)
        {
            Timeout = TimeSpan.FromSeconds(3),
        };
        _http.DefaultRequestHeaders.ConnectionClose = false;
    }

    // ---------------- 读取 ----------------

    public Task<WatchState?> GetStateAsync(CancellationToken ct = default)
        => GetJsonAsync<WatchState>("/state", ct);

    /// <summary>只要最新局面、不要价格历史时用这个，回包小很多。</summary>
    public Task<WatchState?> GetStateNoHistoryAsync(CancellationToken ct = default)
        => GetJsonAsync<WatchState>("/state?history=0", ct);

    public Task<AssistPending?> GetAssistPendingAsync(CancellationToken ct = default)
        => GetJsonAsync<AssistPending>("/assist/pending", ct);

    public Task<ScratchpadResponse?> GetScratchpadAsync(CancellationToken ct = default)
        => GetJsonAsync<ScratchpadResponse>("/scratchpad", ct);

    public Task<Dictionary<string, List<double>>?> GetPriceHistoryAsync(CancellationToken ct = default)
        => GetJsonAsync<Dictionary<string, List<double>>>("/prices", ct);

    public async Task<bool> HealthAsync(CancellationToken ct = default)
    {
        try
        {
            using var resp = await _http.GetAsync(BaseUrl + "/health", ct).ConfigureAwait(false);
            return resp.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    // ---------------- 写入（只有「外部的怜悯」用到）----------------

    /// <summary>回复参赛者的求助。</summary>
    public async Task<(bool Ok, string Error)> ReplyAsync(string ticket, string text, CancellationToken ct = default)
        => await PostActionAsync("/assist/reply", new { ticket, text }, ct).ConfigureAwait(false);

    /// <summary>驳回一条求助。</summary>
    public async Task<(bool Ok, string Error)> RejectAsync(string ticket, CancellationToken ct = default)
        => await PostActionAsync("/assist/reject", new { ticket }, ct).ConfigureAwait(false);

    // ---------------- 交易操作（仅人类版使用）----------------
    // 参数与 docs/ai-protocol.md 第 155-179 行的接口表一一对应。

    public Task<(bool Ok, string Error)> OpenAsync(string pair, string side, int lots, int leverage, CancellationToken ct = default)
        => PostActionAsync("/open", new { pair, side, lots, leverage }, ct);

    /// <summary>lots 超过实际持仓时，服务端按实际持仓全平，不报错。</summary>
    public Task<(bool Ok, string Error)> CloseAsync(string pair, string side, CancellationToken ct = default)
        => PostActionAsync("/close", new { pair, side }, ct);

    public Task<(bool Ok, string Error)> CloseAllAsync(CancellationToken ct = default)
        => PostActionAsync("/close_all", new { }, ct);

    public Task<(bool Ok, string Error)> LoanAsync(double amount, CancellationToken ct = default)
        => PostActionAsync("/loan", new { amount }, ct);

    public Task<(bool Ok, string Error)> RepayAsync(double amount, CancellationToken ct = default)
        => PostActionAsync("/repay", new { amount }, ct);

    /// <summary>seconds 只能是 300 或 180。</summary>
    public Task<(bool Ok, string Error)> FastForwardAsync(int seconds, CancellationToken ct = default)
        => PostActionAsync("/fastforward", new { seconds }, ct);

    /// <summary>接受本局挑战任务（难度定档后的询问阶段有效）。</summary>
    public Task<(bool Ok, string Error)> ChallengeAcceptAsync(CancellationToken ct = default)
        => PostActionAsync("/challenge/accept", new { }, ct);

    /// <summary>不开启挑战任务，按普通玩法进行。</summary>
    public Task<(bool Ok, string Error)> ChallengeDeclineAsync(CancellationToken ct = default)
        => PostActionAsync("/challenge/decline", new { }, ct);

    /// <summary>正式开始：解除暂停并把 45 分钟计时基准设到此刻（人类版开局流程最后一步）。</summary>
    public Task<(bool Ok, string Error)> BeginAsync(CancellationToken ct = default)
        => PostActionAsync("/begin", new { }, ct);

    /// <summary>开始难度盲盒（30 秒倒计时，期间行情不动）。</summary>
    public Task<(bool Ok, string Error)> RollStartAsync(CancellationToken ct = default)
        => PostActionAsync("/roll/start", new { }, ct);

    /// <summary>暂停对局（规则未确认前的初始态）。</summary>
    public Task<(bool Ok, string Error)> PauseAsync(CancellationToken ct = default)
        => PostActionAsync("/pause", new { }, ct);

    /// <summary>叫停难度盲盒：定档后返回本局的黑天鹅/流动性等级。</summary>
    public async Task<RollResult> RollStopAsync(CancellationToken ct = default)
    {
        var (ok, err) = await PostActionAsync("/roll/stop", new { }, ct).ConfigureAwait(false);
        if (!ok) return new RollResult { Ok = false, Error = err };

        // /roll/stop 的回包结构与 /state 的 gap_level / liq_level 不同，
        // 这里再取一次 /state 拿最终档位，避免依赖未文档化的字段。
        var st = await GetStateNoHistoryAsync(ct).ConfigureAwait(false);
        return new RollResult
        {
            Ok = true,
            Gap = st?.GapLevel ?? "",
            Liq = st?.LiqLevel ?? "",
            GapChance = 0,
            Liquidity = 0,
        };
    }

    /// <summary>GET /rules 原文（键是中文，交给规则窗口自己排版）。</summary>
    public async Task<JsonElement?> GetRulesAsync(CancellationToken ct = default)
    {
        using var resp = await _http.GetAsync(BaseUrl + "/rules", ct).ConfigureAwait(false);
        if (!resp.IsSuccessStatusCode) return null;
        await using var stream = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct).ConfigureAwait(false);
        return doc.RootElement.Clone();
    }

    /// <summary>老虎机：amount 限 1~200000 且不超过当前权益，整局 3 次。</summary>
    public async Task<SlotResult> SlotAsync(double amount, CancellationToken ct = default)
    {
        var body = JsonSerializer.Serialize(new { amount });
        using var content = new StringContent(body, Encoding.UTF8, "application/json");
        using var resp = await _http.PostAsync(BaseUrl + "/slot", content, ct).ConfigureAwait(false);

        if (!resp.IsSuccessStatusCode)
            return new SlotResult { Ok = false, Error = $"HTTP {(int)resp.StatusCode}" };

        await using var stream = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct).ConfigureAwait(false);
        var root = doc.RootElement;

        bool ok = root.TryGetProperty("ok", out var okEl) && okEl.ValueKind == JsonValueKind.True;
        string err = root.TryGetProperty("error", out var errEl) && errEl.ValueKind == JsonValueKind.String
            ? errEl.GetString() ?? "" : "";

        static int I32(JsonElement e, string n) =>
            e.TryGetProperty(n, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetInt32() : 0;
        static double D64(JsonElement e, string n) =>
            e.TryGetProperty(n, out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : 0.0;

        return new SlotResult
        {
            Ok = ok,
            Error = err,
            Mult = I32(root, "mult"),
            Payout = D64(root, "payout"),
            BumpPct = D64(root, "bump_pct"),
            Bump = D64(root, "bump"),
        };
    }

    public Task<(bool Ok, string Error)> ResetAsync(CancellationToken ct = default)
        => PostActionAsync("/reset", new { }, ct);

    public Task<(bool Ok, string Error)> QuitAsync(CancellationToken ct = default)
        => PostActionAsync("/quit", new { }, ct);

    /// <summary>
    /// 与 Python 侧「结束相关进程」按钮一致（tm_watch_ai.py 第 1414-1422 行）：
    /// 通知服务立即退出，随后由调用方关闭观众席。
    /// </summary>
    public async Task PostShutdownAsync(CancellationToken ct = default)
    {
        try
        {
            using var content = new StringContent("{}", Encoding.UTF8, "application/json");
            using var _ = await _http.PostAsync(BaseUrl + "/shutdown", content, ct).ConfigureAwait(false);
        }
        catch
        {
            // 服务已经不在是正常情况
        }
    }

    // ---------------- 内部实现 ----------------

    private async Task<T?> GetJsonAsync<T>(string path, CancellationToken ct) where T : class
    {
        using var resp = await _http.GetAsync(BaseUrl + path, ct).ConfigureAwait(false);
        resp.EnsureSuccessStatusCode();
        await using var stream = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        return await JsonSerializer.DeserializeAsync<T>(stream, JsonOpts, ct).ConfigureAwait(false);
    }

    private async Task<(bool, string)> PostActionAsync(string path, object payload, CancellationToken ct)
    {
        var body = JsonSerializer.Serialize(payload);
        using var content = new StringContent(body, Encoding.UTF8, "application/json");
        using var resp = await _http.PostAsync(BaseUrl + path, content, ct).ConfigureAwait(false);

        if (!resp.IsSuccessStatusCode)
            return (false, $"HTTP {(int)resp.StatusCode}");

        await using var stream = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct).ConfigureAwait(false);

        bool ok = doc.RootElement.TryGetProperty("ok", out var okEl)
                  && okEl.ValueKind == JsonValueKind.True;

        string err = doc.RootElement.TryGetProperty("error", out var errEl)
                     && errEl.ValueKind == JsonValueKind.String
            ? errEl.GetString() ?? ""
            : "";

        return (ok, err);
    }

    public void Dispose() => _http.Dispose();
}

/// <summary>老虎机单次结果。mult=0 表示空转。</summary>
public sealed class SlotResult
{
    public bool Ok { get; init; }
    public string Error { get; init; } = "";
    public int Mult { get; init; }
    public double Payout { get; init; }
    public double BumpPct { get; init; }
    public double Bump { get; init; }
}

/// <summary>难度定档结果。</summary>
public sealed class RollResult
{
    public bool Ok { get; init; }
    public string Error { get; init; } = "";
    public string Gap { get; init; } = "";
    public string Liq { get; init; } = "";
    public double GapChance { get; init; }
    public double Liquidity { get; init; }
}
