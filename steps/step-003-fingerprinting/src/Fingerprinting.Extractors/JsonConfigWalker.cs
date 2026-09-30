using System.Text;
using System.Text.Json;

namespace Fingerprinting.Extractors;

/// <summary>
/// Which configuration files step 3 reads. <c>appsettings*.json</c> covers
/// the environment variants (<c>appsettings.Development.json</c>,
/// <c>appsettings.DEVOCP.json</c>) that an exact <c>appsettings.json</c> match
/// used to miss — they carry the same connection strings, sinks and paths.
/// </summary>
internal static class ConfigFiles
{
    public static bool IsAppSettings(string fileName) =>
        fileName.StartsWith("appsettings", StringComparison.OrdinalIgnoreCase)
        && fileName.EndsWith(".json", StringComparison.OrdinalIgnoreCase);

    public static bool IsXmlConfig(string fileName) =>
        string.Equals(fileName, "web.config", StringComparison.OrdinalIgnoreCase)
        || string.Equals(fileName, "app.config", StringComparison.OrdinalIgnoreCase);
}

/// <summary>One JSON value in an appsettings file, flattened with its path
/// and the line it sits on.</summary>
internal sealed record JsonConfigNode
{
    /// <summary>Property names, and array indices as "0", "1"… — the same
    /// segments .NET configuration uses.</summary>
    public required IReadOnlyList<string> Path { get; init; }

    public required int Line { get; init; }

    public required JsonTokenType Kind { get; init; }

    /// <summary>The string value, or null when the node is not a string or
    /// is secret-bearing. Never populated for a connection string or
    /// anything under a sensitive key — the walker does not materialise
    /// those (Part G).</summary>
    public string? StringValue { get; init; }

    /// <summary>The node is a sensitive key itself (its subtree is skipped,
    /// never read).</summary>
    public bool IsSensitiveKey { get; init; }

    /// <summary>A direct child of a <c>ConnectionStrings</c> section.</summary>
    public bool IsConnectionString { get; init; }

    /// <summary>Only meaningful when <see cref="IsConnectionString"/>: the
    /// verdict of <see cref="Secrets.UsesWindowsAuthentication"/>. The
    /// string it was computed from is not kept.</summary>
    public bool UsesWindowsAuthentication { get; init; }

    public string Name => Path.Count == 0 ? string.Empty : Path[^1];

    /// <summary>Colon-separated key path, e.g. <c>Serilog:WriteTo:0:Name</c>.</summary>
    public string KeyPath => string.Join(':', Path);
}

/// <summary>
/// Reads an appsettings file with <see cref="Utf8JsonReader"/> so every node
/// carries a line number — <see cref="JsonDocument"/> exposes none, which is
/// why appsettings evidence used to have no line spans. Walks arrays as well
/// as objects (Serilog's <c>WriteTo</c> is an array). Comments and trailing
/// commas are accepted, as .NET's configuration loader accepts them.
///
/// Secrets are handled here, structurally: a sensitive key's subtree is
/// skipped unread, and a connection string's value is read only to be handed
/// to <see cref="Secrets.UsesWindowsAuthentication"/> and then dropped.
/// </summary>
internal static class JsonConfigWalker
{
    private static readonly JsonReaderOptions ReaderOptions = new()
    {
        CommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true,
    };

    public static IReadOnlyList<JsonConfigNode> Walk(string filePath)
    {
        var bytes = File.ReadAllBytes(filePath).AsSpan();
        var bom = Encoding.UTF8.Preamble;
        if (bytes.StartsWith(bom))
        {
            bytes = bytes[bom.Length..];
        }

        var lines = new LineMap(bytes);
        var reader = new Utf8JsonReader(bytes, ReaderOptions);
        var nodes = new List<JsonConfigNode>();

        if (reader.Read())
        {
            ReadValue(ref reader, [], lines.LineOf(reader.TokenStartIndex), underConnectionStrings: false, nodes, lines);
        }

        return nodes;
    }

    private static void ReadValue(
        ref Utf8JsonReader reader, List<string> path, int line, bool underConnectionStrings,
        List<JsonConfigNode> nodes, LineMap lines)
    {
        var name = path.Count == 0 ? string.Empty : path[^1];

        if (underConnectionStrings)
        {
            // A connection string: the one permitted read, straight into the
            // Windows-auth check, never into the node.
            var windowsAuth = reader.TokenType == JsonTokenType.String
                && Secrets.UsesWindowsAuthentication(reader.GetString() ?? string.Empty);
            nodes.Add(new JsonConfigNode
            {
                Path = [.. path], Line = line, Kind = reader.TokenType,
                IsConnectionString = true, UsesWindowsAuthentication = windowsAuth,
            });
            reader.Skip();
            return;
        }

        var isConnectionStringsSection = string.Equals(name, "ConnectionStrings", StringComparison.OrdinalIgnoreCase)
            && reader.TokenType == JsonTokenType.StartObject;

        if (!isConnectionStringsSection && path.Count > 0 && Secrets.IsSensitiveKey(name))
        {
            nodes.Add(new JsonConfigNode { Path = [.. path], Line = line, Kind = reader.TokenType, IsSensitiveKey = true });
            reader.Skip();
            return;
        }

        switch (reader.TokenType)
        {
            case JsonTokenType.StartObject:
                nodes.Add(new JsonConfigNode { Path = [.. path], Line = line, Kind = JsonTokenType.StartObject });
                while (reader.Read() && reader.TokenType == JsonTokenType.PropertyName)
                {
                    var propertyName = reader.GetString() ?? string.Empty;
                    var propertyLine = lines.LineOf(reader.TokenStartIndex);
                    reader.Read();
                    path.Add(propertyName);
                    ReadValue(ref reader, path, propertyLine, isConnectionStringsSection, nodes, lines);
                    path.RemoveAt(path.Count - 1);
                }
                break;

            case JsonTokenType.StartArray:
                nodes.Add(new JsonConfigNode { Path = [.. path], Line = line, Kind = JsonTokenType.StartArray });
                var index = 0;
                while (reader.Read() && reader.TokenType != JsonTokenType.EndArray)
                {
                    path.Add(index.ToString(System.Globalization.CultureInfo.InvariantCulture));
                    ReadValue(ref reader, path, lines.LineOf(reader.TokenStartIndex), underConnectionStrings: false, nodes, lines);
                    path.RemoveAt(path.Count - 1);
                    index++;
                }
                break;

            case JsonTokenType.String:
                nodes.Add(new JsonConfigNode
                {
                    Path = [.. path], Line = line, Kind = JsonTokenType.String, StringValue = reader.GetString(),
                });
                break;

            default:
                nodes.Add(new JsonConfigNode { Path = [.. path], Line = line, Kind = reader.TokenType });
                break;
        }
    }

    /// <summary>Byte offset to 1-based line number.</summary>
    private sealed class LineMap
    {
        private readonly List<long> _lineStarts = [0];

        public LineMap(ReadOnlySpan<byte> bytes)
        {
            for (var i = 0; i < bytes.Length; i++)
            {
                if (bytes[i] == (byte)'\n')
                {
                    _lineStarts.Add(i + 1);
                }
            }
        }

        public int LineOf(long offset)
        {
            var index = _lineStarts.BinarySearch(offset);
            return (index >= 0 ? index : ~index - 1) + 1;
        }
    }
}
