using System.Text.Json.Serialization;

namespace TokensWatch.Models;

/// /// <summary>Response of GET /assist/pending. Data source for the "Outside Mercy" window.</summary>
public sealed class AssistPending
{
    [JsonPropertyName("enabled")] public bool Enabled { get; set; }
    [JsonPropertyName("remaining")] public int Remaining { get; set; }

    /// <summary>Mid-match enabling was removed in v1.2.23; the server always returns 0.</summary>
    [JsonPropertyName("price")] public double Price { get; set; }

    [JsonPropertyName("log")] public List<AssistLogItem> Log { get; set; } = new();
    [JsonPropertyName("pending")] public List<AssistTicket> Pending { get; set; } = new();
}

public sealed class AssistLogItem
{
    [JsonPropertyName("tick")] public int Tick { get; set; }

    ///     /// <summary>ai = contestant, human = spectator, anything else renders as "system".</summary>
    [JsonPropertyName("who")] public string Who { get; set; } = "";

    [JsonPropertyName("text")] public string Text { get; set; } = "";
}

public sealed class AssistTicket
{
    [JsonPropertyName("ticket")] public string Ticket { get; set; } = "";
    [JsonPropertyName("tick")] public int Tick { get; set; }
    [JsonPropertyName("text")] public string Text { get; set; } = "";
}

/// /// <summary>Response of GET /scratchpad. Data source for the "AI Actions" window.</summary>
public sealed class ScratchpadResponse
{
    [JsonPropertyName("items")] public List<ScratchpadItem> Items { get; set; } = new();
}

public sealed class ScratchpadItem
{
    [JsonPropertyName("tick")] public JsonElementLite Tick { get; set; }
    [JsonPropertyName("elapsed")] public double Elapsed { get; set; }
    [JsonPropertyName("text")] public string Text { get; set; } = "";
}

/// <summary>
/// /// tick is sometimes a number and sometimes absent (Python falls back with x.get("tick", "-")).
/// /// Carried as a string; the converter handles both shapes on deserialization.
/// </summary>
[JsonConverter(typeof(JsonElementLiteConverter))]
public readonly struct JsonElementLite
{
    public string Text { get; init; }
    public JsonElementLite(string text) => Text = text;
    public override string ToString() => Text;
}

internal sealed class JsonElementLiteConverter : JsonConverter<JsonElementLite>
{
    public override JsonElementLite Read(ref System.Text.Json.Utf8JsonReader reader, Type typeToConvert, System.Text.Json.JsonSerializerOptions options)
    {
        switch (reader.TokenType)
        {
            case System.Text.Json.JsonTokenType.Number:
                return new JsonElementLite(reader.TryGetInt64(out var l) ? l.ToString() : reader.GetDouble().ToString("0.###"));
            case System.Text.Json.JsonTokenType.String:
                return new JsonElementLite(reader.GetString() ?? "—");
            case System.Text.Json.JsonTokenType.Null:
                return new JsonElementLite("—");
            default:
                reader.Skip();
                return new JsonElementLite("—");
        }
    }

    public override void Write(System.Text.Json.Utf8JsonWriter writer, JsonElementLite value, System.Text.Json.JsonSerializerOptions options)
        => writer.WriteStringValue(value.Text);
}
