using Fingerprinting.Domain;

namespace Fingerprinting.Impact;

public sealed record WorkItemSeed(string ItemId, Guid? ProjectId, string ProjectPath, IReadOnlyList<SeedFile> Seeds);

public sealed record ResolutionInfo(string Id, string Name, bool IsDefault, string ConsumerImpact, IReadOnlyList<ImpactRule> Rules);

public sealed record CatalogItemInfo(string ItemId, string Name, IReadOnlyList<ResolutionInfo> Resolutions);

/// <param name="Decisions">The engagement's live decisions: item → chosen
/// resolution (decided items only).</param>
public sealed record ImpactInput(
    Guid RepositoryId, string RepositorySlug, string EngagementId, ProjectMap Projects, IReadOnlyList<WorkItemSeed> WorkItems,
    IReadOnlyDictionary<string, CatalogItemInfo> Items, IReadOnlyDictionary<string, string> Decisions,
    IReadOnlyList<TestLink> Tests, IReadOnlyList<EntryPointRef> EntryPoints,
    IReadOnlyList<HostLink>? HostLinks = null, IReadOnlyList<DeployFile>? DeployFiles = null);

/// <summary>
/// Lifecycle step impact-analysis — 33-IMPACT-ANALYSIS.md.
/// Deterministic only: the LLM residue (Part H) is not built.
/// </summary>
public static class ImpactPipeline
{
    public const string ArtifactVersion = "2.1.0";
    public const string Structural = "structural";

    private static readonly string[] ImpactRank = ["none", "low", "medium", "high"];

    public static async Task<ImpactArtifact> RunAsync(ImpactInput input, string repositoryRoot, CancellationToken ct)
    {
        var index = await CodeIndex.BuildAsync(repositoryRoot, ct);
        var engine = new RuleEngine(index, input.Projects, input.Tests, input.EntryPoints, input.HostLinks, input.DeployFiles);
        var warnings = new List<Warning>();
        var workItems = new List<WorkItemImpact>();

        foreach (var seed in input.WorkItems.OrderBy(w => w.ItemId, StringComparer.Ordinal).ThenBy(w => w.ProjectPath, StringComparer.Ordinal))
        {
            if (!input.Items.TryGetValue(seed.ItemId, out var item) || item.Resolutions.Count == 0)
            {
                warnings.Add(new Warning { Code = "ITEM_WITHOUT_RESOLUTIONS", Message = $"{seed.ItemId} on {seed.ProjectPath}: no live resolution to analyse.", Severity = WarningSeverities.Warning });
                continue;
            }

            // Part C: the default always; the chosen one where decided.
            var fallback = item.Resolutions.FirstOrDefault(r => r.IsDefault);
            var defaultRole = fallback is null ? "presumptive" : "default";
            fallback ??= item.Resolutions.OrderBy(r => Array.IndexOf(ImpactRank, r.ConsumerImpact)).ThenBy(r => r.Id, StringComparer.Ordinal).First();
            var chosen = input.Decisions.TryGetValue(item.ItemId, out var chosenId) ? item.Resolutions.FirstOrDefault(r => r.Id == chosenId) : null;
            var computed = new List<(ResolutionInfo Resolution, List<string> Roles)> { (fallback, [defaultRole]) };
            if (chosen is not null)
            {
                if (chosen.Id == fallback.Id) computed[0].Roles.Add("chosen");
                else computed.Add((chosen, ["chosen"]));
            }

            var effective = (chosen ?? fallback).Id;
            var resolutions = new List<ResolutionImpact>();
            foreach (var (resolution, roles) in computed)
            {
                var explicitRules = resolution.Rules.Count > 0;
                var result = engine.Evaluate(explicitRules ? resolution.Rules : ImpactRule.Default, seed.Seeds, seed.ProjectPath);
                resolutions.Add(new ResolutionImpact
                {
                    ResolutionId = resolution.Id, Name = resolution.Name, Roles = roles, Effective = resolution.Id == effective,
                    RulesSource = explicitRules ? "explicit" : "default", DecisionResolutionId = chosen?.Id,
                    Counts = ActionCounts.Of(result.Entries.Select(e => e.Action)),
                    Changed = result.Entries.Count(e => Actions.IsChange(e.Action)),
                    Created = result.Entries.Count(e => e.Action == Actions.Create),
                    ToReview = result.Entries.Count(e => e.Action == Actions.Review),
                    Confirmed = result.Entries.Count(e => e.Certainty == Certainties.Confirmed),
                    Possible = result.Entries.Count(e => e.Certainty == Certainties.Possible),
                    Entries = result.Entries, KnownLimits = result.KnownLimits, DeferredRules = result.DeferredRules,
                });
            }

            workItems.Add(new WorkItemImpact
            {
                ItemId = item.ItemId, ItemName = item.Name, ProjectPath = seed.ProjectPath, ProjectId = seed.ProjectId,
                EffectiveResolutionId = effective, Resolutions = resolutions,
                PendingResolutions = item.Resolutions.Where(r => computed.All(c => c.Resolution.Id != r.Id))
                    .OrderBy(r => r.Id, StringComparer.Ordinal).Select(r => new PendingResolution { ResolutionId = r.Id, Name = r.Name }).ToList(),
            });
        }

        var rollup = Rollup(workItems.SelectMany(w => w.Resolutions.Where(r => r.Effective).SelectMany(r => r.Entries.Select(e =>
            (Key: e.FilePath ?? "create:" + e.ProposedPath, Item: new RollupWorkItem
            {
                ItemId = w.ItemId, ProjectPath = w.ProjectPath, ResolutionId = r.ResolutionId, Action = e.Action, Source = Structural,
                RuleIds = e.Reasons.Select(x => x.RuleId).Distinct().Order(StringComparer.Ordinal).ToList(),
            })))));
        var effectiveEntries = workItems.SelectMany(w => w.Resolutions.Where(r => r.Effective).SelectMany(r => r.Entries)).ToList();
        var changed = effectiveEntries.Where(e => Actions.IsChange(e.Action)).Select(e => e.FilePath!).ToHashSet(StringComparer.Ordinal);
        return new ImpactArtifact
        {
            ArtifactVersion = ArtifactVersion, RepositoryId = input.RepositoryId, RepositorySlug = input.RepositorySlug, EngagementId = input.EngagementId,
            Summary = new ImpactSummary
            {
                WorkItems = workItems.Count,
                Changes = effectiveEntries.Count(e => Actions.IsChange(e.Action)),
                FilesChanged = changed.Count,
                ByAction = ActionCounts.Of(effectiveEntries.Select(e => e.Action)),
                NewFiles = effectiveEntries.Where(e => e.Action == Actions.Create).Select(e => e.ProposedPath).Distinct().Count(),
                FilesToReview = effectiveEntries.Where(e => e.Action == Actions.Review && !changed.Contains(e.FilePath!)).Select(e => e.FilePath).Distinct().Count(),
                Hotspots = rollup.Count(r => r.Hotspot),
                Conflicts = rollup.Sum(r => r.Conflicts.Count),
            },
            WorkItems = workItems, Rollup = rollup,
            Warnings = warnings.OrderBy(w => w.Message, StringComparer.Ordinal).ToList(),
        };
    }

    /// <summary>
    /// Part G, from effective resolutions: a file touched by three or more
    /// work items is a hotspot; delete with any non-delete, or two creates at
    /// one path, is a conflict, reported naming both work items. Rewrite with
    /// update, or update with update, is ordering, not conflict. The backend
    /// recomputes this with client rows after dependency-and-context-map (app/impact/rollup.py)
    /// and must agree.
    /// </summary>
    public static IReadOnlyList<FileRollup> Rollup(IEnumerable<(string Key, RollupWorkItem Item)> entries)
    {
        var result = new List<FileRollup>();
        foreach (var group in entries.GroupBy(e => e.Key, StringComparer.Ordinal).OrderBy(g => g.Key, StringComparer.Ordinal))
        {
            var items = group.Select(g => g.Item).DistinctBy(i => i.Key)
                .OrderBy(i => i.ItemId, StringComparer.Ordinal).ThenBy(i => i.ProjectPath, StringComparer.Ordinal).ThenBy(i => i.Source, StringComparer.Ordinal).ToList();
            var distinct = items.Select(i => (i.ItemId, i.ProjectPath)).Distinct().Count();
            var conflicts = new List<RollupConflict>();
            for (var a = 0; a < items.Count; a++)
            {
                for (var b = a + 1; b < items.Count; b++)
                {
                    var (first, second) = (items[a], items[b]);
                    if (first.ItemId == second.ItemId && first.ProjectPath == second.ProjectPath) continue;
                    var kind = (first.Action == Actions.Delete) != (second.Action == Actions.Delete) ? "delete_with_change"
                        : first.Action == Actions.Create && second.Action == Actions.Create ? "create_same_path"
                        : null;
                    if (kind is not null) conflicts.Add(new RollupConflict { Kind = kind, First = first, Second = second });
                }
            }

            result.Add(new FileRollup { FileKey = group.Key, WorkItems = items, Hotspot = distinct >= 3, Conflicts = conflicts });
        }

        return result;
    }
}
