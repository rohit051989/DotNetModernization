using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using NuGet.Frameworks;
using NuGet.Versioning;

namespace Fingerprinting.Dependencies;

public sealed record DependencyOptions(
    string TargetFramework,
    bool ComparePublicFeed = true,
    bool IncludeTransitive = false,
    string PublicFeedSource = FeedResolver.NuGetOrgV3);

/// <summary>One project as the step receives it: step 2's path, framework
/// and direct packages, the database id, and step 3's skip verdict.</summary>
public sealed record DependencyInputProject(
    string RelativePath, Guid ProjectId, string? SkipReason, string? CurrentFramework, IReadOnlyList<InputPackage> Packages);

public sealed record DependencyInput(
    Guid RepositoryId, string RepositorySlug, string SkipSource, IReadOnlyList<DependencyInputProject> Projects, IReadOnlyList<Warning> Warnings);

/// <summary>
/// Builds the dependency-assessment@1.1.0 artifact for one repository —
/// 30-STEP-006-DEPENDENCY-ASSESSMENT.md Parts B to D. Read-only against the
/// repository (Part B5): direct dependencies come from step 2, packages are
/// fetched into a cache outside it, and transitive resolution, when enabled,
/// restores a scratch copy. Deterministic against the lookup cache (Part B6).
/// </summary>
public sealed class DependencyPipeline(PackageLookup lookup, DependencyOptions options, TransitiveResolver? transitive = null)
{
    /// <summary>Matches the dependency-assessment step registration version.</summary>
    public const string ScannerVersion = "1.1.0";

    /// <summary>The producer name its signals are registered under (Part D1).</summary>
    public const string Extractor = "DependencyAssessment";

    private const int MaxVersionsExamined = 40;

    private readonly NuGetFramework _target = NuGetFramework.Parse(options.TargetFramework);
    private readonly Dictionary<string, IReadOnlyDictionary<string, ApiType>?> _surfaces = new(StringComparer.Ordinal);

    public async Task<DependencyAssessmentArtifact> RunAsync(DependencyInput input, string repositoryRoot, CancellationToken ct)
    {
        var results = new List<ProjectDependencies>();
        foreach (var project in input.Projects.OrderBy(p => p.RelativePath, StringComparer.Ordinal))
        {
            ct.ThrowIfCancellationRequested();
            results.Add(await AssessProjectAsync(input.RepositoryId, repositoryRoot, project, ct));
        }

        // Version drift (1.1.0): one package id at more than one version across
        // the repository's projects. A finding of its own — consolidating is
        // usually the sensible first step before an upgrade.
        var drifting = results.SelectMany(p => p.Packages)
            .Where(p => p.CurrentVersion is not null)
            .GroupBy(p => p.PackageId, StringComparer.OrdinalIgnoreCase)
            .Where(g => g.Select(p => p.CurrentVersion).Distinct(StringComparer.OrdinalIgnoreCase).Count() > 1)
            .Select(g => g.Key)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        results = results.Select(r => r with
        {
            Packages = r.Packages.Select(p => drifting.Contains(p.PackageId) ? p with { VersionDrift = true } : p).ToList(),
        }).ToList();

        var packages = results.SelectMany(p => p.Packages).ToList();
        return new DependencyAssessmentArtifact
        {
            ScannerVersion = ScannerVersion,
            RepositoryId = input.RepositoryId,
            RepositorySlug = input.RepositorySlug,
            TargetFramework = _target.GetShortFolderName(),
            ComparePublicFeed = options.ComparePublicFeed,
            IncludeTransitive = options.IncludeTransitive,
            SkipSource = input.SkipSource,
            Summary = new DependencySummary
            {
                ProjectsScanned = results.Count(r => r.Status == ProjectScanStatuses.Scanned),
                ProjectsSkipped = results.Count(r => r.Status == ProjectScanStatuses.Skipped),
                ProjectsFailed = results.Count(r => r.Status == ProjectScanStatuses.Failed),
                PackageCount = packages.Count,
                CountByOutcome = Count(packages.Select(p => p.Outcome)),
                CountByFeedSource = Count(packages.Select(p => p.FeedSource ?? "none")),
                DeprecatedCount = packages.Count(p => p.Deprecated is not null),
                VulnerableCount = packages.Count(p => p.Vulnerable is not null),
                NotInClientFeedCount = packages.Count(p => p.NotInClientFeed is not null),
                VersionDriftCount = drifting.Count,
                ContentBreakingPossibleCount = packages.Count(p => p.ContentBreakingPossible),
            },
            Projects = results,
            Warnings = input.Warnings.OrderBy(w => w.Message, StringComparer.Ordinal).ToList(),
        };
    }

    private async Task<ProjectDependencies> AssessProjectAsync(Guid repositoryId, string repositoryRoot, DependencyInputProject project, CancellationToken ct)
    {
        if (project.SkipReason is not null)
        {
            return Empty(project, ProjectScanStatuses.Skipped, project.SkipReason, []);
        }

        var projectFile = Path.Combine(repositoryRoot, project.RelativePath.Replace('/', Path.DirectorySeparatorChar));
        var projectDirectory = Path.GetDirectoryName(projectFile)!;
        if (!Directory.Exists(projectDirectory))
        {
            return Empty(project, ProjectScanStatuses.Failed, null,
                [new Warning { Code = WarningCodes.ProjectDirectoryNotFound, Message = $"Project directory not found on disk: {project.RelativePath}", Severity = WarningSeverities.Warning }]);
        }

        var feeds = FeedResolver.Resolve(repositoryRoot, projectDirectory, options.ComparePublicFeed, options.PublicFeedSource);
        var declarations = PackageDeclarations.Read(repositoryRoot, project.RelativePath, project.Packages);
        // Step 2's answer, including a framework set in Directory.*.props
        // (solution-project-inventory 2.1.0): one answer for every step.
        var current = ParseFramework(project.CurrentFramework);
        ProjectSource? source = null;

        var assessments = new List<PackageAssessment>();
        var signals = new List<Signal>();
        foreach (var declaration in declarations)
        {
            var (assessment, emitted) = await AssessPackageAsync(repositoryId, project, declaration, feeds, current,
                async () => source ??= await ProjectSource.LoadAsync(repositoryRoot, project.RelativePath, [], NoAuxiliaryFiles.Instance, ct), ct);
            assessments.Add(assessment);
            signals.AddRange(emitted);
        }

        IReadOnlyList<TransitivePackage>? transitivePackages = null;
        var warnings = new List<Warning>();
        if (options.IncludeTransitive && transitive is not null)
        {
            var resolved = await transitive.ResolveAsync(repositoryRoot, project.RelativePath, ct);
            if (resolved.Error is not null)
            {
                warnings.Add(new Warning { Code = "TRANSITIVE_RESOLUTION_FAILED", Message = resolved.Error, Severity = WarningSeverities.Warning });
            }
            else
            {
                var direct = declarations.Select(d => d.PackageId).ToHashSet(StringComparer.OrdinalIgnoreCase);
                var list = new List<TransitivePackage>();
                foreach (var (id, version) in resolved.Packages.Where(p => !direct.Contains(p.Id)).OrderBy(p => p.Id, StringComparer.OrdinalIgnoreCase))
                {
                    list.Add(new TransitivePackage { PackageId = id, Version = version, Vulnerable = await TransitiveVulnerabilityAsync(feeds, id, version, ct) });
                }

                transitivePackages = list;
            }
        }

        var ordered = assessments.OrderBy(a => a.PackageId, StringComparer.OrdinalIgnoreCase).ToList();
        return new ProjectDependencies
        {
            ProjectId = project.ProjectId,
            ProjectPath = project.RelativePath,
            Status = ProjectScanStatuses.Scanned,
            CurrentFramework = current?.GetShortFolderName(),
            Feeds = feeds.All.Select(f => f.ToRecord()).Concat(feeds.Public is { } p && !feeds.All.Contains(p) ? [p.ToRecord() with { Role = "public_comparison" }] : []).ToList(),
            Summary = new ProjectDependencySummary
            {
                CountByOutcome = Count(ordered.Select(a => a.Outcome)),
                DeprecatedCount = ordered.Count(a => a.Deprecated is not null),
                VulnerableCount = ordered.Count(a => a.Vulnerable is not null),
                NotInClientFeedCount = ordered.Count(a => a.NotInClientFeed is not null),
            },
            Packages = ordered,
            Transitive = transitivePackages,
            Signals = signals
                .OrderBy(s => s.Name, StringComparer.Ordinal)
                .ThenBy(s => s.SourcePath, StringComparer.Ordinal)
                .ThenBy(s => s.Value, StringComparer.Ordinal)
                .ToList(),
            Warnings = warnings,
        };
    }

    // ---------- one package ----------

    private sealed record Candidate(NuGetVersion Version, Feed Feed, CacheEntry Entry, CachedVersion Cached);

    private async Task<(PackageAssessment, IReadOnlyList<Signal>)> AssessPackageAsync(
        Guid repositoryId, DependencyInputProject project, PackageDeclaration declaration, FeedSet feeds, NuGetFramework? currentFramework,
        Func<Task<ProjectSource>> loadSource, CancellationToken ct)
    {
        var id = Hash($"{repositoryId:D}\n{project.RelativePath}\n{declaration.PackageId.ToLowerInvariant()}");
        var reasons = new List<string>();
        PackageAssessment Result(string outcome, string? reason, double confidence) => new()
        {
            AssessmentId = id,
            PackageId = declaration.PackageId,
            CurrentVersion = declaration.Version?.ToNormalizedString() ?? declaration.VersionText,
            VersionSource = declaration.VersionSource,
            DeclaredAt = declaration.DeclaredAt,
            Outcome = outcome,
            OutcomeReason = reason,
            Confidence = confidence,
            ConfidenceReasons = reasons,
        };

        if (declaration.Version is null)
        {
            return (Result(Outcomes.Unknown, declaration.Problem, 0.0), []);
        }

        var currentVersion = declaration.Version;

        // ---- the authoritative feeds (Part B2). Every one must answer: a
        // client feed that cannot be reached could hold a newer version, so
        // its silence is "unknown", never a quiet substitution (Part B7).
        var candidates = new List<Candidate>();
        var errors = new List<string>();
        foreach (var feed in feeds.Authorities)
        {
            var result = await lookup.GetAsync(feed, declaration.PackageId, ct);
            if (!result.Reachable)
            {
                errors.Add(result.Error!);
                continue;
            }

            foreach (var cached in result.Entry!.Versions.Where(v => v.Listed))
            {
                var version = NuGetVersion.Parse(cached.Version);
                if (candidates.All(c => c.Version != version)) candidates.Add(new Candidate(version, feed, result.Entry, cached));
            }
        }

        // ---- the public comparison (Part B3), client feeds only.
        IReadOnlyList<Candidate> publicCandidates = [];
        if (feeds.Public is { } publicFeed)
        {
            var result = await lookup.GetAsync(publicFeed, declaration.PackageId, ct);
            if (result.Reachable)
            {
                publicCandidates = result.Entry!.Versions.Where(v => v.Listed)
                    .Select(v => new Candidate(NuGetVersion.Parse(v.Version), publicFeed, result.Entry, v)).ToList();
            }
            else
            {
                reasons.Add("public comparison skipped: nuget.org could not be reached");
            }
        }

        var allowPrerelease = currentVersion.IsPrerelease;
        var ordered = candidates.Where(c => allowPrerelease || !c.Version.IsPrerelease).OrderByDescending(c => c.Version).ToList();
        var latest = ordered.FirstOrDefault();
        var currentCandidate = candidates.FirstOrDefault(c => c.Version == currentVersion);

        if (errors.Count > 0)
        {
            return (Result(Outcomes.Unknown, string.Join("; ", errors), 0.0) with { FeedSource = SourceOf(feeds) }, []);
        }

        if (ordered.Count == 0)
        {
            var gap = await PublicGapAsync(publicCandidates, allowPrerelease, null, feeds, ct);
            var where = string.Join(", ", feeds.Authorities.Select(f => f.Name));
            var assessment = Result(Outcomes.Unknown, $"{declaration.PackageId} is not on {(feeds.UsingClientFeeds ? "the client feed(s)" : "nuget.org")}: {where}", 0.0)
                with { FeedSource = SourceOf(feeds), NotInClientFeed = gap };
            return (assessment, Signals(declaration, assessment, null));
        }

        // ---- the recommended version: the newest that supports the target (Part C2).
        var (recommended, examined) = await NewestCompatibleAsync(ordered, ct);
        var deprecated = Deprecation(currentCandidate);
        var vulnerable = Vulnerability(currentCandidate, recommended);
        var answering = recommended ?? currentCandidate ?? latest!;
        var common = new
        {
            Recommended = recommended?.Version.ToNormalizedString(),
            Latest = latest!.Version.ToNormalizedString(),
            FeedSource = SourceOf(feeds),
            FeedName = answering.Feed.Name,
            FeedUrl = answering.Feed.Url,
        };
        var gapFlag = feeds.UsingClientFeeds ? await PublicGapAsync(publicCandidates, allowPrerelease, recommended?.Version, feeds, ct) : null;

        // The kind of what is installed today: the current version's contents,
        // or the nearest readable version when the current one is not on the feed.
        var kindSource = currentCandidate ?? recommended ?? latest!;
        var kind = await lookup.KindAsync(kindSource.Feed, kindSource.Entry, kindSource.Cached, ct);

        PackageAssessment Finish(PackageAssessment a) => a with
        {
            PackageKind = kind,
            RecommendedVersion = common.Recommended,
            LatestVersion = common.Latest,
            FeedSource = common.FeedSource,
            FeedName = common.FeedName,
            FeedUrl = common.FeedUrl,
            Deprecated = deprecated,
            Vulnerable = vulnerable,
            NotInClientFeed = gapFlag,
        };

        if (recommended is null)
        {
            var reason = examined < ordered.Count
                ? $"no version among the newest {examined} supports {_target.GetShortFolderName()} (latest {common.Latest})"
                : $"no version supports {_target.GetShortFolderName()} (latest {common.Latest})";
            var assessment = Finish(Result(Outcomes.NoCompatibleVersion, reason, 0.9));
            return (assessment, Signals(declaration, assessment, null));
        }

        if (recommended.Version < currentVersion)
        {
            var assessment = Finish(Result(Outcomes.NoCompatibleVersion,
                $"{currentVersion} does not support {_target.GetShortFolderName()}; only older versions do (newest {recommended.Version})", 0.8));
            return (assessment, Signals(declaration, assessment, null));
        }

        if (recommended.Version == currentVersion)
        {
            var assessment = Finish(Result(Outcomes.Current, null, 1.0));
            return (assessment, Signals(declaration, assessment, null));
        }

        // ---- safe or breaking (Part C4): semver first, the API diff over it.
        var semver = recommended.Version.Major != currentVersion.Major ? "major"
            : recommended.Version.Minor != currentVersion.Minor ? "minor" : "patch";
        var heuristic = semver == "major" ? Outcomes.UpgradeBreaking : Outcomes.UpgradeSafe;

        // Build, tools, analyzer and content packages put no compile-time
        // assembly into the project, so no C# call site can break: whatever
        // the version jump, they are safe for this step's purposes. A content
        // package's major version can still break markup or CSS, which the
        // call-site model cannot see — flagged, but kept out of breaking.
        if (kind is not null && kind != PackageKinds.Runtime)
        {
            var contentRisk = kind == PackageKinds.Content && semver == "major";
            reasons.Add($"{kind} package: no lib/ or ref/ assemblies, so no C# call site to break");
            if (contentRisk) reasons.Add("content package, major version: markup and CSS may break; not analysed by this step");
            // A meta-package (Swashbuckle.AspNetCore: a props file and
            // dependencies) carries its API in packages it pulls in. Those are
            // transitive, not direct references, and are not diffed here.
            if (kindSource.Cached.DependencyFrameworks.Count > 0)
                reasons.Add("declares package dependencies; any API it brings lives in those, which are not direct references and are not diffed");
            var assessment = Finish(Result(Outcomes.UpgradeSafe,
                contentRisk
                    ? $"{semver} version change of a content package; may break markup or CSS (not analysed)"
                    : $"{semver} version change of a {kind} package; no compile-time assemblies",
                0.8))
                with { ClassificationMethod = ClassificationMethods.PackageKind, SemverChange = semver, ContentBreakingPossible = contentRisk };
            return (assessment, Signals(declaration, assessment, null));
        }

        var diff = await DiffAsync(currentCandidate, recommended, currentFramework, ct);
        if (diff is null)
        {
            reasons.Add(currentCandidate is null
                ? $"{currentVersion} is not on the feed, so its assemblies could not be compared; semver decides"
                : "no comparable assemblies in one of the versions; semver decides");
            var assessment = Finish(Result(heuristic, $"{semver} version change ({currentVersion} -> {recommended.Version}), presumed {(semver == "major" ? "breaking" : "safe")}", 0.5))
                with
                {
                    ClassificationMethod = ClassificationMethods.SemverHeuristic,
                    SemverChange = semver,
                    BreakingEvidence = heuristic == Outcomes.UpgradeBreaking ? BreakingEvidence.SemverPresumed : null,
                };
            return (assessment, Signals(declaration, assessment, null));
        }

        var hits = CallSiteFinder.Find(await loadSource(), diff.Value.Changes);
        var summary = new ApiDiffSummary
        {
            RemovedTypes = diff.Value.Changes.Count(c => c.Change == "type_removed"),
            RemovedMembers = diff.Value.Changes.Count(c => c.Change == "member_removed"),
            ChangedSignatures = diff.Value.Changes.Count(c => c.Change == "signature_changed"),
            CurrentAssemblies = diff.Value.CurrentGroup,
            RecommendedAssemblies = diff.Value.RecommendedGroup,
        };

        if (hits.Count == 0)
        {
            reasons.Add(semver == "major"
                ? "major version, but the API diff shows nothing the code calls changed: the diff overrides the heuristic"
                : "no call to a changed member found");
            var assessment = Finish(Result(Outcomes.UpgradeSafe, $"{semver} version change; nothing the code calls changed", 0.85))
                with { ClassificationMethod = ClassificationMethods.ApiDiff, SemverChange = semver, ApiDiff = summary };
            return (assessment, Signals(declaration, assessment, null));
        }

        reasons.Add("call sites found by syntax search guarded by the package's namespaces");
        if (semver != "major") reasons.Add($"{semver} version, but the API diff hits a call site: the diff overrides the heuristic");
        var allSites = hits.SelectMany(h => h.Sites).ToList();
        var confirmed = allSites.Count(s => s.Certainty == CallSiteCertainty.Confirmed);
        var ambiguousOnly = confirmed == 0;
        if (ambiguousOnly) reasons.Add("every call site could bind to an unchanged overload; syntax cannot tell which");
        var breaking = Finish(Result(Outcomes.UpgradeBreaking,
            ambiguousOnly
                ? $"possibly breaking: {allSites.Count} call site(s) may bind to a changed overload of {hits.Count} member(s), but an unchanged overload accepts the same arguments; no confirmed call site ({currentVersion} -> {recommended.Version})"
                : $"{hits.Count} changed member(s) the code calls, {confirmed} confirmed call site(s) ({currentVersion} -> {recommended.Version})",
            ambiguousOnly ? CallSiteFinder.AmbiguousConfidence : CallSiteFinder.Confidence))
            with
            {
                ClassificationMethod = ClassificationMethods.ApiDiff,
                SemverChange = semver,
                ApiDiff = summary,
                BreakingEvidence = ambiguousOnly ? BreakingEvidence.AmbiguousCallSitesOnly : BreakingEvidence.ConfirmedCallSites,
                BreakingMembers = hits.Select(h => new BreakingMember
                {
                    Change = h.Change.Change,
                    Type = h.Change.Type.FullName,
                    Member = h.Change.Member,
                    OldSignature = h.Change.OldSignature,
                    NewSignatures = h.Change.NewSignatures,
                }).OrderBy(m => m.Type, StringComparer.Ordinal).ThenBy(m => m.Member ?? "", StringComparer.Ordinal).ThenBy(m => m.OldSignature ?? "", StringComparer.Ordinal).ToList(),
                CallSites = allSites.OrderBy(s => s.Certainty == CallSiteCertainty.Confirmed ? 0 : 1).DistinctBy(s => (s.FilePath, s.LineStart, s.Member))
                    .OrderBy(s => s.FilePath, StringComparer.Ordinal).ThenBy(s => s.LineStart).ThenBy(s => s.Member, StringComparer.Ordinal).ToList(),
            };
        return (breaking, Signals(declaration, breaking, breaking.CallSites));
    }

    private static string SourceOf(FeedSet feeds) => feeds.UsingClientFeeds ? FeedSources.ClientFeed : FeedSources.NuGetOrgFallback;

    /// <summary>Walks versions newest first until one supports the target.</summary>
    private async Task<(Candidate? Compatible, int Examined)> NewestCompatibleAsync(IReadOnlyList<Candidate> ordered, CancellationToken ct)
    {
        var examined = 0;
        foreach (var candidate in ordered.Take(MaxVersionsExamined))
        {
            examined++;
            var frameworks = await lookup.FrameworksAsync(candidate.Feed, candidate.Entry, candidate.Cached, ct);
            if (frameworks is not null && Supports(frameworks)) return (candidate, examined);
            // Second opinion from lib/ref, for the newest version only — that
            // bounds the downloads for a package that genuinely does not fit.
            if (examined > 1 || candidate.Cached.DependencyFrameworks.Count == 0) continue;
            var assets = await lookup.AssetFrameworksAsync(candidate.Feed, candidate.Entry, candidate.Cached, ct);
            if (assets is not null && Supports(assets)) return (candidate, examined);
        }

        return (null, examined);
    }

    /// <summary>No frameworks at all (content, tools, a meta-package) is
    /// framework-neutral; otherwise one group must be compatible with the target.</summary>
    private bool Supports(IReadOnlyList<NuGetFramework> frameworks) =>
        frameworks.Count == 0 || frameworks.Any(f => f.IsAny || f.IsAgnostic || DefaultCompatibilityProvider.Instance.IsCompatible(_target, f));

    private async Task<ClientFeedGap?> PublicGapAsync(IReadOnlyList<Candidate> publicCandidates, bool allowPrerelease, NuGetVersion? inClient, FeedSet feeds, CancellationToken ct)
    {
        if (publicCandidates.Count == 0) return null;
        var ordered = publicCandidates.Where(c => allowPrerelease || !c.Version.IsPrerelease).OrderByDescending(c => c.Version).ToList();
        var (newestPublic, _) = await NewestCompatibleAsync(ordered, ct);
        if (newestPublic is null || (inClient is not null && newestPublic.Version <= inClient)) return null;
        return new ClientFeedGap
        {
            LatestPublicVersion = newestPublic.Version.ToNormalizedString(),
            LatestInClientFeed = inClient?.ToNormalizedString(),
            ClientFeedName = string.Join(", ", feeds.Authorities.Select(f => f.Name)),
        };
    }

    private static DeprecationFlag? Deprecation(Candidate? current) =>
        current?.Cached.Deprecation is { } d
            ? new DeprecationFlag { Reasons = d.Reasons, Message = d.Message, ReplacementId = d.AlternateId, ReplacementRange = d.AlternateRange }
            : null;

    private static readonly string[] SeverityNames = ["low", "moderate", "high", "critical"];

    private static VulnerabilityFlag? Vulnerability(Candidate? current, Candidate? recommended)
    {
        if (current is null || current.Cached.Vulnerabilities.Count == 0) return null;
        var max = current.Cached.Vulnerabilities.Max(v => v.Severity);
        return new VulnerabilityFlag
        {
            MaxSeverity = SeverityNames[Math.Clamp(max, 0, 3)],
            Advisories = current.Cached.Vulnerabilities.Select(v => new Advisory { Severity = SeverityNames[Math.Clamp(v.Severity, 0, 3)], Url = v.AdvisoryUrl }).ToList(),
            ResolvedByUpgrade = recommended is null || recommended.Version == current.Version ? null : recommended.Cached.Vulnerabilities.Count == 0,
        };
    }

    private async Task<VulnerabilityFlag?> TransitiveVulnerabilityAsync(FeedSet feeds, string id, string version, CancellationToken ct)
    {
        foreach (var feed in feeds.Authorities)
        {
            var result = await lookup.GetAsync(feed, id, ct);
            var cached = result.Entry?.Versions.FirstOrDefault(v => NuGetVersion.Parse(v.Version) == NuGetVersion.Parse(version));
            if (cached is not null)
            {
                return Vulnerability(new Candidate(NuGetVersion.Parse(cached.Version), feed, result.Entry!, cached), null);
            }
        }

        return null;
    }

    // ---------- the API diff ----------

    private async Task<(IReadOnlyList<ApiChange> Changes, string CurrentGroup, string RecommendedGroup)?> DiffAsync(
        Candidate? current, Candidate recommended, NuGetFramework? currentFramework, CancellationToken ct)
    {
        if (current is null) return null;
        // Unknown current framework: read the current version for the target
        // instead — the nearest real guess — never whichever folder sorts highest.
        var before = await SurfaceAsync(current, currentFramework ?? _target, ct);
        var after = await SurfaceAsync(recommended, _target, ct);
        if (before is null || after is null) return null;
        return (ApiSurface.Compare(before.Value.Types, after.Value.Types), before.Value.Group, after.Value.Group);
    }

    /// <summary>The public surface of a version's lib (or ref) assemblies
    /// for the framework nearest to <paramref name="framework"/>, extracted
    /// into the package cache — never next to a project.</summary>
    private async Task<(IReadOnlyDictionary<string, ApiType> Types, string Group)?> SurfaceAsync(Candidate candidate, NuGetFramework? framework, CancellationToken ct)
    {
        var path = await lookup.DownloadAsync(candidate.Feed, candidate.Entry.PackageId, candidate.Cached.Version, ct);
        if (path is null) return null;

        using var archive = ZipFile.OpenRead(path);
        var groups = archive.Entries
            .Where(e => e.FullName.EndsWith(".dll", StringComparison.OrdinalIgnoreCase)
                        && (e.FullName.StartsWith("lib/", StringComparison.OrdinalIgnoreCase) || e.FullName.StartsWith("ref/", StringComparison.OrdinalIgnoreCase)))
            .GroupBy(e => string.Join('/', e.FullName.Split('/').Take(2)), StringComparer.OrdinalIgnoreCase)
            .ToDictionary(g => g.Key, g => g.ToList(), StringComparer.OrdinalIgnoreCase);
        if (groups.Count == 0) return null;

        // Prefer lib/ (what runs); fall back to ref/.
        var byFramework = groups.Keys
            .Select(k => (Key: k, Framework: NuGetFramework.ParseFolder(k.Split('/')[1])))
            .Where(x => !x.Framework.IsUnsupported)
            .OrderBy(x => x.Key.StartsWith("lib/", StringComparison.OrdinalIgnoreCase) ? 0 : 1)
            .ToList();
        var reducer = new FrameworkReducer();
        NuGetFramework? nearest = framework is null ? null : reducer.GetNearest(framework, byFramework.Select(x => x.Framework).Distinct());
        var chosen = nearest is null
            ? byFramework.OrderByDescending(x => x.Framework, NuGetFrameworkSorter.Instance).FirstOrDefault()
            : byFramework.FirstOrDefault(x => x.Framework.Equals(nearest));
        if (chosen.Key is null) return null;

        var cacheKey = $"{path}|{chosen.Key}";
        if (!_surfaces.TryGetValue(cacheKey, out var types))
        {
            var directory = Path.Combine(Path.GetDirectoryName(path)!, "extracted", chosen.Key.Replace('/', '_'));
            Directory.CreateDirectory(directory);
            var files = new List<string>();
            foreach (var entry in groups[chosen.Key].OrderBy(e => e.FullName, StringComparer.Ordinal))
            {
                var target = Path.Combine(directory, entry.Name);
                if (!File.Exists(target)) entry.ExtractToFile(target, overwrite: true);
                files.Add(target);
            }

            try
            {
                types = ApiSurface.Read(files);
            }
            catch (BadImageFormatException)
            {
                types = null;
            }

            _surfaces[cacheKey] = types;
        }

        return types is null ? null : (types, $"{candidate.Version.ToNormalizedString()} {chosen.Key}");
    }

    // ---------- signals (Part D1) ----------

    private static IReadOnlyList<Signal> Signals(PackageDeclaration declaration, PackageAssessment assessment, IReadOnlyList<CallSite>? callSites)
    {
        var signals = new List<Signal>();
        var from = assessment.CurrentVersion;
        var to = assessment.RecommendedVersion;
        Signal AtDeclaration(string name, string value) => new()
        {
            Name = name,
            Category = "PACKAGE_DEPENDENCY",
            Type = "PACKAGE",
            Value = value,
            SourceType = "PACKAGE_REFERENCE",
            SourcePath = declaration.DeclaredAt.FilePath,
            EvidenceKind = "FILE",
            OccurrenceCount = 1,
            Evidence = [new Evidence { LineStart = declaration.DeclaredAt.Line, LineEnd = declaration.DeclaredAt.Line }],
            Extractor = Extractor,
            ExtractionConfidence = (decimal)Math.Round(Math.Max(assessment.Confidence, 0.5), 2),
        };

        switch (assessment.Outcome)
        {
            case Outcomes.UpgradeSafe:
                signals.Add(AtDeclaration("PACKAGE_UPGRADE_SAFE", $"{assessment.PackageId} {from} -> {to}"));
                break;
            case Outcomes.NoCompatibleVersion:
                signals.Add(AtDeclaration("PACKAGE_NO_COMPATIBLE_VERSION", $"{assessment.PackageId} {from}"));
                break;
            case Outcomes.UpgradeBreaking when callSites is { Count: > 0 }:
                // One signal per file and member, its evidence every call site there.
                foreach (var group in callSites.GroupBy(s => (s.FilePath, s.Member)).OrderBy(g => g.Key.FilePath, StringComparer.Ordinal).ThenBy(g => g.Key.Member, StringComparer.Ordinal))
                {
                    signals.Add(new Signal
                    {
                        Name = "PACKAGE_UPGRADE_BREAKING",
                        Category = "PACKAGE_DEPENDENCY",
                        Type = "API_INVOCATION",
                        Value = $"{assessment.PackageId} {from} -> {to}: {group.Key.Member}",
                        SourceType = "SOURCE_CODE",
                        SourcePath = group.Key.FilePath,
                        EvidenceKind = "FILE",
                        OccurrenceCount = group.Count(),
                        // Confirmed sites first, so the 20-entry cap never drops one in favour of an ambiguous site.
                        Evidence = group.OrderBy(s => s.Certainty == CallSiteCertainty.Confirmed ? 0 : 1).ThenBy(s => s.LineStart).Take(20)
                            .OrderBy(s => s.LineStart)
                            .Select(s => new Evidence { LineStart = s.LineStart, LineEnd = s.LineEnd, Certainty = s.Certainty }).ToList(),
                        Extractor = Extractor,
                        ExtractionConfidence = (decimal)(group.Any(s => s.Certainty == CallSiteCertainty.Confirmed) ? CallSiteFinder.Confidence : CallSiteFinder.AmbiguousConfidence),
                    });
                }

                break;
            case Outcomes.UpgradeBreaking:
                // Semver presumes breaking but the assemblies could not be
                // compared, so no call site is known: the finding sits at the
                // reference, the one place known to change.
                signals.Add(AtDeclaration("PACKAGE_UPGRADE_BREAKING", $"{assessment.PackageId} {from} -> {to}: (major version; call sites not determined)")
                    with { Type = "API_INVOCATION" });
                break;
        }

        if (assessment.Deprecated is { } deprecated)
        {
            var replacement = deprecated.ReplacementId is null ? "no suggested replacement" : $"replacement {deprecated.ReplacementId}{(deprecated.ReplacementRange is null ? "" : " " + deprecated.ReplacementRange)}";
            signals.Add(AtDeclaration("PACKAGE_DEPRECATED", $"{assessment.PackageId} {from}: {replacement}"));
        }

        if (assessment.Vulnerable is { } vulnerable)
        {
            signals.Add(AtDeclaration("PACKAGE_VULNERABLE", $"{assessment.PackageId} {from}: {vulnerable.MaxSeverity}"));
        }

        if (assessment.NotInClientFeed is { } gap)
        {
            signals.Add(AtDeclaration("PACKAGE_NOT_IN_CLIENT_FEED",
                $"{assessment.PackageId}: latest public compatible {gap.LatestPublicVersion}, latest in {gap.ClientFeedName} {gap.LatestInClientFeed ?? "none"}"));
        }

        return signals;
    }

    // ---------- helpers ----------

    /// <summary>step 2's framework: <c>net8.0</c>, <c>net472</c>, <c>v4.7.2</c>.</summary>
    public static NuGetFramework? ParseFramework(string? text)
    {
        if (string.IsNullOrWhiteSpace(text)) return null;
        var trimmed = text.Trim();
        if (trimmed.StartsWith('v') && Version.TryParse(trimmed[1..], out var legacy))
        {
            return new NuGetFramework(FrameworkConstants.FrameworkIdentifiers.Net, legacy);
        }

        var framework = NuGetFramework.Parse(trimmed.Split(';')[0]);
        return framework.IsUnsupported ? null : framework;
    }

    private static ProjectDependencies Empty(DependencyInputProject project, string status, string? skipReason, IReadOnlyList<Warning> warnings) => new()
    {
        ProjectId = project.ProjectId,
        ProjectPath = project.RelativePath,
        Status = status,
        SkipReason = skipReason,
        Summary = new ProjectDependencySummary(),
        Warnings = warnings,
    };

    public static string Hash(string key) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(key)))[..32];

    private static SortedDictionary<string, int> Count(IEnumerable<string> values)
    {
        var counts = new SortedDictionary<string, int>(StringComparer.Ordinal);
        foreach (var value in values) counts[value] = counts.GetValueOrDefault(value) + 1;
        return counts;
    }
}
