using Fingerprinting.Domain;
using Fingerprinting.Outbound;
using Fingerprinting.Outbound.Cli;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>release 5: every record any outbound test produces is checked as it would be written — the schema,
/// and every required field holding text holds some (Fingerprinting.StepHost.RequiredFields). The tests' detection
/// helpers pass their results through <see cref="Checked"/>.</summary>
public static class Conformance
{
    public static IReadOnlyList<ProjectInvocations> Checked(IReadOnlyList<ProjectInvocations> projects)
    {
        var artifact = new OutboundInventoryArtifact
        {
            ScannerVersion = OutboundPipeline.ScannerVersion,
            RepositoryId = Guid.Parse("11111111-2222-3333-4444-555555555555"),
            RepositorySlug = "fixture",
            SkipSource = "application-fingerprint",
            Summary = OutboundPipeline.Summarise(projects),
            Projects = projects,
        };
        Assert.Empty(OutboundInventoryCli.Problems(artifact));
        return projects;
    }
}
