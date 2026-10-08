using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.Json.Serialization.Metadata;

namespace Fingerprinting.Domain;

/// <summary>
/// The one JSON configuration every artifact and StepResult write must go
/// through — see 21-APPLICATION-FINGERPRINTING.md Part B rule 2:
/// alphabetical keys at every level, two-space indent, explicit '\n' line
/// endings, invariant culture. Two runs over unchanged input must produce
/// identical bytes.
/// </summary>
public static class DeterministicJson
{
    public static readonly JsonSerializerOptions Options = Create(omitNulls: false);

    /// <summary>Same determinism guarantees as <see cref="Options"/>, but
    /// omits a property entirely instead of writing it as <c>null</c> — for
    /// formats like SARIF 2.1.0 whose schema types most optional properties
    /// as object/string/integer without "null", so an explicit null (valid
    /// in our own native artifact) would fail schema validation there.</summary>
    public static readonly JsonSerializerOptions OptionsOmitNulls = Create(omitNulls: true);

    private static JsonSerializerOptions Create(bool omitNulls)
    {
        var resolver = new DefaultJsonTypeInfoResolver();
        resolver.Modifiers.Add(SortPropertiesAlphabetically);

        return new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            TypeInfoResolver = resolver,
            DefaultIgnoreCondition = omitNulls ? JsonIgnoreCondition.WhenWritingNull : JsonIgnoreCondition.Never,
        };
    }

    private static void SortPropertiesAlphabetically(JsonTypeInfo typeInfo)
    {
        if (typeInfo.Kind != JsonTypeInfoKind.Object || typeInfo.Properties.Count < 2)
        {
            return;
        }

        var sorted = typeInfo.Properties.OrderBy(p => p.Name, StringComparer.Ordinal).ToList();
        typeInfo.Properties.Clear();
        foreach (var property in sorted)
        {
            typeInfo.Properties.Add(property);
        }
    }

    /// <summary>
    /// Serializes with sorted keys, two-space indent and explicit '\n' line
    /// endings (never <see cref="Environment.NewLine"/>), terminated by a
    /// single trailing newline.
    /// </summary>
    public static string Serialize<T>(T value)
    {
        var json = JsonSerializer.Serialize(value, Options);
        return json.Replace("\r\n", "\n") + "\n";
    }

    /// <summary>Same as <see cref="Serialize{T}"/>, using <see cref="OptionsOmitNulls"/>.</summary>
    public static string SerializeOmitNulls<T>(T value)
    {
        var json = JsonSerializer.Serialize(value, OptionsOmitNulls);
        return json.Replace("\r\n", "\n") + "\n";
    }
}
