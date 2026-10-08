using System.Text.RegularExpressions;
using Fingerprinting.Analysis;

namespace Fingerprinting.TestCoverage;

/// <summary>
/// Part H: CI maturity from pipeline definitions, per repository.
///
/// Pipelines: <c>azure-pipelines*.yml</c> anywhere and YAML under
/// <c>.azure-pipelines/</c>, <c>.azuredevops/</c> or <c>.pipelines/</c>
/// (Azure Pipelines); <c>.github/workflows/*.yml</c> (GitHub Actions);
/// <c>Jenkinsfile*</c> (Jenkins); files under <c>.teamcity/</c> (TeamCity).
///
/// Each fact is a line-level text match, recorded as evidence with its file
/// and line, so a reviewer sees why it is true:
/// <list type="bullet">
/// <item><c>runs_tests</c> — <c>dotnet test</c>, <c>dotnet vstest</c>,
/// <c>VSTest@</c>, a <c>DotNetCoreCLI</c> <c>command: test</c>,
/// vstest.console, nunit3-console, xunit.console.</item>
/// <item><c>collects_coverage</c> — <c>--collect</c> code coverage, coverlet,
/// <c>CollectCoverage=true</c>, <c>codeCoverageEnabled: true</c>, dotCover,
/// OpenCover.</item>
/// <item><c>publishes_coverage</c> — <c>PublishCodeCoverageResults@</c>,
/// Codecov, Coveralls, Jenkins <c>cobertura</c>/<c>recordCoverage</c>/
/// <c>publishCoverage</c>, or an <c>upload-artifact</c> whose next lines name
/// a coverage file.</item>
/// <item><c>enforces_coverage_gate</c> — coverlet's <c>Threshold</c>,
/// <c>--threshold</c>, <c>fail_under</c>/<c>failUnder</c>,
/// <c>minimum_coverage</c>, a SonarQube quality gate wait.</item>
/// </list>
/// </summary>
public static class CiMaturityScanner
{
    private static readonly (string Fact, Regex Pattern)[] Rules =
    [
        ("runs_tests", new(@"(?i)\bdotnet\s+(test|vstest)\b|\bVSTest@\d|\bcommand:\s*['""]?test['""]?\s*$|vstest\.console|nunit3-console|xunit\.console", RegexOptions.Compiled)),
        ("collects_coverage", new(@"(?i)--collect[:\s=]+['""]?(xplat\s+)?code\s+coverage|\bcoverlet\b|CollectCoverage\s*=\s*true|codeCoverageEnabled:\s*true|\bdotcover\b|\bopencover\b", RegexOptions.Compiled)),
        ("publishes_coverage", new(@"(?i)PublishCodeCoverageResults@\d|\bcodecov\b|\bcoveralls\b|\bpublishCoverage\b|\brecordCoverage\b|\bcobertura\s*\(|\bcobertura\s+coberturaReportFile", RegexOptions.Compiled)),
        ("enforces_coverage_gate", new(@"(?i)/p:Threshold\s*=|\bThreshold\s*=\s*\d|--threshold\b|\bfail_?under\b|\bminimum[_-]?coverage\b|sonar\.qualitygate\.wait\s*=\s*true", RegexOptions.Compiled)),
    ];

    private static readonly Regex UploadArtifact = new(@"(?i)upload-artifact|PublishBuildArtifacts@\d|PublishPipelineArtifact@\d|archiveArtifacts", RegexOptions.Compiled);
    private static readonly Regex CoverageFile = new(@"(?i)coverage|cobertura|lcov|opencover", RegexOptions.Compiled);

    public static CiMaturity Scan(string repositoryRoot, CancellationToken ct)
    {
        var pipelines = new List<CiPipeline>();
        foreach (var absolute in FileSystemWalk.EnumerateFiles(repositoryRoot, ct))
        {
            var relative = FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, absolute);
            if (SystemOf(relative) is { } system) pipelines.Add(new CiPipeline { Path = relative, System = system });
        }

        pipelines = pipelines.OrderBy(p => p.Path, StringComparer.Ordinal).ToList();
        var evidence = new List<CiEvidence>();
        foreach (var pipeline in pipelines)
        {
            var lines = File.ReadAllLines(Path.Combine(repositoryRoot, pipeline.Path));
            for (var i = 0; i < lines.Length; i++)
            {
                var line = lines[i];
                if (line.TrimStart().StartsWith('#') || line.TrimStart().StartsWith("//", StringComparison.Ordinal)) continue;
                foreach (var (fact, pattern) in Rules)
                {
                    if (pattern.IsMatch(line)) evidence.Add(Evidence(fact, pipeline.Path, i, line));
                }

                if (UploadArtifact.IsMatch(line) && lines.Skip(i).Take(7).Any(l => CoverageFile.IsMatch(l)))
                {
                    evidence.Add(Evidence("publishes_coverage", pipeline.Path, i, line));
                }
            }
        }

        evidence = evidence.Distinct().OrderBy(e => e.Fact, StringComparer.Ordinal).ThenBy(e => e.Path, StringComparer.Ordinal).ThenBy(e => e.Line).ToList();
        bool Has(string fact) => evidence.Any(e => e.Fact == fact);
        return new CiMaturity
        {
            HasPipeline = pipelines.Count > 0,
            RunsTests = Has("runs_tests"),
            CollectsCoverage = Has("collects_coverage"),
            PublishesCoverage = Has("publishes_coverage"),
            EnforcesCoverageGate = Has("enforces_coverage_gate"),
            Pipelines = pipelines,
            Evidence = evidence,
        };
    }

    private static CiEvidence Evidence(string fact, string path, int index, string line) =>
        new() { Fact = fact, Path = path, Line = index + 1, Text = line.Trim().Length > 200 ? line.Trim()[..200] : line.Trim() };

    public static string? SystemOf(string relativePath)
    {
        var path = relativePath.Replace('\\', '/');
        var name = Path.GetFileName(path).ToLowerInvariant();
        var lower = path.ToLowerInvariant();
        var yaml = name.EndsWith(".yml", StringComparison.Ordinal) || name.EndsWith(".yaml", StringComparison.Ordinal);
        if (yaml && (lower.StartsWith(".github/workflows/", StringComparison.Ordinal) || lower.Contains("/.github/workflows/"))) return "github_actions";
        if (yaml && (name.StartsWith("azure-pipelines", StringComparison.Ordinal)
                     || lower.Contains(".azure-pipelines/") || lower.Contains(".azuredevops/") || lower.StartsWith(".pipelines/", StringComparison.Ordinal) || lower.Contains("/.pipelines/")))
        {
            return "azure_pipelines";
        }

        if (name.StartsWith("jenkinsfile", StringComparison.Ordinal)) return "jenkins";
        if (lower.StartsWith(".teamcity/", StringComparison.Ordinal) || lower.Contains("/.teamcity/")) return "teamcity";
        return null;
    }
}
