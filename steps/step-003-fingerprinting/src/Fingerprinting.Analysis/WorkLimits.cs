namespace Fingerprinting.Analysis;

/// <summary>
/// How long one project's load, and one file's analysis, may take within a step (rbc-release-5). Over the limit, the
/// project or file is recorded as "not checked", with the reason, and the step carries on: no single project or file
/// can hold a whole step up. The engine passes them (STEP_PROJECT_SECONDS, STEP_FILE_SECONDS); these are the defaults.
/// </summary>
public sealed record WorkLimits(TimeSpan ProjectLoad, TimeSpan File)
{
    public static WorkLimits Default { get; } = new(TimeSpan.FromSeconds(300), TimeSpan.FromSeconds(60));

    /// <summary>The engine's limits, each falling back to the default.</summary>
    public static WorkLimits From(TimeSpan? projectLoad, TimeSpan? file) => new(projectLoad ?? Default.ProjectLoad, file ?? Default.File);
}
