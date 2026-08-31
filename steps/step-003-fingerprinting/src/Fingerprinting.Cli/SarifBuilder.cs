using Fingerprinting.Domain;
using Fingerprinting.Extractors;

namespace Fingerprinting.Cli;

/// <summary>
/// Builds the <c>fingerprint-sarif@2.1.0</c> log from an already-computed
/// <see cref="ApplicationFingerprintArtifact"/> — 25-STANDARDS-AND-VIEWPOINTS.md
/// Part A3. Purely a re-projection: it never re-scans anything, so it
/// inherits the native artifact's determinism (projects sorted by path,
/// signals sorted by category/name/sourcePath) rather than having to
/// re-establish it.
/// </summary>
public static class SarifBuilder
{
    private const string ToolName = "Fingerprinting.Cli";
    private const string TaxonomyName = "signal-categories";
    private const string TaxonomyVersion = "1.0.0";

    public static SarifLog Build(ApplicationFingerprintArtifact artifact, SignalRegistry registry)
    {
        var descriptionsByName = registry.Entries.ToDictionary(e => e.Name, e => e.Description, StringComparer.Ordinal);

        var rules = registry.Entries
            .OrderBy(e => e.Name, StringComparer.Ordinal)
            .Select(e => new SarifReportingDescriptor
            {
                Id = e.Name,
                Name = e.Name,
                ShortDescription = new SarifMessage { Text = e.Description },
                Properties = new Dictionary<string, object?> { ["category"] = e.Category },
            })
            .ToList();

        var taxa = registry.Entries
            .Select(e => e.Category)
            .Distinct(StringComparer.Ordinal)
            .OrderBy(c => c, StringComparer.Ordinal)
            .Select(category => new SarifReportingDescriptor { Id = category, Name = category })
            .ToList();

        var taxonomy = new SarifToolComponent
        {
            Name = TaxonomyName,
            Version = TaxonomyVersion,
            Taxa = taxa,
        };

        var driver = new SarifToolComponent
        {
            Name = ToolName,
            Version = artifact.ScannerVersion,
            Rules = rules,
        };

        var runs = artifact.Projects
            .Select(project => BuildRun(project, driver, taxonomy, descriptionsByName))
            .ToList();

        return new SarifLog { Runs = runs };
    }

    private static SarifRun BuildRun(
        ProjectFingerprint project,
        SarifToolComponent driver,
        SarifToolComponent taxonomy,
        IReadOnlyDictionary<string, string> descriptionsByName)
    {
        var results = project.Signals
            .Select(signal => BuildResult(signal, descriptionsByName))
            .ToList();

        return new SarifRun
        {
            Tool = new SarifTool { Driver = driver },
            Results = results,
            Taxonomies = [taxonomy],
            Properties = new Dictionary<string, object?>
            {
                ["projectId"] = project.ProjectId.ToString(),
                ["fingerprintStatus"] = project.FingerprintStatus,
            },
        };
    }

    private static SarifResult BuildResult(Signal signal, IReadOnlyDictionary<string, string> descriptionsByName)
    {
        return new SarifResult
        {
            RuleId = signal.Name,
            Level = "none",
            Message = new SarifMessage { Text = descriptionsByName[signal.Name] },
            Locations = BuildLocations(signal),
            Properties = new Dictionary<string, object?>
            {
                ["occurrenceCount"] = signal.OccurrenceCount,
                ["extractionConfidence"] = signal.ExtractionConfidence,
            },
        };
    }

    /// <summary>One location per evidence span (each carries its own
    /// region); if there is no evidence but a source path is known, one
    /// location naming the file with no region; if neither is known, no
    /// locations at all (result.locations is optional per the SARIF schema).</summary>
    private static IReadOnlyList<SarifLocation>? BuildLocations(Signal signal)
    {
        if (signal.Evidence.Count > 0)
        {
            if (signal.SourcePath is null)
            {
                // Cannot happen with the current extractors (evidence is
                // only ever attached alongside a source path), but the
                // domain model allows it, so degrade to "no locations"
                // rather than emit an artifactLocation with an empty uri.
                return null;
            }

            return signal.Evidence
                .Select(evidence => new SarifLocation
                {
                    PhysicalLocation = new SarifPhysicalLocation
                    {
                        ArtifactLocation = new SarifArtifactLocation { Uri = signal.SourcePath },
                        Region = evidence.LineStart is null
                            ? null
                            : new SarifRegion { StartLine = evidence.LineStart, EndLine = evidence.LineEnd },
                    },
                })
                .ToList();
        }

        if (signal.SourcePath is not null)
        {
            return
            [
                new SarifLocation
                {
                    PhysicalLocation = new SarifPhysicalLocation
                    {
                        ArtifactLocation = new SarifArtifactLocation { Uri = signal.SourcePath },
                    },
                },
            ];
        }

        return null;
    }
}
