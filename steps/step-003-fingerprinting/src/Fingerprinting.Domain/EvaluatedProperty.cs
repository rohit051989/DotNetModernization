namespace Fingerprinting.Domain;

/// <summary>
/// An MSBuild-evaluated property that differs from step 2's raw XML parse.
/// Both values are kept — see 21-APPLICATION-FINGERPRINTING.md Part A7 — never
/// let the evaluated value silently erase the raw one.
/// </summary>
public sealed record EvaluatedProperty
{
    public string? Raw { get; init; }
    public string? Evaluated { get; init; }
    public required string Source { get; init; }
}

/// <summary>
/// Where an <see cref="EvaluatedProperty"/> came from.
/// </summary>
public static class EvaluatedPropertySources
{
    public const string MsbuildEvaluated = "MSBUILD_EVALUATED";
    public const string RawFallback = "RAW_FALLBACK";
}
