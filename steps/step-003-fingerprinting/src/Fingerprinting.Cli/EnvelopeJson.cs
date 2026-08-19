using System.Text.Json;
using System.Text.Json.Serialization;

namespace Fingerprinting.Cli;

/// <summary>
/// JSON options for the step envelope (StepContext in, StepResult out) —
/// snake_case, compact, per 11-STEP-CONTRACT.md. Distinct from
/// <see cref="Fingerprinting.Domain.DeterministicJson"/>, which is camelCase,
/// indented and key-sorted for the artifact file only. Mirrors
/// steps/step-002-solution-discovery/main.py's stdout write: no indentation,
/// no key sorting — property declaration order is the wire order.
/// </summary>
public static class EnvelopeJson
{
    public static readonly JsonSerializerOptions Options = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        WriteIndented = false,
    };
}
