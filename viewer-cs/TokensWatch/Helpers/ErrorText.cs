using System;
using System.Net.Http;
using System.Net.Sockets;
using System.Text.Json;

namespace TokensWatch.Helpers;

/// <summary>
/// Turn an exception into a deterministic English one-liner.
///
/// Exception.Message is localised by the operating system: on a Chinese Windows build a dead
/// service reports the failure in Chinese, which would put Chinese into an otherwise English
/// spectator. Map the exception type and socket error code instead of echoing the message.
/// </summary>
public static class ErrorText
{
    public static string Describe(Exception ex)
    {
        if (ex is SocketException se)
        {
            string detail = se.SocketErrorCode switch
            {
                SocketError.ConnectionRefused => "connection refused (is the service running?)",
                SocketError.TimedOut => "timed out",
                SocketError.HostNotFound => "host not found",
                SocketError.NetworkUnreachable => "network unreachable",
                SocketError.ConnectionReset => "connection reset",
                _ => se.SocketErrorCode.ToString()
            };
            return "socket error: " + detail;
        }

        if (ex is TaskCanceledException || ex is TimeoutException) return "request timed out";
        // HttpClient wraps the transport failure: keep the concrete reason visible.
        if (ex is HttpRequestException)
            return ex.InnerException is null ? "HTTP request failed" : Describe(ex.InnerException);
        if (ex is JsonException) return "invalid JSON payload";
        if (ex is InvalidOperationException) return "invalid state for this request";
        if (ex is System.IO.IOException) return "I/O error";

        return ex.GetType().Name;
    }
}
