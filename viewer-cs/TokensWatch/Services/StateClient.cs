using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using TokensWatch.Models;

namespace TokensWatch.Services;

/// <summary>
/// /// Read-only HTTP client that talks to the existing service.
///
/// /// Two key alignments with src/tm_watch_ai.py:
/// ///  1. Line 23: the address comes from the TM_WATCH_API environment variable, default http://127.0.0.1:8734
/// ///  2. Line 28: bypass the system proxy explicitly. Python uses ProxyHandler({}),
/// ///     while .NET HttpClientHandler.UseProxy defaults to true and must be turned off,
/// ///     or a user running Clash pushes 127.0.0.1 through the proxy and one failed handshake reads as "connection lost".
/// /// The timeout matches too: 3 seconds (Python timeout=3).
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
            UseProxy = false,                                  // key: bypass Clash / HTTP_PROXY
            AutomaticDecompression = DecompressionMethods.All,
            AllowAutoRedirect = false,
        };

        _http = new HttpClient(handler)
        {
            Timeout = TimeSpan.FromSeconds(3),
        };
        _http.DefaultRequestHeaders.ConnectionClose = false;
    }

    //     // ---------------- Read ----------------

    public Task<WatchState?> GetStateAsync(CancellationToken ct = default)
        => GetJsonAsync<WatchState>("/state", ct);

    ///     /// <summary>Use this when only the latest state is needed and price history is not; the payload is much smaller.</summary>
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

    //     // ---------------- Write (only "Outside Mercy" uses this) ----------------

    ///     /// <summary>Reply to an ask.</summary>
    public async Task<(bool Ok, string Error)> ReplyAsync(string ticket, string text, CancellationToken ct = default)
        => await PostActionAsync("/assist/reply", new { ticket, text }, ct).ConfigureAwait(false);

    ///     /// <summary>Dismiss an ask.</summary>
    public async Task<(bool Ok, string Error)> RejectAsync(string ticket, CancellationToken ct = default)
        => await PostActionAsync("/assist/reject", new { ticket }, ct).ConfigureAwait(false);

    /// <summary>
    ///     /// Mirrors the Python "End related processes" button (tm_watch_ai.py lines 1414-1422):
    ///     /// tell the service to exit now; the caller then closes the spectator.
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
            //             // The service being gone is the normal case
        }
    }

    //     // ---------------- Internals ----------------

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
