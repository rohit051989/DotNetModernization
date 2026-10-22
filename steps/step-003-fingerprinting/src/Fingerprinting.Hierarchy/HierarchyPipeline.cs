using Fingerprinting.Analysis;
using Fingerprinting.Dependencies;
using Fingerprinting.Domain;
using NuGet.Frameworks;
using NuGet.Versioning;

namespace Fingerprinting.Hierarchy;

public sealed record HierarchyOptions(
    bool ComparePublicFeed,
    int MaxPackageDepth = 12,
    int MaxPackages = 5000,
    string PublicFeedSource = FeedResolver.NuGetOrgV3);

/// <summary>
/// Builds the dependency-hierarchy@1.0.0 artifact for one repository — 37-DEPENDENCY-HIERARCHY.md Part B. Read-only
/// against the repository: projects and packages come from solution-discovery and dependency-assessment, assembly
/// references and project-reference lines from the project files, a package's own dependencies from the project's
/// restored assets file where one exists and otherwise from the feed's metadata, through the lookup cache
/// dependency-assessment shares. Nothing is restored or downloaded into the repository.
/// <para>
/// A graph, not a tree: every node is held once by its id, and every edge once by (from, to, kind). A package's
/// dependencies are followed at most <see cref="HierarchyOptions.MaxPackageDepth"/> levels below the project that
/// declares it, the graph holds at most <see cref="HierarchyOptions.MaxPackages"/> packages, and an edge back to a node
/// still being followed is recorded and closes a cycle. What could not be resolved is a node or a field marked not
/// checked, with the reason.
/// </para>
/// </summary>
public sealed class HierarchyPipeline(PackageLookup lookup, HierarchyOptions options, LookupWorkers? workers = null)
{
    /// <summary>Matches the dependency-hierarchy step registration version.</summary>
    public const string ScannerVersion = "1.0.0";

    private static readonly string[] Severities = ["low", "moderate", "high", "critical"];

    private readonly Dictionary<string, HierarchyNode> _nodes = new(StringComparer.Ordinal);
    private readonly Dictionary<(string From, string To, string Kind), EdgeBuilder> _edges = [];
    private readonly Dictionary<string, int> _expanded = new(StringComparer.Ordinal);
    private readonly Dictionary<string, Origin> _origins = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, (string? Version, string? Reason)> _lowest = new(StringComparer.OrdinalIgnoreCase);
    private readonly List<Warning> _warnings = [];
    private readonly HashSet<string> _prefetched = new(StringComparer.OrdinalIgnoreCase);
    private int _packageCount;

    private sealed record Origin(string Value, string Basis, Feed? Feed, string? NotCheckedReason);

    private sealed class EdgeBuilder(string from, string to, string kind, string resolution)
    {
        public string From { get; } = from;
        public string To { get; } = to;
        public string Kind { get; } = kind;
        public string Resolution { get; set; } = resolution;
        public string? VersionRequested { get; set; }
        public SortedSet<string> Frameworks { get; } = new(StringComparer.Ordinal);
        public SourceAt? DeclaredAt { get; set; }
        public bool ClosesCycle { get; set; }
    }

    public async Task<DependencyHierarchyArtifact> RunAsync(HierarchyInput input, string repositoryRoot, CancellationToken ct,
        StepProgress? progress = null, WorkLimits? limits = null)
    {
        progress ??= StepProgress.Silent();
        limits ??= WorkLimits.Default;
        if (input.Assessment is null)
        {
            _warnings.Add(Warn("ASSESSMENT_MISSING", "dependency-assessment's artifact was not available: packages come from solution-discovery's inventory, without findings."));
        }

        // Every project first, so a reference to one later in the order finds its node.
        progress.Phase("read", input.Projects.Count);
        var files = new Dictionary<string, ProjectFile>(StringComparer.Ordinal);
        foreach (var project in input.Projects.OrderBy(p => p.RelativePath, StringComparer.Ordinal))
        {
            using var item = progress.Item(project.RelativePath);
            var path = Combine(repositoryRoot, project.RelativePath);
            var file = project.ParseStatus == "success" && project.StructuralType is "csharp_project" or "vb_project" or "fsharp_project"
                ? ProjectFile.Read(path)
                : ProjectFile.Empty("not a code project");
            files[project.RelativePath] = file;
            var (kind, basis) = file.Classify(project.StructuralType, project.ParseStatus, project.OutputType, project.ProjectSdk,
                project.Packages.Select(p => p.PackageId));
            AddNode(new HierarchyNode
            {
                Id = ProjectNodeId(project.RelativePath),
                Type = NodeTypes.Project,
                Name = project.Name,
                Status = file.Error is not null && kind != ProjectKinds.Other ? NodeStatuses.NotChecked : NodeStatuses.Checked,
                NotCheckedReason = file.Error is not null && kind != ProjectKinds.Other ? file.Error : null,
                Project = new ProjectNodeDetail
                {
                    ProjectId = project.ProjectId,
                    Path = project.RelativePath,
                    Kind = kind,
                    KindBasis = basis,
                    TargetFrameworks = project.TargetFrameworks,
                    ProjectFormat = project.ProjectFormat,
                    PackageManagement = project.PackageManagement,
                },
            });
        }

        var assessed = (input.Assessment?.Projects ?? []).ToDictionary(p => p.ProjectPath, StringComparer.Ordinal);
        progress.Phase("resolve", input.Projects.Count);
        foreach (var project in input.Projects.OrderBy(p => p.RelativePath, StringComparer.Ordinal))
        {
            ct.ThrowIfCancellationRequested();
            using var item = progress.Item(project.RelativePath);
            using var limit = CancellationTokenSource.CreateLinkedTokenSource(ct);
            limit.CancelAfter(limits.ProjectLoad);
            try
            {
                await ProjectAsync(input, repositoryRoot, project, files[project.RelativePath], assessed.GetValueOrDefault(project.RelativePath), limit.Token);
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                var reason = $"not checked: resolving the project's dependencies took longer than {limits.ProjectLoad.TotalSeconds:0} s; what was found before then is kept";
                progress.RecordNotChecked(project.RelativePath, "project", reason);
                var id = ProjectNodeId(project.RelativePath);
                _nodes[id] = _nodes[id] with { Status = NodeStatuses.NotChecked, NotCheckedReason = reason };
            }
        }

        progress.Phase("graph");
        return Build(input);
    }

    // ---------- one project ----------

    private async Task ProjectAsync(HierarchyInput input, string repositoryRoot, HierarchyInputProject project, ProjectFile file,
        AssessedProject? assessed, CancellationToken ct)
    {
        var from = ProjectNodeId(project.RelativePath);
        var projectPath = Combine(repositoryRoot, project.RelativePath);
        var projectDirectory = Path.GetDirectoryName(projectPath)!;

        foreach (var reference in input.ProjectReferences.Where(r => r.Source == project.RelativePath).OrderBy(r => r.RawPath, StringComparer.Ordinal))
        {
            var to = reference.Target is not null ? ProjectNodeId(reference.Target) : MissingProject(repositoryRoot, projectDirectory, reference);
            var edge = AddEdge(from, to, EdgeKinds.ProjectReference, Resolutions.Declared);
            edge.DeclaredAt = new SourceAt
            {
                FilePath = project.RelativePath,
                Line = file.ProjectReferenceLines.TryGetValue(reference.RawPath.Replace('\\', '/'), out var line) ? line : null,
            };
        }

        if (file.Error is not null && project.Packages.Count == 0) return;

        FeedSet? feeds = null;
        string? feedError = null;
        try
        {
            feeds = FeedResolver.Resolve(repositoryRoot, projectDirectory, options.ComparePublicFeed, options.PublicFeedSource);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidOperationException or NuGet.Configuration.NuGetConfigurationException)
        {
            feedError = $"the project's NuGet configuration could not be read: {ex.Message}";
        }

        var framework = project.CurrentFramework;
        var (assets, _) = project.PackageManagement is "packagereference" or "mixed" ? AssetsFile.Read(projectDirectory, framework) : (null, null);
        var declared = Declared(project, assessed);
        var declaredIds = declared.Select(d => d.PackageId).ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (feeds is not null) await PrefetchAsync(feeds, declaredIds.Concat(assets?.Packages.Keys ?? []), ct);

        foreach (var package in declared.OrderBy(d => d.PackageId, StringComparer.OrdinalIgnoreCase))
        {
            ct.ThrowIfCancellationRequested();
            var restored = assets?.Packages.GetValueOrDefault(package.PackageId);
            var version = restored?.Version ?? package.Version;
            var nodeId = await EnsurePackageAsync(input, package.PackageId, version, feeds, feedError, package.UnresolvedReason, restored is not null, ct);
            if (nodeId is null) break;                                                   // the package limit
            AddFindings(nodeId, package.Findings);
            var edge = AddEdge(from, nodeId, package.EdgeKind, Resolutions.Declared);
            edge.VersionRequested = package.VersionText;
            edge.DeclaredAt = package.DeclaredAt;
            if (version is not null && feeds is not null)
            {
                await ExpandAsync(input, nodeId, package.PackageId, version, framework, assets, feeds, options.MaxPackageDepth, ct);
            }
        }

        foreach (var reference in file.AssemblyReferences.OrderBy(r => r.Include, StringComparer.OrdinalIgnoreCase))
        {
            if (AssemblyNode(repositoryRoot, projectDirectory, reference, declaredIds) is not { } node) continue;
            AddNode(node);
            var edge = AddEdge(from, node.Id, EdgeKinds.AssemblyReference, Resolutions.Declared);
            edge.VersionRequested = reference.Version;
            edge.DeclaredAt = new SourceAt { FilePath = project.RelativePath, Line = reference.Line };
        }
    }

    private sealed record DeclaredPackage(
        string PackageId, string? Version, string? VersionText, string EdgeKind, SourceAt? DeclaredAt, string? UnresolvedReason, AssessedPackage? Findings);

    /// <summary>The project's direct packages: dependency-assessment's, whose versions it resolved (central package
    /// management included); solution-discovery's when dependency-assessment did not assess the project.</summary>
    private static List<DeclaredPackage> Declared(HierarchyInputProject project, AssessedProject? assessed)
    {
        if (assessed is { Status: ProjectScanStatuses.Scanned })
        {
            return assessed.Packages.Select(p => new DeclaredPackage(
                p.PackageId,
                p.CurrentVersion,
                p.CurrentVersion,
                p.VersionSource switch
                {
                    "packages_config" => EdgeKinds.PackagesConfig,
                    "central" => EdgeKinds.CentralPackageVersion,
                    _ => project.Packages.FirstOrDefault(i => i.PackageId.Equals(p.PackageId, StringComparison.OrdinalIgnoreCase))?.DeclarationSource == "packages_config"
                        ? EdgeKinds.PackagesConfig
                        : EdgeKinds.PackageReference,
                },
                p.DeclaredAt is null ? null : new SourceAt { FilePath = p.DeclaredAt.FilePath, Line = p.DeclaredAt.Line },
                p.CurrentVersion is null ? $"no version could be read: {p.OutcomeReason ?? "unresolved"}" : null,
                p)).ToList();
        }

        return project.Packages.Select(p =>
        {
            var version = PackageDeclarations.ParseVersion(p.VersionRaw ?? "")?.ToNormalizedString();
            return new DeclaredPackage(p.PackageId, version, p.VersionRaw,
                p.DeclarationSource == "packages_config" ? EdgeKinds.PackagesConfig : EdgeKinds.PackageReference, null,
                version is null ? $"no version could be read{(p.VersionRaw is null ? "" : $" from '{p.VersionRaw}'")}" : null, null);
        }).ToList();
    }

    private string MissingProject(string repositoryRoot, string projectDirectory, InventoryReference reference)
    {
        var full = Path.GetFullPath(Path.Combine(projectDirectory, reference.RawPath.Replace('\\', Path.DirectorySeparatorChar)));
        var relative = Path.GetRelativePath(repositoryRoot, full).Replace('\\', '/');
        var outside = relative.StartsWith("..", StringComparison.Ordinal) || Path.IsPathRooted(relative);
        var path = outside ? reference.RawPath.Replace('\\', '/') : relative;
        var id = ProjectNodeId(path);
        if (!_nodes.ContainsKey(id))
        {
            AddNode(new HierarchyNode
            {
                Id = id,
                Type = NodeTypes.Project,
                Name = Path.GetFileNameWithoutExtension(path),
                Status = NodeStatuses.NotChecked,
                NotCheckedReason = outside || reference.ResolutionStatus == "external_repository"
                    ? "outside this repository: not followed"
                    : "the referenced project file was not found in the repository",
                Project = new ProjectNodeDetail
                {
                    Path = path, Kind = ProjectKinds.Other, KindBasis = "not in the repository's inventory", ProjectFormat = "unknown", PackageManagement = "none",
                },
            });
        }

        return id;
    }

    // ---------- packages ----------

    /// <summary>The package's node, created with its origin the first time; null when the graph is at its package limit.</summary>
    /// <param name="restored">The project's assets file has the package: restore installed it, whether or not a feed lists it.</param>
    private async Task<string?> EnsurePackageAsync(HierarchyInput input, string packageId, string? version, FeedSet? feeds, string? feedError,
        string? unresolvedReason, bool restored, CancellationToken ct)
    {
        var id = PackageNodeId(packageId, version);
        if (_nodes.ContainsKey(id)) return id;
        if (_packageCount >= options.MaxPackages)
        {
            if (_warnings.All(w => w.Code != "PACKAGE_LIMIT"))
            {
                _warnings.Add(Warn("PACKAGE_LIMIT", $"The graph reached its limit of {options.MaxPackages} packages; further packages were not added."));
            }

            return null;
        }

        var origin = await OriginAsync(input, packageId, feeds, feedError, restored, ct);
        CachedVersion? cached = null;
        if (version is not null && origin.Feed is not null)
        {
            var found = await lookup.GetAsync(origin.Feed, packageId, ct);
            cached = found.Entry?.Versions.FirstOrDefault(v => SameVersion(v.Version, version));
        }

        var reason = unresolvedReason ?? origin.NotCheckedReason;
        _packageCount++;
        AddNode(new HierarchyNode
        {
            Id = id,
            Type = NodeTypes.Package,
            Name = packageId,
            Status = reason is null ? NodeStatuses.Checked : NodeStatuses.NotChecked,
            NotCheckedReason = reason,
            Package = new PackageNodeDetail
            {
                PackageId = packageId,
                Version = version,
                Origin = origin.Value,
                OriginBasis = origin.Basis,
                FeedName = origin.Feed?.Name,
                FeedUrl = origin.Feed?.Url,
                Producer = input.Producers.GetValueOrDefault(packageId.ToLowerInvariant()),
                VulnerabilityMaxSeverity = cached is { Vulnerabilities.Count: > 0 }
                    ? Severities[Math.Clamp(cached.Vulnerabilities.Max(v => v.Severity), 0, 3)]
                    : null,
            },
        });
        return id;
    }

    /// <summary>Internal or external, once per package id (Part B3). Estate consolidation's producer decides first; then
    /// the feeds: nuget.org answering as the fallback is external; a client feed answering is internal unless nuget.org
    /// has the package too.</summary>
    private async Task<Origin> OriginAsync(HierarchyInput input, string packageId, FeedSet? feeds, string? feedError, bool restored, CancellationToken ct)
    {
        if (_origins.TryGetValue(packageId, out var known)) return known;
        Origin origin;
        Feed? answering = null;
        var errors = new List<string>();
        foreach (var feed in feeds?.Authorities ?? [])
        {
            var result = await lookup.GetAsync(feed, packageId, ct);
            if (result.Entry is { Versions.Count: > 0 })
            {
                answering = feed;
                break;
            }

            errors.Add(result.Error ?? $"feed '{feed.Name}' lists no version of it");
        }

        if (input.Producers.TryGetValue(packageId.ToLowerInvariant(), out var producer))
        {
            origin = new Origin(PackageOrigins.Internal, $"produced by repository {producer.RepositoryName} ({producer.ProjectPath}), as estate consolidation found",
                answering, null);
        }
        else if (answering is null && restored && feeds is { UsingClientFeeds: false })
        {
            // Restore installed it, and nuget.org is the project's only source: an unlisted package, still restorable.
            origin = new Origin(PackageOrigins.External, "restored from nuget.org, the project's only source, which lists no version of it (unlisted)",
                null, null);
        }
        else if (answering is null)
        {
            var why = feedError ?? (errors.Count > 0 ? string.Join("; ", errors) : "no feed was resolved for the project");
            origin = new Origin(PackageOrigins.Unknown, "no feed answered for it", null, $"not checked: {why}");
        }
        else if (feeds is not { UsingClientFeeds: true })
        {
            origin = new Origin(PackageOrigins.External, "answered by nuget.org, the fallback: the project declares no client feed", answering, null);
        }
        else if (feeds.Public is { } nuget)
        {
            var onPublic = await lookup.GetAsync(nuget, packageId, ct);
            origin = onPublic.Entry is { Versions.Count: > 0 }
                ? new Origin(PackageOrigins.External, $"on client feed '{answering.Name}' and on nuget.org", answering, null)
                : onPublic.Reachable
                    ? new Origin(PackageOrigins.Internal, $"on client feed '{answering.Name}', not on nuget.org", answering, null)
                    : new Origin(PackageOrigins.Internal, $"on client feed '{answering.Name}'; nuget.org could not be asked ({onPublic.Error})", answering, null);
        }
        else
        {
            origin = new Origin(PackageOrigins.Internal, $"on client feed '{answering.Name}'; nuget.org was not consulted (the public comparison is off)", answering, null);
        }

        _origins[packageId] = origin;
        return origin;
    }

    /// <summary>
    /// A package's own dependencies for one framework, followed <paramref name="remaining"/> levels down. A node already
    /// followed as deep is not followed again; one reached again more shallowly is followed further.
    /// </summary>
    private async Task ExpandAsync(HierarchyInput input, string nodeId, string packageId, string version, string? framework, AssetsFile? assets,
        FeedSet feeds, int remaining, CancellationToken ct)
    {
        var key = $"{nodeId}|{framework}";
        if (_expanded.TryGetValue(key, out var done) && done >= remaining) return;
        if (remaining <= 0)
        {
            NoteDependencies(nodeId, null, $"deeper than {options.MaxPackageDepth} levels below the project that declares it: not followed");
            return;
        }

        _expanded[key] = remaining;
        var dependencies = new List<(string Id, string Range, string? Version, string? Reason)>();
        string resolution;
        string? frameworkName = framework;
        var restored = assets?.Packages.GetValueOrDefault(packageId);
        if (restored is not null && SameVersion(restored.Version, version))
        {
            resolution = Resolutions.AssetsFile;
            frameworkName = assets!.Framework;
            foreach (var (id, range) in restored.Dependencies)
            {
                var depVersion = assets.Packages.GetValueOrDefault(id)?.Version;
                dependencies.Add((id, range, depVersion, depVersion is null ? "not in the assets file's packages" : null));
            }
        }
        else
        {
            resolution = Resolutions.FeedMetadata;
            var target = framework is null ? null : NuGetFramework.Parse(framework);
            if (target is null || target.IsUnsupported)
            {
                NoteDependencies(nodeId, null, "the project's target framework is not known: the package's dependencies were not checked");
                return;
            }

            var (groups, reason) = await GroupsAsync(feeds, packageId, version, ct);
            if (groups is null)
            {
                NoteDependencies(nodeId, null, reason);
                return;
            }

            frameworkName = target.GetShortFolderName();
            var nearest = new FrameworkReducer().GetNearest(target, groups.Select(g => NuGetFramework.Parse(g.Framework)));
            var group = nearest is null ? null : groups.First(g => NuGetFramework.Parse(g.Framework).Equals(nearest));
            await PrefetchAsync(feeds, (group?.Packages ?? []).Select(p => p.Id), ct);
            foreach (var dependency in group?.Packages ?? [])
            {
                var (depVersion, depReason) = await LowestAsync(feeds, dependency.Id, dependency.Range, ct);
                dependencies.Add((dependency.Id, dependency.Range, depVersion, depReason));
            }
        }

        NoteDependencies(nodeId, resolution, null);
        foreach (var dependency in dependencies.OrderBy(d => d.Id, StringComparer.OrdinalIgnoreCase))
        {
            ct.ThrowIfCancellationRequested();
            // Unresolved: the node carries the range's lower bound, and is marked not checked.
            var depVersion = dependency.Version
                          ?? (VersionRange.TryParse(dependency.Range, out var range) ? range.MinVersion?.ToNormalizedString() : null);
            var depId = await EnsurePackageAsync(input, dependency.Id, depVersion, feeds, null,
                dependency.Version is null ? $"no version could be resolved for {dependency.Range}: {dependency.Reason}" : null,
                resolution == Resolutions.AssetsFile && dependency.Version is not null, ct);
            if (depId is null)
            {
                NoteDependencies(nodeId, resolution, $"the graph reached its limit of {options.MaxPackages} packages: some dependencies are not shown");
                return;
            }

            var edge = AddEdge(nodeId, depId, EdgeKinds.PackageDependency, resolution);
            edge.VersionRequested = dependency.Range;
            if (frameworkName is not null) edge.Frameworks.Add(frameworkName);
            if (dependency.Version is not null)
            {
                await ExpandAsync(input, depId, dependency.Id, dependency.Version, framework, assets, feeds, remaining - 1, ct);
            }
        }
    }

    private async Task<(IReadOnlyList<CachedDependencyGroup>? Groups, string Reason)> GroupsAsync(FeedSet feeds, string packageId, string version, CancellationToken ct)
    {
        var errors = new List<string>();
        foreach (var feed in feeds.Authorities)
        {
            var result = await lookup.GetAsync(feed, packageId, ct);
            var cached = result.Entry?.Versions.FirstOrDefault(v => SameVersion(v.Version, version));
            if (cached is null)
            {
                errors.Add(result.Error ?? $"feed '{feed.Name}' lists no version {version}");
                continue;
            }

            var groups = cached.Dependencies ?? await lookup.DependenciesAsync(feed, result.Entry!, cached, ct);
            return groups is null
                ? (null, $"the package's dependencies could not be read from feed '{feed.Name}'")
                : (groups, "");
        }

        return (null, $"its dependencies were not checked: {(errors.Count > 0 ? string.Join("; ", errors) : "no feed was resolved")}");
    }

    /// <summary>
    /// Asks the feeds about several packages at once, so the walk that follows finds them in the cache (Part B6): each
    /// authority in turn for the packages earlier ones did not have, then nuget.org for those a client feed had, which
    /// decides their origin. A package is prefetched once per run.
    /// </summary>
    private async Task PrefetchAsync(FeedSet feeds, IEnumerable<string> packageIds, CancellationToken ct)
    {
        if (workers is null) return;
        var pending = packageIds.Distinct(StringComparer.OrdinalIgnoreCase).Where(_prefetched.Add).ToList();
        if (pending.Count < 2) return;                                 // nothing to overlap
        var found = new System.Collections.Concurrent.ConcurrentDictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
        foreach (var feed in feeds.Authorities)
        {
            var ask = pending.Where(id => !found.ContainsKey(id)).ToList();
            if (ask.Count == 0) break;
            await workers.ForEachAsync(ask, async (worker, id) =>
            {
                if ((await worker.GetAsync(feed, id, ct)).Entry is { Versions.Count: > 0 }) found[id] = true;
            });
        }

        if (feeds is { UsingClientFeeds: true, Public: { } nuget } && !found.IsEmpty)
        {
            await workers.ForEachAsync(found.Keys.Order(StringComparer.OrdinalIgnoreCase).ToList(), (worker, id) => worker.GetAsync(nuget, id, ct));
        }
    }

    /// <summary>The lowest listed version a range allows — the one restore picks.</summary>
    private async Task<(string? Version, string? Reason)> LowestAsync(FeedSet feeds, string packageId, string rangeText, CancellationToken ct)
    {
        var key = $"{packageId}|{rangeText}";
        if (_lowest.TryGetValue(key, out var known)) return known;
        (string?, string?) answer = (null, $"'{rangeText}' is not a version range");
        if (VersionRange.TryParse(rangeText, out var range))
        {
            var errors = new List<string>();
            answer = (null, null);
            foreach (var feed in feeds.Authorities)
            {
                var result = await lookup.GetAsync(feed, packageId, ct);
                var lowest = result.Entry?.Versions
                    .Where(v => v.Listed && NuGetVersion.TryParse(v.Version, out _))
                    .Select(v => NuGetVersion.Parse(v.Version))
                    .Where(range.Satisfies)
                    .Min();
                if (lowest is not null)
                {
                    answer = (lowest.ToNormalizedString(), null);
                    break;
                }

                errors.Add(result.Error ?? $"feed '{feed.Name}' has no version in {rangeText}");
            }

            if (answer.Item1 is null) answer = (null, errors.Count > 0 ? string.Join("; ", errors) : "no feed was resolved");
        }

        _lowest[key] = answer;
        return answer;
    }

    private void NoteDependencies(string nodeId, string? resolution, string? notChecked)
    {
        var node = _nodes[nodeId];
        var package = node.Package!;
        _nodes[nodeId] = node with
        {
            Package = package with
            {
                DependenciesResolution = package.DependenciesResolution ?? resolution,
                DependenciesNotCheckedReason = notChecked ?? (resolution is not null ? null : package.DependenciesNotCheckedReason),
            },
        };
    }

    private void AddFindings(string nodeId, AssessedPackage? assessed)
    {
        if (assessed is null) return;
        var node = _nodes[nodeId];
        var current = node.Package!.Findings;
        if (current is not null && Outcomes.Rank(current.Outcome) <= Outcomes.Rank(assessed.Outcome)) return;   // keep the worst
        _nodes[nodeId] = node with
        {
            Package = node.Package with
            {
                Findings = new PackageFindings
                {
                    Outcome = assessed.Outcome,
                    OutcomeReason = assessed.OutcomeReason,
                    RecommendedVersion = assessed.RecommendedVersion,
                    Outdated = assessed.Outcome is Outcomes.UpgradeSafe or Outcomes.UpgradeBreaking,
                    Deprecated = assessed.Deprecated is not null || current?.Deprecated == true,
                    Vulnerable = assessed.Vulnerable is not null || current?.Vulnerable == true,
                    VulnerabilityMaxSeverity = assessed.Vulnerable?.MaxSeverity ?? current?.VulnerabilityMaxSeverity,
                },
            },
        };
    }

    // ---------- assembly references ----------

    private static HierarchyNode? AssemblyNode(string repositoryRoot, string projectDirectory, AssemblyReference reference, IReadOnlySet<string> declaredPackages)
    {
        if (reference.HintPath is null)
        {
            var location = ProjectFile.IsFrameworkAssembly(reference.Name) ? AssemblyLocations.Framework : AssemblyLocations.Gac;
            return new HierarchyNode
            {
                Id = $"assembly:{location}:{reference.Name.ToLowerInvariant()}",
                Type = NodeTypes.Assembly,
                Name = reference.Name,
                Assembly = new AssemblyNodeDetail { AssemblyName = reference.Name, Version = reference.Version, Location = location },
            };
        }

        var hint = reference.HintPath.Replace('\\', '/');
        if (FromDeclaredPackage(hint, declaredPackages)) return null;           // the package's node stands for it

        var full = Path.GetFullPath(Path.Combine(projectDirectory, reference.HintPath.Replace('\\', Path.DirectorySeparatorChar)));
        var relative = Path.GetRelativePath(repositoryRoot, full).Replace('\\', '/');
        var inside = !relative.StartsWith("..", StringComparison.Ordinal) && !Path.IsPathRooted(relative);
        var exists = File.Exists(full);
        var where = inside ? AssemblyLocations.Repository : AssemblyLocations.OutsideRepository;
        var path = inside ? relative : hint;
        return new HierarchyNode
        {
            Id = $"assembly:{where}:{path.ToLowerInvariant()}",
            Type = NodeTypes.Assembly,
            Name = reference.Name,
            Status = exists ? NodeStatuses.Checked : NodeStatuses.NotChecked,
            NotCheckedReason = exists ? null : $"the HintPath's file {path} does not exist here",
            Assembly = new AssemblyNodeDetail { AssemblyName = reference.Name, Version = reference.Version, Location = where, Path = path, Exists = exists },
        };
    }

    /// <summary>A HintPath into NuGet's packages folder for a package the project declares: <c>..\packages\Foo.1.2.0\lib\net45\Foo.dll</c>.</summary>
    private static bool FromDeclaredPackage(string hint, IReadOnlySet<string> declaredPackages)
    {
        var segments = hint.Split('/', StringSplitOptions.RemoveEmptyEntries);
        for (var i = 0; i + 1 < segments.Length; i++)
        {
            if (!segments[i].Equals("packages", StringComparison.OrdinalIgnoreCase)) continue;
            var folder = segments[i + 1];
            if (declaredPackages.Any(p => folder.StartsWith(p + ".", StringComparison.OrdinalIgnoreCase)
                                          && NuGetVersion.TryParse(folder[(p.Length + 1)..], out _)))
            {
                return true;
            }
        }

        return false;
    }

    // ---------- the graph ----------

    private DependencyHierarchyArtifact Build(HierarchyInput input)
    {
        var edges = _edges.Values.OrderBy(e => e.From, StringComparer.Ordinal).ThenBy(e => e.To, StringComparer.Ordinal).ThenBy(e => e.Kind, StringComparer.Ordinal).ToList();
        var outgoing = edges.GroupBy(e => e.From).ToDictionary(g => g.Key, g => g.ToList(), StringComparer.Ordinal);
        var inventory = input.Projects.Select(p => ProjectNodeId(p.RelativePath)).ToHashSet(StringComparer.Ordinal);
        var referenced = edges.Where(e => e.Kind == EdgeKinds.ProjectReference).Select(e => e.To).ToHashSet(StringComparer.Ordinal);
        var roots = inventory.Where(id => !referenced.Contains(id)).Order(StringComparer.Ordinal).ToList();

        // Cycles: an edge back to a node still on the depth-first path closes one. Roots first, then anything a root
        // does not reach (a cycle no root enters), each in id order, so the same graph marks the same edges.
        var cycles = new List<IReadOnlyList<string>>();
        var state = new Dictionary<string, int>(StringComparer.Ordinal);              // 1 on the path, 2 finished
        var path = new List<string>();
        void Visit(string id)
        {
            state[id] = 1;
            path.Add(id);
            foreach (var edge in outgoing.GetValueOrDefault(id) ?? [])
            {
                switch (state.GetValueOrDefault(edge.To))
                {
                    case 1:
                        edge.ClosesCycle = true;
                        var cycle = path.Skip(path.IndexOf(edge.To)).ToList();
                        var start = cycle.IndexOf(cycle.Min(StringComparer.Ordinal)!);
                        cycles.Add(cycle.Skip(start).Concat(cycle.Take(start)).ToList());
                        break;
                    case 0:
                        Visit(edge.To);
                        break;
                }
            }

            path.RemoveAt(path.Count - 1);
            state[id] = 2;
        }

        foreach (var id in roots.Concat(_nodes.Keys.Order(StringComparer.Ordinal)))
        {
            if (state.GetValueOrDefault(id) == 0) Visit(id);
        }

        // Depth: the longest path from a root, over the edges that do not close a cycle.
        var depth = new Dictionary<string, int>(StringComparer.Ordinal);
        int Longest(string id)
        {
            if (depth.TryGetValue(id, out var known)) return known;
            var best = 0;
            foreach (var edge in outgoing.GetValueOrDefault(id) ?? [])
            {
                if (!edge.ClosesCycle) best = Math.Max(best, 1 + Longest(edge.To));
            }

            return depth[id] = best;
        }

        var maxDepth = roots.Count == 0 ? 0 : roots.Max(Longest);
        var declaredByProject = edges.Where(e => _nodes[e.From].Type == NodeTypes.Project).Select(e => e.To).ToHashSet(StringComparer.Ordinal);
        var nodes = _nodes.Values
            .Select(n => n.Package is null ? n : n with { Package = n.Package with { Transitive = !declaredByProject.Contains(n.Id) } })
            .OrderBy(n => n.Id, StringComparer.Ordinal)
            .ToList();
        var packages = nodes.Where(n => n.Type == NodeTypes.Package).ToList();

        return new DependencyHierarchyArtifact
        {
            ScannerVersion = ScannerVersion,
            RepositoryId = input.RepositoryId,
            RepositorySlug = input.RepositorySlug,
            Limits = new HierarchyLimits { MaxPackageDepth = options.MaxPackageDepth, MaxPackages = options.MaxPackages },
            Summary = new HierarchySummary
            {
                ProjectCount = nodes.Count(n => n.Type == NodeTypes.Project),
                CountByProjectKind = Count(nodes.Where(n => n.Project is not null).Select(n => n.Project!.Kind)),
                PackageCount = packages.Count,
                InternalPackageCount = packages.Count(p => p.Package!.Origin == PackageOrigins.Internal),
                ExternalPackageCount = packages.Count(p => p.Package!.Origin == PackageOrigins.External),
                TransitivePackageCount = packages.Count(p => p.Package!.Transitive),
                AssemblyCount = nodes.Count(n => n.Type == NodeTypes.Assembly),
                EdgeCount = edges.Count,
                CountByEdgeKind = Count(edges.Select(e => e.Kind)),
                RootCount = roots.Count,
                CycleCount = cycles.Count,
                NotCheckedCount = nodes.Count(n => n.Status == NodeStatuses.NotChecked),
                Depth = maxDepth,
            },
            Roots = roots,
            Nodes = nodes,
            Edges = edges.Select(e => new HierarchyEdge
            {
                From = e.From,
                To = e.To,
                Kind = e.Kind,
                Resolution = e.Resolution,
                VersionRequested = e.VersionRequested,
                Frameworks = e.Frameworks.ToList(),
                DeclaredAt = e.DeclaredAt,
                ClosesCycle = e.ClosesCycle,
            }).ToList(),
            Cycles = cycles,
            Warnings = _warnings.OrderBy(w => w.Code, StringComparer.Ordinal).ThenBy(w => w.Message, StringComparer.Ordinal).ToList(),
        };
    }

    // ---------- helpers ----------

    private void AddNode(HierarchyNode node) => _nodes.TryAdd(node.Id, node);

    private EdgeBuilder AddEdge(string from, string to, string kind, string resolution)
    {
        if (!_edges.TryGetValue((from, to, kind), out var edge))
        {
            edge = new EdgeBuilder(from, to, kind, resolution);
            _edges[(from, to, kind)] = edge;
        }
        else if (resolution == Resolutions.AssetsFile)
        {
            edge.Resolution = resolution;                              // what restore chose outranks what it would choose
        }

        return edge;
    }

    public static string ProjectNodeId(string relativePath) => $"project:{relativePath}";

    public static string PackageNodeId(string packageId, string? version) =>
        $"package:{packageId.ToLowerInvariant()}@{(version is null ? "unresolved" : NormaliseVersion(version))}";

    private static string NormaliseVersion(string version) =>
        NuGetVersion.TryParse(version, out var parsed) ? parsed.ToNormalizedString().ToLowerInvariant() : version.ToLowerInvariant();

    private static bool SameVersion(string a, string b) =>
        NuGetVersion.TryParse(a, out var x) && NuGetVersion.TryParse(b, out var y) ? x == y : a.Equals(b, StringComparison.OrdinalIgnoreCase);

    private static string Combine(string root, string relative) => Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));

    private static SortedDictionary<string, int> Count(IEnumerable<string> values)
    {
        var counts = new SortedDictionary<string, int>(StringComparer.Ordinal);
        foreach (var value in values) counts[value] = counts.GetValueOrDefault(value) + 1;
        return counts;
    }

    private static Warning Warn(string code, string message) => new() { Code = code, Message = message, Severity = WarningSeverities.Warning };
}
