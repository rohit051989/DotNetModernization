using System.Text.Json;
using System.Text.Json.Serialization.Metadata;

namespace Fingerprinting.Domain;

/// <summary>
/// The one JSON configuration every artifact and StepResult write must go
/// through — see 21-STEP-003-FINGERPRINTING.md Part B rule 2:
/// alphabetical keys at every level, two-space indent, explicit '\n' line
/// endings, invariant culture. Two runs over unchanged input must produce
/// identical bytes.
/// </summary>
public static class DeterministicJson
{
    public static readonly JsonSerializerOptions Options = Create();

    private static JsonSerializerOptions Create()
    {
        var resolver = new DefaultJsonTypeInfoResolver();
        resolver.Modifiers.Add(SortPropertiesAlphabetically);

        return new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            TypeInfoResolver = resolver,
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
}
