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
    private const string RepoRootBaseId = "REPOROOT";

    /// <param name="repoRootUri">Null for the registered, checksummed
    /// artifact — <c>originalUriBaseIds.REPOROOT</c> is still declared, but
    /// with no <c>uri</c>, so no absolute machine path enters the checksum.
    /// Pass the repository's absolute <c>file://</c> URI to build the
    /// local-only sibling instead, so a SARIF viewer on this machine can
    /// resolve source locations.</param>
    public static SarifLog Build(ApplicationFingerprintArtifact artifact, SignalRegistry registry, string? repoRootUri = null)
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

        var originalUriBaseIds = new Dictionary<string, SarifArtifactLocation>
        {
            [RepoRootBaseId] = new SarifArtifactLocation { Uri = repoRootUri },
        };

        var runs = artifact.Projects
            .Select(project => BuildRun(project, driver, taxonomy, descriptionsByName, originalUriBaseIds))
            .ToList();

        // Repository-level signals (deployment files outside every project)
        // get one run of their own, after the per-project runs.
        if (artifact.RepositorySignals.Count > 0)
        {
            runs.Add(new SarifRun
            {
                Tool = new SarifTool { Driver = driver },
                Results = artifact.RepositorySignals.Select(signal => BuildResult(signal, descriptionsByName)).ToList(),
                Taxonomies = [taxonomy],
                OriginalUriBaseIds = originalUriBaseIds,
                Properties = new Dictionary<string, object?> { ["scope"] = "repository" },
            });
        }

        return new SarifLog { Runs = runs };
    }

    private static SarifRun BuildRun(
        ProjectFingerprint project,
        SarifToolComponent driver,
        SarifToolComponent taxonomy,
        IReadOnlyDictionary<string, string> descriptionsByName,
        IReadOnlyDictionary<string, SarifArtifactLocation> originalUriBaseIds)
    {
        var results = project.Signals
            .Select(signal => BuildResult(signal, descriptionsByName))
            .ToList();

        return new SarifRun
        {
            Tool = new SarifTool { Driver = driver },
            Results = results,
            Taxonomies = [taxonomy],
            OriginalUriBaseIds = originalUriBaseIds,
            Properties = new Dictionary<string, object?>
            {
                ["projectId"] = project.ProjectId.ToString(),
                ["fingerprintStatus"] = project.FingerprintStatus,
            },
        };
    }

    private static SarifResult BuildResult(Signal signal, IReadOnlyDictionary<string, string> descriptionsByName)
    {
        var properties = new Dictionary<string, object?>
        {
            ["occurrenceCount"] = signal.OccurrenceCount,
            ["extractionConfidence"] = signal.ExtractionConfidence,
        };

        if (signal.EvidenceKind == SignalEvidenceKinds.Folder && signal.SourcePath is not null)
        {
            // Not a "location" per SARIF (see BuildLocations) but still real
            // data worth keeping — the folder is what the signal observed.
            properties["folderPath"] = signal.SourcePath;
        }

        return new SarifResult
        {
            RuleId = signal.Name,
            Level = "none",
            Message = new SarifMessage { Text = descriptionsByName[signal.Name] },
            Locations = BuildLocations(signal),
            Properties = properties,
        };
    }

    /// <summary>One location per evidence span (each carries its own
    /// region); if there is no evidence but a source path is known, one
    /// location naming the file with no region; if neither is known, no
    /// locations at all (result.locations is optional per the SARIF schema).
    /// A FOLDER (or NONE) evidence kind always yields no locations — SARIF's
    /// physicalLocation means a location within an artifact a viewer can
    /// open and navigate to, and a directory (or the absence of a source
    /// path) is neither. Emitting one for a folder-presence signal (e.g.
    /// SERVICES_FOLDER's sourcePath "src/ApplicationCore/Services") is what
    /// broke the VS Code SARIF viewer — 25-STANDARDS-AND-VIEWPOINTS.md Part
    /// A3 addendum.</summary>
    /// <summary>A repository-relative path as a SARIF <c>uri-reference</c>:
    /// each segment percent-encoded, '/' kept. A raw path with a space (a
    /// svcutil client under "Connected Services/") is not a valid URI
    /// reference and fails SARIF schema validation — which failed the whole
    /// scan the first time such a file carried a signal.</summary>
    internal static string ToUriReference(string repositoryRelativePath) =>
        string.Join('/', repositoryRelativePath.Split('/').Select(Uri.EscapeDataString));

    private static IReadOnlyList<SarifLocation>? BuildLocations(Signal signal)
    {
        if (signal.EvidenceKind != SignalEvidenceKinds.File)
        {
            return null;
        }

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
                        ArtifactLocation = new SarifArtifactLocation { Uri = ToUriReference(signal.SourcePath), UriBaseId = RepoRootBaseId },
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
                        ArtifactLocation = new SarifArtifactLocation { Uri = ToUriReference(signal.SourcePath), UriBaseId = RepoRootBaseId },
                    },
                },
            ];
        }

        return null;
    }
}
