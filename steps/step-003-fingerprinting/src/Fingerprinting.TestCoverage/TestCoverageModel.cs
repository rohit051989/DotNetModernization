using System.Text.Json.Serialization;
using Fingerprinting.Domain;

namespace Fingerprinting.TestCoverage;

/// <summary>
/// Artifact <c>test-coverage@1.0.0</c> — 32-STEP-008-TEST-COVERAGE.md Part J.
/// Phase 1 (Part L): discovery, classification, mapping, buckets, existing
/// coverage reports and CI maturity. No LLM, no test execution. Deterministic
/// for a given commit: every list is sorted, nothing time-dependent is in it.
/// </summary>
public sealed record TestCoverageArtifact
{
    public required string ArtifactVersion { get; init; }
    public required Guid RepositoryId { get; init; }
    public required string RepositorySlug { get; init; }
    public string? CommitSha { get; init; }
    public required TestCoverageSummary Summary { get; init; }
    public required IReadOnlyList<TestProjectInfo> TestProjects { get; init; }
    public required IReadOnlyList<TestClassInfo> TestClasses { get; init; }
    public required IReadOnlyList<TestMapping> Mappings { get; init; }
    public required IReadOnlyList<SourceProjectCoverage> Projects { get; init; }
    public required IReadOnlyList<SourceFileCoverage> SourceFiles { get; init; }
    public required IReadOnlyList<CoverageReportInfo> CoverageReports { get; init; }
    public required CiMaturity CiMaturity { get; init; }
    public required IReadOnlyList<Warning> Warnings { get; init; }
}

public sealed record TestCoverageSummary
{
    public required int TestProjects { get; init; }
    public required int TestClasses { get; init; }
    public required int TestMethods { get; init; }
    public required TestTypeCounts TestClassesByType { get; init; }
    public required int SourceFiles { get; init; }
    public required BucketCounts SourceFilesByBucket { get; init; }
    public required int Mappings { get; init; }
    public required int CoverageReports { get; init; }
    public required int SourceFilesMeasured { get; init; }
}

/// <summary>Counts per test type. A record, not a dictionary: its keys are
/// written in a fixed order whatever order they were read in — the cache
/// stores the artifact as JSONB, which reorders object keys, and a reused
/// result must be byte-identical to the computed one (Part J).</summary>
public sealed record TestTypeCounts
{
    [JsonPropertyName("unit")] public int Unit { get; init; }
    [JsonPropertyName("integration")] public int Integration { get; init; }
    [JsonPropertyName("functional")] public int Functional { get; init; }
    [JsonPropertyName("smoke")] public int Smoke { get; init; }
    [JsonPropertyName("unclassified")] public int Unclassified { get; init; }

    public static TestTypeCounts Of(IEnumerable<string> types)
    {
        var list = types.ToList();
        return new TestTypeCounts
        {
            Unit = list.Count(t => t == TestTypes.Unit), Integration = list.Count(t => t == TestTypes.Integration),
            Functional = list.Count(t => t == TestTypes.Functional), Smoke = list.Count(t => t == TestTypes.Smoke),
            Unclassified = list.Count(t => t == TestTypes.Unclassified),
        };
    }
}

/// <summary>Source files per bucket; a record for the same reason as <see cref="TestTypeCounts"/>.</summary>
public sealed record BucketCounts
{
    [JsonPropertyName("has_tests")] public int HasTests { get; init; }
    [JsonPropertyName("missing_tests")] public int MissingTests { get; init; }
    [JsonPropertyName("no_testable_logic")] public int NoTestableLogic { get; init; }

    public static BucketCounts Of(IEnumerable<string> buckets)
    {
        var list = buckets.ToList();
        return new BucketCounts
        {
            HasTests = list.Count(b => b == Buckets.HasTests), MissingTests = list.Count(b => b == Buckets.MissingTests),
            NoTestableLogic = list.Count(b => b == Buckets.NoTestableLogic),
        };
    }
}

public static class TestTypes
{
    public const string Unit = "unit";
    public const string Integration = "integration";
    public const string Functional = "functional";
    public const string Smoke = "smoke";
    public const string Unclassified = "unclassified";

    public static readonly IReadOnlyList<string> All = [Unit, Integration, Functional, Smoke, Unclassified];

    /// <summary>Integration, functional and smoke reach real systems by
    /// design (Part E2): never executed during discovery.</summary>
    public static bool ReachesRealSystems(string type) => type is Integration or Functional or Smoke;
}

public static class Buckets
{
    public const string HasTests = "has_tests";
    public const string MissingTests = "missing_tests";
    public const string NoTestableLogic = "no_testable_logic";

    public static readonly IReadOnlyList<string> All = [HasTests, MissingTests, NoTestableLogic];
}

public static class CoverageSources
{
    public const string ExistingReport = "existing_report";
    public const string NotMeasured = "not_measured";
}

public sealed record TestProjectInfo
{
    public required string ProjectPath { get; init; }
    public required string Reason { get; init; }
    public required int TestClasses { get; init; }
    public required TestTypeCounts TestClassesByType { get; init; }
}

/// <summary>One piece of classification evidence (Part B2).</summary>
public sealed record ClassificationEvidence
{
    /// <summary>project_name, category, infrastructure, connection_string, mocking.</summary>
    public required string Kind { get; init; }
    public required string Value { get; init; }
    public required string Indicates { get; init; }
    /// <summary>strong, indicative or supporting.</summary>
    public required string Strength { get; init; }
}

public sealed record TestClassInfo
{
    public required string ProjectPath { get; init; }
    public required string FilePath { get; init; }
    public required string ClassName { get; init; }
    public string? Namespace { get; init; }
    public required int LineStart { get; init; }
    public required string TestType { get; init; }
    public required string ClassificationReason { get; init; }
    public required IReadOnlyList<ClassificationEvidence> Evidence { get; init; }
    public required int TestCount { get; init; }
}

public static class MappingMethods
{
    public const string TypeReference = "type_reference";
    public const string TypeReferenceAndNaming = "type_reference+naming";
    public const string NamingOnly = "naming_only";
}

/// <summary>A test class exercising a production type (Part C).</summary>
public sealed record TestMapping
{
    public required string SourceFile { get; init; }
    public required string ProductionType { get; init; }
    public required string TestFile { get; init; }
    public required string TestClass { get; init; }
    public required string TestType { get; init; }
    /// <summary>The test methods whose bodies reference the type; all of them
    /// when the class references it outside a method (a field, the
    /// constructor).</summary>
    public required IReadOnlyList<string> TestMethods { get; init; }
    public required string Method { get; init; }
    public required decimal Confidence { get; init; }
    public required IReadOnlyList<string> Evidence { get; init; }
}

public sealed record SourceProjectCoverage
{
    public required string ProjectPath { get; init; }
    public required int Files { get; init; }
    public required int HasTests { get; init; }
    public required int MissingTests { get; init; }
    public required int NoTestableLogic { get; init; }
    public decimal? UnitLinePct { get; init; }
    public string? UnitNotMeasuredReason { get; init; }
    public decimal? IntegrationLinePct { get; init; }
    public string? IntegrationNotMeasuredReason { get; init; }
}

public sealed record SourceFileCoverage
{
    public required string ProjectPath { get; init; }
    public required string FilePath { get; init; }
    public required string Bucket { get; init; }
    /// <summary>Members with a non-trivial body (Part D).</summary>
    public required int TestableMembers { get; init; }
    public required IReadOnlyList<string> TestFiles { get; init; }
    public required IReadOnlyList<string> TestTypes { get; init; }
    public required string CoverageSource { get; init; }
    public decimal? LinePct { get; init; }
    public decimal? BranchPct { get; init; }
    /// <summary>Always set when <see cref="CoverageSource"/> is not_measured:
    /// unknown is never shown as 0% (Part E1).</summary>
    public string? NotMeasuredReason { get; init; }
    public decimal? UnitLinePct { get; init; }
    public string? UnitNotMeasuredReason { get; init; }
    public decimal? IntegrationLinePct { get; init; }
    public string? IntegrationNotMeasuredReason { get; init; }
}

public sealed record CoverageReportInfo
{
    public required string Path { get; init; }
    /// <summary>cobertura, opencover or lcov.</summary>
    public required string Format { get; init; }
    /// <summary>unit, integration or unattributed (counts toward the combined figure only).</summary>
    public required string Attribution { get; init; }
    public required string AttributionReason { get; init; }
    public required int FilesInReport { get; init; }
    public required int FilesMatched { get; init; }
    public required IReadOnlyList<string> UnmatchedPaths { get; init; }
}

/// <summary>Part H, per repository.</summary>
public sealed record CiMaturity
{
    public required bool HasPipeline { get; init; }
    public required bool RunsTests { get; init; }
    public required bool CollectsCoverage { get; init; }
    public required bool PublishesCoverage { get; init; }
    public required bool EnforcesCoverageGate { get; init; }
    public required IReadOnlyList<CiPipeline> Pipelines { get; init; }
    public required IReadOnlyList<CiEvidence> Evidence { get; init; }
}

public sealed record CiPipeline
{
    public required string Path { get; init; }
    /// <summary>azure_pipelines, github_actions, jenkins or teamcity.</summary>
    public required string System { get; init; }
}

public sealed record CiEvidence
{
    public required string Fact { get; init; }
    public required string Path { get; init; }
    public required int Line { get; init; }
    public required string Text { get; init; }
}
