using System.Text.Json;
using System.Text.Json.Serialization;
using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// One entry from <c>schemas/signal-registry-&lt;version&gt;.json</c>.
/// </summary>
public sealed record SignalRegistryEntry
{
    [JsonPropertyName("name")]
    public required string Name { get; init; }

    [JsonPropertyName("category")]
    public required string Category { get; init; }

    [JsonPropertyName("type")]
    public required string Type { get; init; }

    [JsonPropertyName("description")]
    public required string Description { get; init; }

    [JsonPropertyName("extractor")]
    public required string Extractor { get; init; }

    [JsonPropertyName("value_semantics")]
    public required string ValueSemantics { get; init; }
}

file sealed record SignalRegistryFile
{
    [JsonPropertyName("registry_version")]
    public required string RegistryVersion { get; init; }

    [JsonPropertyName("signals")]
    public required IReadOnlyList<SignalRegistryEntry> Signals { get; init; }
}

/// <summary>
/// Thrown when a signal carries a name absent from the registry — a
/// validation failure, not a warning, per
/// 21-STEP-003-FINGERPRINTING.md Part D.
/// </summary>
public sealed class UnregisteredSignalException(IReadOnlyList<string> unregisteredNames)
    : Exception(
        $"Emitted signal name(s) not present in the signal registry: {string.Join(", ", unregisteredNames)}")
{
    public IReadOnlyList<string> UnregisteredNames { get; } = unregisteredNames;
}

/// <summary>
/// Loads the versioned signal registry and rejects any emitted signal whose
/// name is not in it. The registry is the vocabulary step 4's detection rules
/// will eventually bind to — see that doc's "Note for step 4".
/// </summary>
public sealed class SignalRegistry
{
    private readonly HashSet<string> _registeredNames;

    public string RegistryVersion { get; }

    private SignalRegistry(string registryVersion, IReadOnlyList<SignalRegistryEntry> entries)
    {
        RegistryVersion = registryVersion;
        _registeredNames = new HashSet<string>(entries.Select(e => e.Name), StringComparer.Ordinal);
    }

    public static SignalRegistry Load(string path)
    {
        var json = File.ReadAllText(path);
        var file = JsonSerializer.Deserialize<SignalRegistryFile>(json)
            ?? throw new InvalidOperationException($"Signal registry at '{path}' deserialized to null.");
        return new SignalRegistry(file.RegistryVersion, file.Signals);
    }

    public bool IsRegistered(string signalName) => _registeredNames.Contains(signalName);

    /// <summary>
    /// Throws <see cref="UnregisteredSignalException"/> if any signal's name
    /// is not in the registry. Call this before the artifact is written —
    /// an unregistered name must fail the step, never merely warn.
    /// </summary>
    public void Validate(IEnumerable<Signal> signals)
    {
        var unregistered = signals
            .Select(s => s.Name)
            .Where(name => !_registeredNames.Contains(name))
            .Distinct(StringComparer.Ordinal)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToList();

        if (unregistered.Count > 0)
        {
            throw new UnregisteredSignalException(unregistered);
        }
    }
}
