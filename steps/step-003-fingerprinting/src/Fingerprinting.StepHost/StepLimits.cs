using System.Text.Json;

namespace Fingerprinting.StepHost;

/// <summary>
/// What the engine passes a step in <c>step_context</c> (rbc-release-5; backend/app/workflow/runtime/executor.py): the
/// limits within the step — one project's load, one file's analysis — and the folder that outlives this execution,
/// where the step keeps what it has finished so a rerun continues from there.
/// </summary>
public static class StepLimits
{
    /// <summary>One project's load, and one file's analysis: (project, file), each null when the engine gave none.</summary>
    public static (TimeSpan? ProjectLoad, TimeSpan? File) Within(StepContextEnvelope context)
    {
        var limits = Element(context.StepContext, "time_limits");
        return (Number(limits, "project_seconds") is { } project ? TimeSpan.FromSeconds(project) : null,
                Number(limits, "file_seconds") is { } file ? TimeSpan.FromSeconds(file) : null);
    }

    /// <summary>The checkpoint folder for this step and repository, or null when the engine gave none.</summary>
    public static string? CheckpointDirectory(StepContextEnvelope context) =>
        Element(context.StepContext, "checkpoint_dir") is { ValueKind: JsonValueKind.String } value ? value.GetString() : null;

    private static JsonElement? Element(JsonElement? parent, string name) =>
        parent is { ValueKind: JsonValueKind.Object } p && p.TryGetProperty(name, out var child) ? child : null;

    private static double? Number(JsonElement? parent, string name) =>
        Element(parent, name) is { ValueKind: JsonValueKind.Number } n ? n.GetDouble() : null;
}
