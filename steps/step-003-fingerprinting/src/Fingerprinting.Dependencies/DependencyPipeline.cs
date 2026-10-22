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
    string PublicFeedSource = FeedResolver.NuGetOrgV3,
    SharedFrameworks? SharedFrameworks = null);

/// <summary>One project as the step receives it: step 2's path, framework
/// and direct packages, the database id, and step 3's skip verdict.</summary>
public sealed record DependencyInputProject(
    string RelativePath, Guid ProjectId, string? SkipReason, string? CurrentFramework, IReadOnlyList<InputPackage> Packages,
    string? ProjectSdk = null);

public sealed record DependencyInput(
    Guid RepositoryId, string RepositorySlug, string SkipSource, IReadOnlyList<DependencyInputProject> Projects, IReadOnlyList<Warning> Warnings);

/// <summary>
/// Builds the dependency-assessment@1.1.0 artifact for one repository —
/// 30-DEPENDENCY-ASSESSMENT.md Parts B to D. Read-only against the
/// repository (Part B5): direct dependencies come from step 2, packages are
/// fetched into a cache outside it, and transitive resolution, when enabled,
/// restores a scratch copy. Deterministic against the lookup cache (Part B6).
/// </summary>
public sealed class DependencyPipeline(PackageLookup lookup, DependencyOptions options, TransitiveResolver? transitive = null)
{
    /// <summary>Matches the dependency-assessment step registration version. 1.4.1: <c>lookup_offline</c>, answers
    /// from the lookup cache only (PackageLookup). 1.4.2: a local feed's key resolves junctions and links
    /// (FeedResolver.NormaliseUrl). 1.4.3: a version newer than the lookup answers is current
    /// (<see cref="NewerThanLookups"/>). 1.5.0 (artifact 1.5.0): the recommended version never carries a known
    /// advisory (<see cref="WithoutAdvisoryAsync"/>); a vulnerability names the version that fixes it, or says there
    /// is none yet; a retired package's replacement is given a version (<see cref="ReplacementVersionAsync"/>).
    /// 1.6.0 (artifact 1.6.0): feeds resolve as dotnet resolves them — a NuGet.config in a folder above the
    /// repository is recorded as declared in <c>parent</c>, and a local folder declared at user level is a client
    /// feed (<see cref="FeedResolver"/>). 1.7.0 (release 5): each project within a time limit, over which it is
    /// recorded NOT_CHECKED with the reason; a transitive restore over its limit ends with everything it started;
    /// progress, a timing profile, and finished projects kept so a rerun continues from there. Artifact unchanged.
    /// 1.7.1: the step reports its artifact to the engine as 1.6.0, the version it writes; it had reported 1.5.0.
    /// Artifact unchanged.</summary>
    public const string ScannerVersion = "1.7.1";

    /// <summary>1.5.0: the PACKAGE_VULNERABLE value's ending when no release without a known advisory supports the
    /// target.</summary>
    public const string NoFixedRelease = "no release without a known advisory yet";

    /// <summary>1.4.3: the start of the outcome reason for a version newer than every version the lookup answers
    /// know. An engine run looks up live feeds and may take a release published after an experiment's lookups were
    /// frozen: that is an upgrade (outcome current), never unresolved or unknown. The verifier reports these apart,
    /// as "newer than snapshot".</summary>
    public const string NewerThanLookups = "newer than the lookup answers";

    /// <summary>The producer name its signals are registered under (Part D1).</summary>
    public const string Extractor = "DependencyAssessment";

    private const int MaxVersionsExamined = 40;

    private readonly NuGetFramework _target = NuGetFramework.Parse(options.TargetFramework);
    private readonly Dictionary<string, IReadOnlyDictionary<string, ApiType>?> _surfaces = new(StringComparer.Ordinal);

    public async Task<DependencyAssessmentArtifact> RunAsync(DependencyInput input, string repositoryRoot, CancellationToken ct,
        StepProgress? progress = null, WorkLimits? limits = null, ProjectCheckpoints? checkpoints = null)
    {
        progress ??= StepProgress.Silent();
        limits ??= WorkLimits.Default;
        checkpoints ??= ProjectCheckpoints.None;

        // One project at a time: the time goes on package lookups, which the lookup cache shares between projects and
        // a client feed should not see in bursts. Each project has its own time limit, and is saved as it completes so
        // a rerun continues from there (release 5).
        var results = new List<ProjectDependencies>();
        progress.Phase("assess", input.Projects.Count);
        foreach (var project in input.Projects.OrderBy(p => p.RelativePath, StringComparer.Ordinal))
        {
            ct.ThrowIfCancellationRequested();
            using var item = progress.Item(project.RelativePath);
            if (checkpoints.TryGet<ProjectDependencies>(project.RelativePath, out var saved) && saved is not null)
            {
                results.Add(saved);
                continue;
            }

            if (checkpoints.Skipped(project.RelativePath, out var skipped))
            {
                // Not retried: an earlier, interrupted run was stuck on it (release 5).
                progress.RecordNotChecked(project.RelativePath, "project", skipped);
                var notChecked = Empty(project, ProjectScanStatuses.Failed, null,
                    [new Warning { Code = WarningCodes.NotChecked, Message = skipped, Severity = WarningSeverities.Warning }]);
                checkpoints.Save(project.RelativePath, notChecked);
                results.Add(notChecked);
                continue;
            }

            using var limit = CancellationTokenSource.CreateLinkedTokenSource(ct);
            limit.CancelAfter(limits.ProjectLoad);
            ProjectDependencies result;
            try
            {
                result = await AssessProjectAsync(input.RepositoryId, repositoryRoot, project, limit.Token);
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                var reason = $"not checked: assessing the project took longer than {limits.ProjectLoad.TotalSeconds:0} s";
                progress.RecordNotChecked(project.RelativePath, "project", reason);
                result = Empty(project, ProjectScanStatuses.Failed, null,
                    [new Warning { Code = WarningCodes.NotChecked, Message = reason, Severity = WarningSeverities.Warning }]);
            }

            checkpoints.Save(project.RelativePath, result);
            results.Add(result);
        }

        progress.Phase("summarise");

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
        var projectText = File.Exists(projectFile) ? await File.ReadAllTextAsync(projectFile, ct) : null;
        var sharedFrameworks = SharedFrameworks.UsedBy(project.ProjectSdk, projectText);

        var assessments = new List<PackageAssessment>();
        var signals = new List<Signal>();
        if (RetargetSignal(repositoryRoot, project.RelativePath, projectText, current) is { } retarget)
        {
            signals.Add(retarget);
        }

        foreach (var declaration in declarations)
        {
            var (assessment, emitted) = await AssessPackageAsync(repositoryId, project, declaration, feeds, current, sharedFrameworks,
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
        IReadOnlyList<string> sharedFrameworks, Func<Task<ProjectSource>> loadSource, CancellationToken ct)
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

        // ---- provided by the target's shared framework (1.4.0): a removal, decided before any feed lookup.
        var target = _target.GetShortFolderName();
        if (options.SharedFrameworks?.Provider(target, sharedFrameworks, declaration.PackageId, currentVersion) is { } provider)
        {
            var removal = Result(Outcomes.FrameworkProvided,
                $"{declaration.PackageId} {currentVersion.ToNormalizedString()} is provided by the {provider} shared framework on {target}: remove the reference", 1.0);
            return (removal, Signals(declaration, removal, null, $"{provider} {target}"));
        }

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
        var (newestCompatible, examined) = await NewestCompatibleAsync(ordered, ct);
        var recommended = await WithoutAdvisoryAsync(newestCompatible, currentCandidate, ordered, ct);
        var deprecated = Deprecation(currentCandidate, ordered);
        if (deprecated is { Scope: DeprecationScopes.Package, ReplacementId: { } replacementId })
        {
            deprecated = deprecated with { ReplacementVersion = await ReplacementVersionAsync(feeds, replacementId, deprecated.ReplacementRange, ct) };
        }

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

        // The nuspec dependencies of both ends of the upgrade, recorded in the
        // lookup cache whatever its age: the conversion planner orders package
        // units by them, dependencies before dependents.
        foreach (var end in new[] { currentCandidate, recommended }.OfType<Candidate>())
        {
            await lookup.DependenciesAsync(end.Feed, end.Entry, end.Cached, ct);
        }

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

        if (currentCandidate is null && currentVersion > candidates.Max(c => c.Version)!)
        {
            var assessment = Finish(Result(Outcomes.Current,
                $"{NewerThanLookups}: {currentVersion} is not among them (newest known {common.Latest}, recommended "
                + $"{common.Recommended ?? "none"}); a release after they were taken, counted as upgraded", 0.8));
            return (assessment, Signals(declaration, assessment, null));
        }

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
        // assembly into the project, so no C# call site into the package itself
        // can break. A content package's major version can still break markup
        // or CSS, which the call-site model cannot see — flagged, but kept out
        // of breaking.
        if (kind is not null && kind != PackageKinds.Runtime)
        {
            var contentRisk = kind == PackageKinds.Content && semver == "major";
            reasons.Add($"{kind} package: no lib/ or ref/ assemblies of its own");
            if (contentRisk) reasons.Add("content package, major version: markup and CSS may break; not analysed by this step");

            // A meta-package (Swashbuckle.AspNetCore: a props file and
            // dependencies) carries its API in the packages it pulls in. Every
            // dependency whose version moves is diffed, and a call into a
            // changed member of one breaks this upgrade as surely as a call
            // into the package's own.
            var carried = currentCandidate is null ? [] : await TransitiveDiffsAsync(feeds, currentCandidate, recommended, currentFramework, everyChange: true, ct);
            if (carried.Count > 0)
            {
                var classified = await ClassifyAsync(carried.SelectMany(t => t.Changes).ToList(), "(none of its own)", "(none of its own)", carried);
                if (classified is not null) return classified.Value;
                reasons.Add($"the API it carries ({string.Join(", ", carried.Select(Describe))}) changes nothing the code calls");
            }

            var assessment = Finish(Result(Outcomes.UpgradeSafe,
                contentRisk
                    ? $"{semver} version change of a content package; may break markup or CSS (not analysed)"
                    : $"{semver} version change of a {kind} package; no compile-time assemblies",
                0.8))
                with { ClassificationMethod = ClassificationMethods.PackageKind, SemverChange = semver, ContentBreakingPossible = contentRisk };
            return (assessment, Signals(declaration, assessment, null));
        }

        var diff = await DiffAsync(currentCandidate, recommended, currentFramework, ct);
        // Transitive API: a dependency whose major version moves with this
        // upgrade (Swashbuckle 10 pulls Microsoft.OpenApi from 1.x to 2.x) is
        // diffed too; the code may call into it directly. When the package has
        // no comparable assemblies of its own, every dependency that moves is.
        var transitive = currentCandidate is null ? [] : await TransitiveDiffsAsync(feeds, currentCandidate, recommended, currentFramework, everyChange: diff is null, ct);
        if (diff is null && transitive.Count == 0)
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

        var changes = (diff?.Changes ?? []).Concat(transitive.SelectMany(t => t.Changes)).ToList();
        var classifiedUpgrade = await ClassifyAsync(changes, diff?.CurrentGroup ?? "(none comparable)", diff?.RecommendedGroup ?? "(none comparable)", transitive);
        if (classifiedUpgrade is not null) return classifiedUpgrade.Value;

        reasons.Add(semver == "major"
            ? "major version, but the API diff shows nothing the code calls changed: the diff overrides the heuristic"
            : "no call to a changed member found");
        if (transitive.Count > 0) reasons.Add($"dependencies diffed with it: {string.Join(", ", transitive.Select(Describe))}");
        var safe = Finish(Result(Outcomes.UpgradeSafe, $"{semver} version change; nothing the code calls changed", 0.85))
            with { ClassificationMethod = ClassificationMethods.ApiDiff, SemverChange = semver, ApiDiff = Summary(changes, diff?.CurrentGroup, diff?.RecommendedGroup) };
        return (safe, Signals(declaration, safe, null));

        static string Describe(TransitiveDiff t) => $"{t.PackageId} {t.From} -> {t.To}";

        static ApiDiffSummary Summary(IReadOnlyList<ApiChange> all, string? currentGroup, string? recommendedGroup) => new()
        {
            RemovedTypes = all.Count(c => c.Change == "type_removed"),
            RemovedMembers = all.Count(c => c.Change == "member_removed"),
            ChangedSignatures = all.Count(c => c.Change == "signature_changed"),
            CurrentAssemblies = currentGroup ?? "(none comparable)",
            RecommendedAssemblies = recommendedGroup ?? "(none comparable)",
        };

        // Breaking when the code calls a changed member of the package or of
        // a dependency diffed with it; null when it calls none.
        async Task<(PackageAssessment, IReadOnlyList<Signal>)?> ClassifyAsync(
            IReadOnlyList<ApiChange> all, string currentGroup, string recommendedGroup, IReadOnlyList<TransitiveDiff> carriedBy)
        {
            var hits = CallSiteFinder.Find(await loadSource(), all);
            if (hits.Count == 0) return null;

            reasons.Add("call sites found by syntax search guarded by the package's namespaces");
            if (carriedBy.Count > 0) reasons.Add($"dependencies diffed with it: {string.Join(", ", carriedBy.Select(Describe))}");
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
                    ApiDiff = Summary(all, currentGroup, recommendedGroup),
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

    /// <summary>1.5.0: never recommend a version with a known advisory. When the newest version supporting the target
    /// has one, the newest without one, not below the current version, is recommended instead. When there is none,
    /// the current version, if it supports the target itself: the package stays where it is, and the vulnerability
    /// says no fixed release exists yet. Otherwise (the current version does not support the target) the newest
    /// compatible version stands, and the vulnerability on it is reported.</summary>
    private async Task<Candidate?> WithoutAdvisoryAsync(Candidate? newest, Candidate? current, IReadOnlyList<Candidate> ordered, CancellationToken ct)
    {
        if (newest is null || newest.Cached.Vulnerabilities.Count == 0) return newest;
        var floor = current?.Version;
        var clean = ordered.Where(c => c.Version < newest.Version && (floor is null || c.Version >= floor) && c.Cached.Vulnerabilities.Count == 0).ToList();
        var (cleanCompatible, _) = await NewestCompatibleAsync(clean, ct);
        if (cleanCompatible is not null) return cleanCompatible;
        if (current is not null && (await NewestCompatibleAsync([current], ct)).Compatible is not null) return current;
        return newest;
    }

    /// <summary>1.5.0: the version of a retired package's replacement to move to: its newest release within the
    /// publisher's range (any, when the range is <c>[*, )</c> or unreadable), stable, listed, not deprecated, with no
    /// known advisory, supporting the target. Null when no feed answers or no release qualifies.</summary>
    private async Task<string?> ReplacementVersionAsync(FeedSet feeds, string packageId, string? range, CancellationToken ct)
    {
        VersionRange? allowed = range is not null && VersionRange.TryParse(range, out var parsed) ? parsed : null;
        var candidates = new List<Candidate>();
        foreach (var feed in feeds.Authorities)
        {
            var result = await lookup.GetAsync(feed, packageId, ct);
            if (!result.Reachable) continue;
            foreach (var cached in result.Entry!.Versions.Where(v => v.Listed && v.Deprecation is null && v.Vulnerabilities.Count == 0))
            {
                var version = NuGetVersion.Parse(cached.Version);
                if (version.IsPrerelease || (allowed is not null && !allowed.Satisfies(version))) continue;
                if (candidates.All(c => c.Version != version)) candidates.Add(new Candidate(version, feed, result.Entry, cached));
            }
        }

        var (compatible, _) = await NewestCompatibleAsync(candidates.OrderByDescending(c => c.Version).ToList(), ct);
        return compatible?.Version.ToNormalizedString();
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

    /// <summary>The current version's deprecation, with its scope (Part C3). NuGet deprecates versions, not packages,
    /// so the scope is read from the reasons and from the package's other versions. <c>package</c>: no newer listed
    /// version is free of deprecation (the publisher has retired every release), or the reason is Legacy and the
    /// publisher names a different package as its successor (xunit to xunit.v3) — replace it. <c>version</c>: a
    /// newer version is not deprecated and no successor package is named — a maintained package whose old release
    /// was deprecated, for CriticalBugs, Other, or Legacy with "move to latest" — which an upgrade resolves.</summary>
    private static readonly System.Text.RegularExpressions.Regex TargetFrameworkElement =
        new(@"<TargetFrameworks?>", System.Text.RegularExpressions.RegexOptions.IgnoreCase);

    /// <summary>TARGET_FRAMEWORK_BELOW_ENGAGEMENT_TARGET (1.4.0): a modern .NET project (.NETCoreApp) whose framework is
    /// older than the engagement's target. Value "{from} -> {to}", located at the line declaring the framework: the
    /// project file, else the nearest Directory.Build.props above it that declares one.</summary>
    private Signal? RetargetSignal(string repositoryRoot, string relativePath, string? projectText, NuGetFramework? current)
    {
        if (current is null || current.Framework != FrameworkConstants.FrameworkIdentifiers.NetCoreApp
            || _target.Framework != FrameworkConstants.FrameworkIdentifiers.NetCoreApp || current.Version >= _target.Version)
        {
            return null;
        }

        var file = relativePath.Replace('\\', '/');
        var line = FirstMatchLine(projectText);
        if (line is null)
        {
            var root = Path.GetFullPath(repositoryRoot);
            for (var dir = Path.GetDirectoryName(Path.Combine(root, relativePath)); dir is not null
                 && Path.GetFullPath(dir).StartsWith(root, StringComparison.OrdinalIgnoreCase); dir = Path.GetDirectoryName(dir))
            {
                var props = Path.Combine(dir, "Directory.Build.props");
                if (File.Exists(props) && FirstMatchLine(File.ReadAllText(props)) is { } found)
                {
                    file = Path.GetRelativePath(root, props).Replace('\\', '/');
                    line = found;
                    break;
                }
            }
        }

        return new Signal
        {
            Name = "TARGET_FRAMEWORK_BELOW_ENGAGEMENT_TARGET",
            Category = "PROJECT_METADATA",
            Type = "CONFIG_ELEMENT",
            Value = $"{current.GetShortFolderName()} -> {_target.GetShortFolderName()}",
            SourceType = "PROJECT_FILE",
            SourcePath = file,
            EvidenceKind = "FILE",
            OccurrenceCount = 1,
            Evidence = line is null ? [] : [new Evidence { LineStart = line, LineEnd = line }],
            Extractor = Extractor,
            ExtractionConfidence = 1.0m,
        };
    }

    private static int? FirstMatchLine(string? text)
    {
        if (text is null) return null;
        var m = TargetFrameworkElement.Match(text);
        return m.Success ? text.AsSpan(0, m.Index).Count('\n') + 1 : null;
    }

    private static DeprecationFlag? Deprecation(Candidate? current, IReadOnlyList<Candidate> ordered)
    {
        if (current?.Cached.Deprecation is not { } d) return null;
        var legacy = d.Reasons.Any(r => string.Equals(r, "Legacy", StringComparison.OrdinalIgnoreCase));
        var successor = legacy && d.AlternateId is { } alternate && !string.Equals(alternate, current.Entry.PackageId, StringComparison.OrdinalIgnoreCase);
        var maintainedNewer = ordered.FirstOrDefault(c => c.Version > current.Version && c.Cached.Deprecation is null);
        return new DeprecationFlag
        {
            Reasons = d.Reasons, Message = d.Message, ReplacementId = d.AlternateId, ReplacementRange = d.AlternateRange,
            Scope = successor || maintainedNewer is null ? DeprecationScopes.Package : DeprecationScopes.Version,
            NewestNotDeprecated = successor ? null : maintainedNewer?.Version.ToNormalizedString(),
        };
    }

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
            FixedIn = recommended is not null && recommended.Version > current.Version && recommended.Cached.Vulnerabilities.Count == 0
                ? recommended.Version.ToNormalizedString() : null,
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

    // ---------- transitive API ----------

    /// <summary>A dependency diffed with an upgrade: its lowest version each
    /// side resolves to (NuGet picks a range's minimum), and what changed.</summary>
    private sealed record TransitiveDiff(string PackageId, string From, string To, IReadOnlyList<ApiChange> Changes);

    /// <summary>Levels of dependencies walked below the package itself.</summary>
    private const int MaxTransitiveDepth = 3;

    /// <summary>
    /// The dependencies an upgrade moves that carry API the code may call.
    /// The two versions' nuspec dependency groups (nearest to the current and
    /// the target framework) are compared: a dependency on both sides whose
    /// minimum moves across a major version — or, with
    /// <paramref name="everyChange"/>, moves at all — is diffed. A dependency
    /// with no assemblies of its own is itself a meta-package, so the walk
    /// goes one level further into what it carries, every change counted.
    /// </summary>
    private async Task<IReadOnlyList<TransitiveDiff>> TransitiveDiffsAsync(
        FeedSet feeds, Candidate current, Candidate recommended, NuGetFramework? currentFramework, bool everyChange, CancellationToken ct)
    {
        var found = new List<TransitiveDiff>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { current.Entry.PackageId };
        await WalkAsync(current, recommended, everyChange, 0);
        return found.OrderBy(t => t.PackageId, StringComparer.OrdinalIgnoreCase).ToList();

        async Task WalkAsync(Candidate from, Candidate to, bool all, int depth)
        {
            var before = await MinimumsAsync(from, currentFramework ?? _target, ct);
            var after = await MinimumsAsync(to, _target, ct);
            foreach (var (id, toMin) in after.OrderBy(kv => kv.Key, StringComparer.OrdinalIgnoreCase))
            {
                if (!before.TryGetValue(id, out var fromMin) || toMin <= fromMin) continue;
                if (!all && toMin.Major == fromMin.Major) continue;
                if (!seen.Add(id)) continue;
                var fromCandidate = await ResolveAsync(feeds, id, fromMin, ct);
                var toCandidate = await ResolveAsync(feeds, id, toMin, ct);
                if (fromCandidate is null || toCandidate is null) continue;
                var diff = await DiffAsync(fromCandidate, toCandidate, currentFramework, ct);
                if (diff is not null)
                    found.Add(new TransitiveDiff(id, fromCandidate.Version.ToNormalizedString(), toCandidate.Version.ToNormalizedString(), diff.Value.Changes));
                if (depth + 1 < MaxTransitiveDepth)
                    await WalkAsync(fromCandidate, toCandidate, diff is null, depth + 1);
            }
        }
    }

    /// <summary>Each dependency's minimum version, from the dependency group
    /// nearest to <paramref name="framework"/>. Empty when there is none.</summary>
    private async Task<Dictionary<string, NuGetVersion>> MinimumsAsync(Candidate candidate, NuGetFramework framework, CancellationToken ct)
    {
        var minimums = new Dictionary<string, NuGetVersion>(StringComparer.OrdinalIgnoreCase);
        var groups = await lookup.DependenciesAsync(candidate.Feed, candidate.Entry, candidate.Cached, ct);
        if (groups is null || groups.Count == 0) return minimums;
        var nearest = NuGetFrameworkUtility.GetNearest(groups, framework, g => NuGetFramework.Parse(g.Framework));
        foreach (var dependency in nearest?.Packages ?? [])
        {
            if (VersionRange.TryParse(dependency.Range, out var range) && range.MinVersion is { } min) minimums[dependency.Id] = min;
        }

        return minimums;
    }

    /// <summary>What NuGet resolves a dependency's minimum to: that version, or
    /// the lowest listed one above it, on the first authoritative feed that has it.</summary>
    private async Task<Candidate?> ResolveAsync(FeedSet feeds, string id, NuGetVersion minimum, CancellationToken ct)
    {
        foreach (var feed in feeds.Authorities)
        {
            var result = await lookup.GetAsync(feed, id, ct);
            var cached = result.Entry?.Versions
                .Where(v => v.Listed)
                .Select(v => (Version: NuGetVersion.Parse(v.Version), Cached: v))
                .Where(v => v.Version >= minimum)
                .OrderBy(v => v.Version)
                .FirstOrDefault();
            if (cached?.Cached is not null)
            {
                return new Candidate(cached.Value.Version, feed, result.Entry!, cached.Value.Cached);
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

    private static IReadOnlyList<Signal> Signals(PackageDeclaration declaration, PackageAssessment assessment, IReadOnlyList<CallSite>? callSites,
        string? providedBy = null)
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
            case Outcomes.FrameworkProvided:
                signals.Add(AtDeclaration("PACKAGE_PROVIDED_BY_FRAMEWORK", $"{assessment.PackageId} {from}: provided by {providedBy}"));
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
            // The value says which: "package deprecated (...)" is a replacement (package-replacement-required);
            // "version deprecated (...)" is resolved by the upgrade the outcome already describes.
            var reasons = deprecated.Reasons.Count == 0 ? "no reason given" : string.Join(", ", deprecated.Reasons);
            var value = deprecated.Scope == DeprecationScopes.Version
                ? $"{assessment.PackageId} {from}: version deprecated ({reasons}); {deprecated.NewestNotDeprecated} is not"
                : $"{assessment.PackageId} {from}: package deprecated ({reasons}); " + (deprecated.ReplacementId is null
                    ? "no suggested replacement"
                    : deprecated.ReplacementVersion is { } replacementVersion
                        ? $"replacement {deprecated.ReplacementId} {replacementVersion}"
                        : $"replacement {deprecated.ReplacementId}{(deprecated.ReplacementRange is null ? "" : " " + deprecated.ReplacementRange)}; "
                          + "no release of it supports the target without a known advisory");
            signals.Add(AtDeclaration("PACKAGE_DEPRECATED", value));
        }

        if (assessment.Vulnerable is { } vulnerable)
        {
            // 1.5.0: the version that fixes it, or plainly that none does yet; never a version with an advisory.
            signals.Add(AtDeclaration("PACKAGE_VULNERABLE", $"{assessment.PackageId} {from}: {vulnerable.MaxSeverity}; "
                + (vulnerable.FixedIn is { } fixedIn ? $"fixed in {fixedIn}" : NoFixedRelease)));
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
