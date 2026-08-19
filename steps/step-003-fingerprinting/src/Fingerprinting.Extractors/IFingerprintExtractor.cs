namespace Fingerprinting.Extractors;

/// <summary>
/// One modular fingerprint extractor. Each extractor produces signals and
/// evidence, never a final classification — see
/// step-3-application-fingerprinting.md section 30.
/// </summary>
public interface IFingerprintExtractor
{
    string Name { get; }

    bool CanProcess(ProjectContext context);

    Task<ExtractorResult> ExtractAsync(ProjectContext context, CancellationToken cancellationToken);
}
