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

    // ---------------- 写入（只有「Outside Mercy」用到）----------------

    /// <summary>Reply的求助。</summary>
    public async Task<(bool Ok, string Error)> ReplyAsync(string ticket, string text, CancellationToken ct = default)
        => await PostActionAsync("/assist/reply", new { ticket, text }, ct).ConfigureAwait(false);

    /// <summary>Dismiss一条求助。</summary>
    public async Task<(bool Ok, string Error)> RejectAsync(string ticket, CancellationToken ct = default)
        => await PostActionAsync("/assist/reject", new { ticket }, ct).ConfigureAwait(false);

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
