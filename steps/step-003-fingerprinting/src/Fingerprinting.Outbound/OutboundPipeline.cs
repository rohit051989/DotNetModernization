using System.Security.Cryptography;
using System.Text;
using Fingerprinting.Analysis;
using Fingerprinting.Domain;

namespace Fingerprinting.Outbound;

/// <summary>One project as the pipeline receives it: step 2's path and
/// packages, the database id, step 3's verdict on whether to scan it, and
/// step 3's UNC path literals for it.</summary>
public sealed record OutboundInputProject(
    string RelativePath, Guid ProjectId, string? SkipReason, IReadOnlyList<string> Packages, IReadOnlyList<UncLiteral> UncLiterals);

public sealed record OutboundInput(
    Guid RepositoryId,
    string RepositorySlug,
    string SkipSource,
    IReadOnlyList<OutboundInputProject> Projects,
    IReadOnlyList<Warning> Warnings);

/// <summary>
/// Builds the outbound-invocation-inventory@1.0.0 artifact for one
/// repository — 29-STEPS-004-005-INVENTORIES.md Part C. Deterministic per
/// step 3's rules: every collection sorted, ids derived, nothing time- or
/// machine-dependent.
/// </summary>
public sealed class OutboundPipeline
{
    /// <summary>Matches the outbound-invocation-inventory step registration version.</summary>
    public const string ScannerVersion = "1.1.0";

    public async Task<OutboundInventoryArtifact> RunAsync(OutboundInput input, string repositoryRoot, CancellationToken cancellationToken)
    {
        var results = new List<ProjectInvocations>();
        var loaded = new List<(OutboundInputProject Input, ProjectSource Source)>();

        foreach (var project in input.Projects.OrderBy(p => p.RelativePath, StringComparer.Ordinal))
        {
            if (project.SkipReason is not null)
            {
                results.Add(Empty(project, ProjectScanStatuses.Skipped, project.SkipReason, []));
                continue;
            }

            var directory = Path.GetDirectoryName(Path.Combine(repositoryRoot, project.RelativePath.Replace('/', Path.DirectorySeparatorChar)))!;
            if (!Directory.Exists(directory))
            {
                results.Add(Empty(project, ProjectScanStatuses.Failed, null,
                [
                    new Warning
                    {
                        Code = WarningCodes.ProjectDirectoryNotFound,
                        Message = $"Project directory not found on disk: {project.RelativePath}",
                        Severity = WarningSeverities.Warning,
                    },
                ]));
                continue;
            }

            // Generated files are loaded (flagged) so a service reference's
            // Reference.cs can supply a binding; nothing else reads them.
            loaded.Add((project, await ProjectSource.LoadAsync(
                repositoryRoot, project.RelativePath, project.Packages, NoAuxiliaryFiles.Instance, cancellationToken, includeGenerated: true)));
        }

        var config = RepositoryConfig.Build(repositoryRoot, cancellationToken);
        results.AddRange(Detect(input.RepositoryId, loaded, config));
        results = results.OrderBy(r => r.ProjectPath, StringComparer.Ordinal).ToList();

        return new OutboundInventoryArtifact
        {
            ScannerVersion = ScannerVersion,
            RepositoryId = input.RepositoryId,
            RepositorySlug = input.RepositorySlug,
            SemanticAnalysisEnabled = false,
            SkipSource = input.SkipSource,
            Summary = Summarise(results),
            Projects = results,
            Warnings = input.Warnings.OrderBy(w => w.Message, StringComparer.Ordinal).ToList(),
        };
    }

    /// <summary>Detection over already-loaded projects — the entry point tests use.</summary>
    public static IReadOnlyList<ProjectInvocations> Detect(
        Guid repositoryId, IReadOnlyList<(OutboundInputProject Input, ProjectSource Source)> loaded, RepositoryConfig config)
    {
        var sources = loaded.Select(l => l.Source).ToList();
        var symbols = SymbolIndex.Build(sources);
        var contexts = loaded.Select(l => (l.Input, Context: new DetectionContext
        {
            Project = l.Source,
            Resolver = new ValueResolver(l.Source, symbols, config),
            Symbols = symbols,
            Config = config,
            Repository = sources,
            UncLiterals = l.Input.UncLiterals,
        })).ToList();
        var references = DatabaseDetector.IndexReferences(contexts.Select(c => c.Context));

        var results = new List<ProjectInvocations>();
        foreach (var (project, context) in contexts)
        {
            var detected = new List<Detected>();
            detected.AddRange(SoapClientDetector.Detect(context));
            detected.AddRange(HttpClientDetector.Detect(context));
            detected.AddRange(GrpcClientDetector.Detect(context));
            detected.AddRange(DatabaseDetector.Detect(context, references));
            detected.AddRange(MessagingDetector.Detect(context));
            detected.AddRange(CacheDetector.Detect(context));
            detected.AddRange(SecretStoreDetector.Detect(context));
            detected.AddRange(FileShareDetector.Detect(context));
            detected.AddRange(SmtpDetector.Detect(context));
            detected.AddRange(LdapDetector.Detect(context));

            var invocations = Finish(repositoryId, project.RelativePath, detected);
            var used = invocations.Where(i => i.Usage == Usages.Used).ToList();
            var warnings = new List<Warning>();
            if (context.Project.Truncated)
            {
                warnings.Add(new Warning
                {
                    Code = WarningCodes.SourceFileCapExceeded,
                    Message = $"More than {SourceFileScanner.MaxFilesPerProject} C# files; the rest were not read.",
                    Severity = WarningSeverities.Warning,
                });
            }

            results.Add(new ProjectInvocations
            {
                ProjectId = project.ProjectId,
                ProjectPath = project.RelativePath,
                Status = ProjectScanStatuses.Scanned,
                Summary = new ProjectOutboundSummary
                {
                    UnusedCount = invocations.Count - used.Count,
                    CountByMechanism = Count(used.Select(i => i.Mechanism)),
                    CountByVerdict = Count(used.Select(i => i.LinuxCompatibility.Verdict)),
                    Incompatible = used
                        .Where(i => i.LinuxCompatibility.Verdict == Verdicts.Incompatible)
                        .Select(i => new IncompatibleInvocation
                        {
                            InvocationId = i.InvocationId,
                            Mechanism = i.Mechanism,
                            Endpoint = Endpoints.Display(i.Endpoint),
                            Reasons = i.LinuxCompatibility.Reasons,
                        })
                        .ToList(),
                },
                Invocations = invocations,
                Warnings = warnings,
            });
        }

        return results;
    }

    /// <summary>
    /// Stamps project path, verdict and id, merges duplicates and sorts —
    /// incompatible first (Part D: the list someone will act on), unused last. The id is
    /// sha256 over repository, project, mechanism, normalised endpoint and
    /// the detector's identity (the SOAP contract, the connection-string
    /// name), truncated to 32 hex digits: stable across rescans. The same
    /// dependency reached from several call sites is one invocation with
    /// every call site.
    /// </summary>
    public static IReadOnlyList<Invocation> Finish(Guid repositoryId, string projectPath, IReadOnlyList<Detected> detected)
    {
        var merged = detected
            .Select(d => (Key: $"{repositoryId:D}\n{projectPath}\n{d.Record.Mechanism}\n{Endpoints.Key(d.Record.Endpoint)}\n{d.Identity}", d.Record))
            .GroupBy(x => x.Key, StringComparer.Ordinal)
            .Select(g => Merge(Hash(g.Key), projectPath, g.Select(x => x.Record).ToList()))
            .ToList();

        return merged
            .OrderBy(i => i.Usage == Usages.Used ? 0 : 1)
            .ThenBy(i => Verdicts.Rank(i.LinuxCompatibility.Verdict))
            .ThenBy(i => i.Mechanism, StringComparer.Ordinal)
            .ThenBy(i => Endpoints.Display(i.Endpoint), StringComparer.Ordinal)
            .ThenBy(i => i.InvocationId, StringComparer.Ordinal)
            .ToList();
    }

    private static Invocation Merge(string id, string projectPath, IReadOnlyList<Invocation> records)
    {
        var ordered = records
            .OrderBy(r => r.CallSites.FirstOrDefault()?.FilePath ?? "", StringComparer.Ordinal)
            .ThenBy(r => r.CallSites.FirstOrDefault()?.LineStart ?? 0)
            .ToList();
        var first = ordered[0];
        var merged = first with
        {
            InvocationId = id,
            ProjectPath = projectPath,
            EnvironmentBindings = ordered.SelectMany(r => r.EnvironmentBindings)
                .DistinctBy(b => (b.Environment, b.SourceFile, b.KeyPath))
                .OrderBy(b => b.Environment == "default" ? 0 : 1).ThenBy(b => b.Environment, StringComparer.Ordinal)
                .ThenBy(b => b.SourceFile, StringComparer.Ordinal).ThenBy(b => b.KeyPath, StringComparer.Ordinal)
                .ToList(),
            Credentials = ordered.SelectMany(r => r.Credentials)
                .DistinctBy(c => (c.Kind, c.KeyPath, c.SourceFile))
                .OrderBy(c => c.Kind, StringComparer.Ordinal).ThenBy(c => c.KeyPath ?? "", StringComparer.Ordinal)
                .ThenBy(c => c.DeclaredAt ?? "", StringComparer.Ordinal)
                .ToList(),
            CallSites = ordered.SelectMany(r => r.CallSites)
                .DistinctBy(c => (c.FilePath, c.LineStart))
                .OrderBy(c => c.FilePath, StringComparer.Ordinal).ThenBy(c => c.LineStart)
                .ToList(),
            Confidence = ordered.Max(r => r.Confidence),
            ConfidenceReasons = ordered.SelectMany(r => r.ConfidenceReasons).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList(),
            // Several call sites under different conditions: none applies to all.
            Soap = first.Soap is null ? null
                : ordered.Select(r => r.Soap?.Condition).Distinct().Count() == 1 ? first.Soap : first.Soap with { Condition = null },
        };

        // A credential makes the declaration: declared wins across call sites.
        if (ordered.Any(r => r.AuthDeclared == AuthDeclared.Declared))
        {
            merged = merged with { AuthDeclared = AuthDeclared.Declared };
        }

        // Used anywhere is used.
        merged = merged with { Usage = ordered.Any(r => r.Usage == Usages.Used) ? Usages.Used : Usages.Unused };
        return LinuxVerdicts.Apply(merged);
    }

    public static string Hash(string key) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(key)))[..32];

    private static ProjectInvocations Empty(OutboundInputProject project, string status, string? skipReason, IReadOnlyList<Warning> warnings) => new()
    {
        ProjectId = project.ProjectId,
        ProjectPath = project.RelativePath,
        Status = status,
        SkipReason = skipReason,
        Summary = new ProjectOutboundSummary(),
        Warnings = warnings,
    };

    private static OutboundSummary Summarise(IReadOnlyList<ProjectInvocations> projects)
    {
        var invocations = projects.SelectMany(p => p.Invocations).ToList();
        var used = invocations.Where(i => i.Usage == Usages.Used).ToList();
        return new OutboundSummary
        {
            ProjectsScanned = projects.Count(p => p.Status == ProjectScanStatuses.Scanned),
            ProjectsSkipped = projects.Count(p => p.Status == ProjectScanStatuses.Skipped),
            ProjectsFailed = projects.Count(p => p.Status == ProjectScanStatuses.Failed),
            InvocationCount = invocations.Count,
            UnusedCount = invocations.Count - used.Count,
            CountByMechanism = Count(used.Select(i => i.Mechanism)),
            CountByVerdict = Count(used.Select(i => i.LinuxCompatibility.Verdict)),
        };
    }

    private static SortedDictionary<string, int> Count(IEnumerable<string> values)
    {
        var counts = new SortedDictionary<string, int>(StringComparer.Ordinal);
        foreach (var value in values)
        {
            counts[value] = counts.GetValueOrDefault(value) + 1;
        }

        return counts;
    }
}
