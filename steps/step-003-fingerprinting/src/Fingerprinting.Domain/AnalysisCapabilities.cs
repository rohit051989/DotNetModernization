namespace Fingerprinting.Domain;

/// <summary>
/// Which analysis levels actually ran for one project, per
/// step-3-application-fingerprinting.md section 20 and
/// 21-STEP-003-FINGERPRINTING.md Part F. Lets a consumer judge a fingerprint's
/// precision ceiling without inferring it from which signals are absent.
/// </summary>
public sealed record AnalysisCapabilities
{
    public bool FileDiscovery { get; init; }
    public bool ProjectMetadataParsed { get; init; }
    public bool MsbuildEvaluated { get; init; }
    public bool SyntaxAnalysis { get; init; }
    public bool SemanticAnalysis { get; init; }
    public bool ConfigurationParsed { get; init; }
    public bool DeploymentArtifactsParsed { get; init; }
    public bool GeneratedCodeExcluded { get; init; }
}
