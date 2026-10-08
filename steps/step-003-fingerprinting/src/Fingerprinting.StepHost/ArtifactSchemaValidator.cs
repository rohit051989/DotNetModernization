using System.Text.Json;
using Json.Schema;

namespace Fingerprinting.StepHost;

/// <summary>
/// Validates a serialized artifact against
/// schemas/application-fingerprint-1.0.0.schema.json before it is written —
/// 21-APPLICATION-FINGERPRINTING.md Part F: "A schema validation failure is a
/// step failure, not a warning."
/// </summary>
public sealed class ArtifactSchemaValidator
{
    private readonly JsonSchema _schema;

    private ArtifactSchemaValidator(JsonSchema schema)
    {
        _schema = schema;
    }

    public static ArtifactSchemaValidator Load(string schemaPath)
    {
        var schema = JsonSchema.FromText(File.ReadAllText(schemaPath));
        return new ArtifactSchemaValidator(schema);
    }

    /// <summary>Throws <see cref="ArtifactSchemaValidationException"/> if
    /// <paramref name="artifactJson"/> does not conform.</summary>
    public void Validate(string artifactJson)
    {
        using var document = JsonDocument.Parse(artifactJson);
        var results = _schema.Evaluate(document.RootElement, new EvaluationOptions { OutputFormat = OutputFormat.List });

        if (results.IsValid)
        {
            return;
        }

        var errors = (results.Details ?? [])
            .Where(d => !d.IsValid && d.Errors is { Count: > 0 })
            .SelectMany(d => d.Errors!.Select(e => $"{d.InstanceLocation}: {e.Key} — {e.Value}"))
            .ToList();

        if (errors.Count == 0)
        {
            errors.Add("Schema validation failed (no per-node error detail available).");
        }

        throw new ArtifactSchemaValidationException(errors);
    }
}

public sealed class ArtifactSchemaValidationException(IReadOnlyList<string> errors)
    : Exception($"Artifact failed JSON Schema validation:\n{string.Join('\n', errors)}")
{
    public IReadOnlyList<string> Errors { get; } = errors;
}
