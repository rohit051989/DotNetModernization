using System.Text;
using System.Text.RegularExpressions;
using Fingerprinting.Analysis;

namespace Fingerprinting.Outbound;

/// <summary>A piece of a value an expression evaluates to: literal text
/// (with where it came from, if configuration) or a hole this step could
/// not fill.</summary>
public abstract record ValuePart;

public sealed record TextPart(string Value, ConfigSource? Source = null) : ValuePart;

/// <param name="Label">What the hole stands for, as written — a variable or
/// member name; never a value.</param>
/// <param name="Placeholder">When the hole waits on a named external value:
/// <c>env:X</c>, <c>config:A:B</c>, <c>${X}</c>.</param>
public sealed record HolePart(string Label, string? Placeholder = null) : ValuePart;

/// <summary>What an expression evaluates to, syntactically.</summary>
/// <param name="WholeConfig">Set when the whole expression is one
/// configuration read.</param>
public sealed record ResolvedValue(IReadOnlyList<ValuePart> Parts, ConfigKey? WholeConfig = null)
{
    /// <summary>Every configuration key the value was read from — what
    /// decides which environment files can change it (Part C4).</summary>
    public IReadOnlyList<ConfigKey> Keys { get; init; } = WholeConfig is null ? [] : [WholeConfig];

    /// <summary>A connection string read from configuration: its facts
    /// only (host, port, provider, authentication) — the value itself never
    /// enters a <see cref="ResolvedValue"/> (Part C5).</summary>
    public ConnectionFacts? Facts { get; init; }

    public static ResolvedValue Hole(string label, string? placeholder = null) => new([new HolePart(label, placeholder)]);

    public static ResolvedValue Text(string value, ConfigSource? source = null) => new([new TextPart(value, source)]);

    public bool IsText => Facts is null && Parts.All(p => p is TextPart);

    public string? TextValue => IsText ? string.Concat(Parts.Cast<TextPart>().Select(p => p.Value)) : null;

    public ResolvedValue Concat(ResolvedValue other) => Join([this, other]);

    public static ResolvedValue Join(IEnumerable<ResolvedValue> values)
    {
        var list = values.ToList();
        return new ResolvedValue(list.SelectMany(v => v.Parts).ToList())
        {
            Keys = list.SelectMany(v => v.Keys).Distinct().ToList(),
        };
    }

    /// <summary>The placeholder the value waits on, if any.</summary>
    public string? Placeholder => Parts.OfType<HolePart>().Select(h => h.Placeholder).FirstOrDefault(p => p is not null);
}

/// <summary>A configuration key: <c>kind</c> is <c>json</c> (appsettings,
/// colon path), <c>app_setting</c> (web.config / app.config
/// &lt;appSettings&gt;) or <c>connection_string</c>.</summary>
public sealed record ConfigKey(string KeyPath, string Kind);

/// <summary>
/// Part C3 endpoint normalisation, and C5's rule that userinfo, query and
/// fragment never reach storage: an <see cref="Endpoint"/> is only ever
/// built from scheme, host, port and path, so there is nowhere for them to
/// go. Placeholders are recognised, recorded by name and never guessed at.
/// </summary>
public static partial class Endpoints
{
    [GeneratedRegex(@"\$\{(?<n>[^}]+)\}|%(?<n>[A-Za-z_][A-Za-z0-9_.]*)%|\{\{\s*(?<n>[^}]+?)\s*\}\}|#\{(?<n>[^}]+)\}")]
    private static partial Regex PlaceholderPattern();

    [GeneratedRegex(@"^(?<scheme>[A-Za-z][A-Za-z0-9+.\-]*)://(?<authority>[^/?#]*)(?<path>[^?#]*)")]
    private static partial Regex UrlShape();

    private const char HoleMark = '\u0001';

    /// <summary>The placeholder in a value, as written: <c>${SERVICE_URL}</c>.</summary>
    public static string? Placeholder(string value) =>
        PlaceholderPattern().Match(value) is { Success: true } m ? m.Value : null;

    /// <summary>An absolute URL, normalised. Null when the text is not an
    /// absolute URL (a relative path, a bare host).</summary>
    public static Endpoint? FromUrl(string raw, ConfigSource? source = null)
    {
        var text = raw.Trim();
        if (Placeholder(text) is { } placeholder)
        {
            return new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = placeholder, Source = source };
        }

        if (!Uri.TryCreate(text, UriKind.Absolute, out var uri) || uri.IsFile || string.IsNullOrEmpty(uri.Host))
        {
            return null;
        }

        return new Endpoint
        {
            Scheme = uri.Scheme.ToLowerInvariant(),
            Host = uri.Host.ToLowerInvariant(),
            Port = uri.Port >= 0 ? uri.Port : null,
            Path = uri.AbsolutePath,
            Resolution = Resolutions.Resolved,
            Source = source,
        };
    }

    /// <summary>
    /// A value that may be partly unresolved. All text: normalised as a URL.
    /// Otherwise the template is parsed around its holes — a component
    /// containing a hole is left null — and the literal fragments kept,
    /// sanitised: <c>$"net.tcp://localhost:{port}/Utility"</c> is scheme
    /// <c>net.tcp</c>, host <c>localhost</c>, path <c>/Utility</c>, port unresolved.
    /// </summary>
    public static Endpoint FromValue(ResolvedValue value)
    {
        var source = value.Parts.OfType<TextPart>().Select(p => p.Source).FirstOrDefault(s => s is not null);
        if (value.TextValue is { } whole)
        {
            return FromUrl(whole, source)
                   ?? new Endpoint { Resolution = Resolutions.Partial, Fragments = [Sanitise(whole)], Source = source };
        }

        var placeholder = value.Parts.OfType<HolePart>().Select(h => h.Placeholder).FirstOrDefault(p => p is not null);
        var template = new StringBuilder();
        foreach (var part in value.Parts)
        {
            template.Append(part is TextPart t ? t.Value : $"{HoleMark}");
        }

        var fragments = value.Parts.OfType<TextPart>().Select(t => Sanitise(t.Value)).Where(f => f.Length > 0).ToList();
        var text = template.ToString();
        if (value.Parts.Count == 1 || fragments.Count == 0)
        {
            return new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = placeholder ?? Label(value), Source = source };
        }

        var match = UrlShape().Match(text);
        if (!match.Success)
        {
            // No written scheme and host: nothing an endpoint register can
            // key on. "://" between two holes is unresolved, not partial.
            return fragments.Any(f => f.Any(char.IsLetterOrDigit))
                ? new Endpoint { Resolution = Resolutions.Partial, Placeholder = placeholder, Fragments = fragments, Source = source }
                : new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = placeholder ?? Label(value), Source = source };
        }

        var authority = match.Groups["authority"].Value;
        var at = authority.LastIndexOf('@');
        if (at >= 0)
        {
            authority = authority[(at + 1)..];   // userinfo: dropped
        }

        var colon = authority.LastIndexOf(':');
        var hostText = colon >= 0 ? authority[..colon] : authority;
        var portText = colon >= 0 ? authority[(colon + 1)..] : null;
        var scheme = match.Groups["scheme"].Value;
        return new Endpoint
        {
            Scheme = scheme.Contains(HoleMark) ? null : scheme.ToLowerInvariant(),
            Host = hostText.Length == 0 || hostText.Contains(HoleMark) ? null : hostText.ToLowerInvariant(),
            Port = portText is not null && !portText.Contains(HoleMark) && int.TryParse(portText, out var port) ? port : DefaultPort(scheme, portText),
            // The path up to its first hole: $"{api}{uri}/{id}" and
            // $"{api}{uri}" are one endpoint, /api/{…}.
            Path = PathPrefix(match.Groups["path"].Value),
            Resolution = Resolutions.Partial,
            Placeholder = placeholder,
            Fragments = fragments,
            Source = source,
        };
    }

    private static string? PathPrefix(string path)
    {
        var hole = path.IndexOf(HoleMark);
        var prefix = hole < 0 ? path : path[..hole] + "{…}";
        return prefix.Length > 0 ? prefix : null;
    }

    private static int? DefaultPort(string scheme, string? portText)
    {
        if (portText is not null)
        {
            return null;   // written, but unresolved
        }

        return scheme.ToLowerInvariant() switch
        {
            "http" => 80,
            "https" => 443,
            "net.tcp" => 808,
            _ => null,
        };
    }

    private static string Label(ResolvedValue value) =>
        string.Join(" + ", value.Parts.Select(p => p is HolePart h ? h.Placeholder ?? h.Label : "…"));

    /// <summary>A literal fragment with userinfo, query and fragment removed.</summary>
    public static string Sanitise(string fragment)
    {
        var text = fragment;
        var cut = text.IndexOfAny(['?', '#']);
        if (cut >= 0)
        {
            text = text[..cut];
        }

        var scheme = text.IndexOf("://", StringComparison.Ordinal);
        if (scheme >= 0)
        {
            var authorityStart = scheme + 3;
            var slash = text.IndexOf('/', authorityStart);
            var authorityEnd = slash < 0 ? text.Length : slash;
            var at = text.LastIndexOf('@', authorityEnd - 1, authorityEnd - authorityStart);
            if (at >= 0)
            {
                text = text[..authorityStart] + text[(at + 1)..];
            }
        }

        return text.Trim();
    }

    /// <summary><c>host:port</c> or <c>host</c> — Redis, Kafka, SMTP. For a
    /// Redis configuration string, the first option without '=' is the
    /// endpoint; <c>password=...</c> and every other option are never read
    /// into the result.</summary>
    public static Endpoint FromHostPort(string scheme, string text, ConfigSource? source = null)
    {
        if (Placeholder(text) is { } placeholder)
        {
            return new Endpoint { Scheme = scheme, Resolution = Resolutions.Unresolved, Placeholder = placeholder, Source = source };
        }

        var first = text.Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .FirstOrDefault(t => !t.Contains('='));
        if (first is null)
        {
            return new Endpoint { Scheme = scheme, Resolution = Resolutions.Unresolved, Source = source };
        }

        if (first.Contains("://") && FromUrl(first, source) is { } url)
        {
            return url with { Scheme = scheme };
        }

        var colon = first.LastIndexOf(':');
        return new Endpoint
        {
            Scheme = scheme,
            Host = (colon > 0 ? first[..colon] : first).ToLowerInvariant(),
            Port = colon > 0 && int.TryParse(first[(colon + 1)..], out var port) ? port : null,
            Resolution = Resolutions.Resolved,
            Source = source,
        };
    }

    /// <summary><c>\\server\share\deeper\path</c> → host <c>server</c>, path
    /// <c>/share</c>. Only the share: deeper segments can name people.</summary>
    public static (Endpoint Endpoint, string Share)? FromUnc(string path)
    {
        var trimmed = path.Trim();
        if (!trimmed.StartsWith(@"\\", StringComparison.Ordinal))
        {
            return null;
        }

        var segments = trimmed[2..].Split('\\', StringSplitOptions.RemoveEmptyEntries);
        if (segments.Length < 2)
        {
            return null;
        }

        var host = segments[0].ToLowerInvariant();
        return (new Endpoint { Scheme = "smb", Host = host, Path = "/" + segments[1], Resolution = Resolutions.Resolved },
            $@"\\{host}\{segments[1]}");
    }

    /// <summary>An MSMQ path: <c>FormatName:DIRECT=OS:host\private$\q</c>,
    /// <c>FormatName:DIRECT=TCP:10.0.0.1\q</c>, <c>host\private$\q</c> or
    /// <c>.\private$\q</c> (this machine).</summary>
    public static Endpoint FromMsmqPath(string path)
    {
        var text = path.Trim();
        var direct = Regex.Match(text, @"DIRECT=(?:OS|TCP|HTTP|HTTPS):(?<rest>.+)$", RegexOptions.IgnoreCase);
        if (direct.Success)
        {
            text = direct.Groups["rest"].Value;
        }

        var parts = text.Split('\\', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length == 0)
        {
            return new Endpoint { Scheme = "msmq", Resolution = Resolutions.Unresolved };
        }

        var host = parts[0] == "." ? "localhost" : parts[0].ToLowerInvariant();
        return new Endpoint { Scheme = "msmq", Host = host, Path = "/" + string.Join('/', parts.Skip(1)), Resolution = Resolutions.Resolved };
    }

    /// <summary><c>LDAP://dc01.corp.local/DC=corp,DC=local</c> → host only.</summary>
    public static Endpoint FromLdapPath(string path)
    {
        var match = Regex.Match(path.Trim(), @"^(?<scheme>LDAPS?|GC)://(?<host>[^/:]+)(:(?<port>\d+))?", RegexOptions.IgnoreCase);
        if (!match.Success)
        {
            return new Endpoint { Scheme = "ldap", Resolution = Resolutions.Unresolved, Placeholder = "current domain" };
        }

        return new Endpoint
        {
            Scheme = match.Groups["scheme"].Value.ToLowerInvariant(),
            Host = match.Groups["host"].Value.ToLowerInvariant(),
            Port = match.Groups["port"].Success ? int.Parse(match.Groups["port"].Value) : null,
            Resolution = Resolutions.Resolved,
        };
    }

    /// <summary>A stable text key for an endpoint, for invocation ids and merging.</summary>
    public static string Key(Endpoint endpoint) => endpoint.Resolution == Resolutions.Unresolved
        ? $"unresolved:{endpoint.Placeholder ?? endpoint.Source?.KeyPath ?? ""}"
        : $"{endpoint.Scheme}://{endpoint.Host}:{endpoint.Port}{endpoint.Path}|{endpoint.Resolution}|{endpoint.Source?.KeyPath}";

    /// <summary>For display and the incompatible list.</summary>
    public static string Display(Endpoint endpoint)
    {
        if (endpoint.Resolution == Resolutions.Unresolved)
        {
            return $"unresolved ({endpoint.Placeholder ?? endpoint.Source?.KeyPath ?? "dynamic"})";
        }

        var port = endpoint.Port is { } p ? $":{p}" : "";
        return endpoint.Scheme is null && endpoint.Host is null
            ? string.Join(" … ", endpoint.Fragments)
            : $"{endpoint.Scheme ?? "?"}://{endpoint.Host ?? "?"}{port}{endpoint.Path}";
    }
}
