using System.Text.Json;
using System.Text.Json.Serialization;
using Fingerprinting.Domain;

namespace Fingerprinting.Impact;

/// <summary>
/// Artifact <c>impact-analysis@2.1.0</c> — 33-IMPACT-ANALYSIS.md
/// Part I. 2.0.0: three figures everywhere — files changed (update, rewrite,
/// delete), new files (create) and files to review, never added together —
/// and a repository summary whose figures reconcile; entries carry details
/// (the config element an update edits, the types a file loses). 2.1.0
/// (additive): each rollup work item names the rules that put it on the
/// file, so a conflict can be traced to the catalog rule pair behind it. Per work item (a found item on a project), the files its
/// conversion touches under the default resolution and, where decided, the
/// chosen one; and per file, every work item touching it under its effective
/// resolution, with hotspots and conflicts. Structural only: client impact is
/// added by dependency-and-context-map. Deterministic for given code and decisions.
/// </summary>
public sealed record ImpactArtifact
{
    public required string ArtifactVersion { get; init; }
    public required Guid RepositoryId { get; init; }
    public required string RepositorySlug { get; init; }
    public required string EngagementId { get; init; }
    public required ImpactSummary Summary { get; init; }
    public required IReadOnlyList<WorkItemImpact> WorkItems { get; init; }
    public required IReadOnlyList<FileRollup> Rollup { get; init; }
    public required IReadOnlyList<Warning> Warnings { get; init; }
}

/// <summary>Under each work item's effective resolution, structural only.
/// <c>Changes</c> counts one per file per work item and equals
/// <c>ByAction</c>'s update + rewrite + delete; <c>FilesChanged</c> counts
/// those files once. Creates and review are counted apart and never added to
/// the changes: <c>FilesToReview</c> is files only marked for review, by no
/// work item changed.</summary>
public sealed record ImpactSummary
{
    public required int WorkItems { get; init; }
    public required int Changes { get; init; }
    public required int FilesChanged { get; init; }
    public required ActionCounts ByAction { get; init; }
    public required int NewFiles { get; init; }
    public required int FilesToReview { get; init; }
    public required int Hotspots { get; init; }
    public required int Conflicts { get; init; }
}

/// <summary>A record, not a dictionary, so the key order never depends on how it was read.</summary>
public sealed record ActionCounts
{
    [JsonPropertyName("update")] public int Update { get; init; }
    [JsonPropertyName("rewrite")] public int Rewrite { get; init; }
    [JsonPropertyName("delete")] public int Delete { get; init; }
    [JsonPropertyName("create")] public int Create { get; init; }
    [JsonPropertyName("review")] public int Review { get; init; }

    public static ActionCounts Of(IEnumerable<string> actions)
    {
        var list = actions.ToList();
        return new ActionCounts
        {
            Update = list.Count(a => a == Actions.Update), Rewrite = list.Count(a => a == Actions.Rewrite),
            Delete = list.Count(a => a == Actions.Delete), Create = list.Count(a => a == Actions.Create),
            Review = list.Count(a => a == Actions.Review),
        };
    }
}

public static class Actions
{
    public const string Update = "update";
    public const string Rewrite = "rewrite";
    public const string Delete = "delete";
    public const string Create = "create";
    public const string Review = "review";

    /// <summary>A traversal rule that only leads to later rules (the project
    /// hosting a contract, where its controller goes): nothing happens to the
    /// files it reaches, so they are not entries.</summary>
    public const string None = "none";

    /// <summary>The actions that change an existing file.</summary>
    public static bool IsChange(string action) => action is Update or Rewrite or Delete;

    /// <summary>Part F: where several rules reach one file, the strongest is kept.</summary>
    public static int Strength(string action) => action switch
    {
        Delete => 4, Rewrite => 3, Update => 2, Review => 1, _ => 0,
    };
}

public static class Certainties
{
    public const string Confirmed = "confirmed";
    public const string Possible = "possible";
}

public sealed record WorkItemImpact
{
    public required string ItemId { get; init; }
    public required string ItemName { get; init; }
    public required string ProjectPath { get; init; }
    public Guid? ProjectId { get; init; }
    public required string EffectiveResolutionId { get; init; }
    public required IReadOnlyList<ResolutionImpact> Resolutions { get; init; }
    /// <summary>Not analysed (Part C): shown as pending.</summary>
    public required IReadOnlyList<PendingResolution> PendingResolutions { get; init; }
}

public sealed record PendingResolution
{
    public required string ResolutionId { get; init; }
    public required string Name { get; init; }
}

public sealed record ResolutionImpact
{
    public required string ResolutionId { get; init; }
    public required string Name { get; init; }
    /// <summary>default, presumptive (an item with no default: its lowest consumer impact), chosen.</summary>
    public required IReadOnlyList<string> Roles { get; init; }
    public required bool Effective { get; init; }
    /// <summary>explicit, or default (the resolution has no rules: its evidence, update).</summary>
    public required string RulesSource { get; init; }
    public string? DecisionResolutionId { get; init; }
    public required ActionCounts Counts { get; init; }
    /// <summary>Existing files updated, rewritten or deleted.</summary>
    public required int Changed { get; init; }
    /// <summary>New files to create.</summary>
    public required int Created { get; init; }
    /// <summary>Files a person should check; not changes, never added to them.</summary>
    public required int ToReview { get; init; }
    public required int Confirmed { get; init; }
    public required int Possible { get; init; }
    public required IReadOnlyList<ImpactEntry> Entries { get; init; }
    /// <summary>Untraceable paths detected (reflection): impact through them is not claimed.</summary>
    public required IReadOnlyList<string> KnownLimits { get; init; }
    /// <summary>Rules left to dependency-and-context-map (client_call_sites).</summary>
    public required IReadOnlyList<string> DeferredRules { get; init; }
}

public sealed record ImpactEntry
{
    /// <summary>Null for create.</summary>
    public string? FilePath { get; init; }
    public string? ProposedPath { get; init; }
    public string? Description { get; init; }
    public required string Action { get; init; }
    public required string Certainty { get; init; }
    public required IReadOnlyList<ImpactReason> Reasons { get; init; }
    public required IReadOnlyList<string> TraversalPaths { get; init; }
    /// <summary>What happens within the file: the config element an update
    /// edits, the types a file loses when it is not deleted whole.</summary>
    public required IReadOnlyList<string> Details { get; init; }
}

public sealed record ImpactReason
{
    public required string RuleId { get; init; }
    public required string Action { get; init; }
    public required string Reason { get; init; }
}

public sealed record FileRollup
{
    /// <summary>The file's path, or "create:" + a proposed path.</summary>
    public required string FileKey { get; init; }
    public required IReadOnlyList<RollupWorkItem> WorkItems { get; init; }
    public required bool Hotspot { get; init; }
    public required IReadOnlyList<RollupConflict> Conflicts { get; init; }
}

public sealed record RollupWorkItem
{
    public required string ItemId { get; init; }
    public required string ProjectPath { get; init; }
    public required string ResolutionId { get; init; }
    public required string Action { get; init; }
    public required string Source { get; init; }
    /// <summary>The rules that reached the file, sorted: a conflict produced by
    /// the same rule pair on every instance of a pattern is the catalog's to fix.</summary>
    public required IReadOnlyList<string> RuleIds { get; init; }

    /// <summary>Identity within one file's rollup (records compare lists by reference).</summary>
    [JsonIgnore] public string Key => $"{ItemId}|{ProjectPath}|{ResolutionId}|{Action}|{Source}|{string.Join(",", RuleIds)}";
}

public sealed record RollupConflict
{
    public required string Kind { get; init; }
    public required RollupWorkItem First { get; init; }
    public required RollupWorkItem Second { get; init; }
}

/// <summary>One impact rule as stored in the catalog (33-IMPACT-ANALYSIS Part D);
/// validated by the backend before it reaches here
/// (backend/app/items/impact_rules.py).</summary>
public sealed record ImpactRule
{
    [JsonPropertyName("id")] public required string Id { get; init; }
    [JsonPropertyName("from")] public JsonElement? From { get; init; }
    [JsonPropertyName("select")] public string? Select { get; init; }
    [JsonPropertyName("traverse")] public string? Traverse { get; init; }
    [JsonPropertyName("filter")] public Dictionary<string, JsonElement>? Filter { get; init; }
    [JsonPropertyName("kind")] public string? Kind { get; init; }
    [JsonPropertyName("path")] public string? Path { get; init; }
    /// <summary>project_files: a name or path below the project directory, <c>*</c> within a name.</summary>
    [JsonPropertyName("pattern")] public string? Pattern { get; init; }
    [JsonPropertyName("action")] public required string Action { get; init; }
    [JsonPropertyName("reason")] public string? Reason { get; init; }
    [JsonPropertyName("create")] public string? Create { get; init; }
    [JsonPropertyName("for_each")] public string? ForEach { get; init; }
    [JsonPropertyName("proposed_path")] public string? ProposedPath { get; init; }

    public IReadOnlyList<string> Sources() => From switch
    {
        { ValueKind: JsonValueKind.Array } array => array.EnumerateArray().Select(e => e.GetString()!).ToList(),
        { ValueKind: JsonValueKind.String } one => [one.GetString()!],
        _ => [],
    };

    /// <summary>Part D: a resolution with no rules gets this one.</summary>
    public static readonly IReadOnlyList<ImpactRule> Default =
    [
        new()
        {
            Id = "evidence", From = JsonDocument.Parse("\"seed\"").RootElement.Clone(), Select = "self", Action = Actions.Update,
            Reason = "Default rule: the work item's own evidence files. This resolution declares no impact rules of its own.",
        },
    ];
}
