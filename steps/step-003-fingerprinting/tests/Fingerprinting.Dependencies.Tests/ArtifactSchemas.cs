using System.Collections.Concurrent;
using Fingerprinting.Dependencies;
using Fingerprinting.Domain;
using Fingerprinting.StepHost;

namespace Fingerprinting.Tests;

/// <summary>A whole dependency-assessment artifact validated against the schema file of the version it declares, the
/// file the step validates against before it writes (CLAUDE.md rule 21). Each schema file is loaded once per test run:
/// a schema registers its <c>$id</c>, and a second load of the same one is refused.</summary>
internal static class ArtifactSchemas
{
    private static readonly ConcurrentDictionary<string, Lazy<ArtifactSchemaValidator>> Loaded = new(StringComparer.Ordinal);

    public static void Validate(DependencyAssessmentArtifact artifact)
    {
        var file = $"dependency-assessment-{artifact.ArtifactVersion}.schema.json";
        Loaded.GetOrAdd(file, f => new Lazy<ArtifactSchemaValidator>(() => ArtifactSchemaValidator.Load(Path.Combine(AppContext.BaseDirectory, "schemas", f))))
            .Value.Validate(DeterministicJson.Serialize(artifact));
    }
}
