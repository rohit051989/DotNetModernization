using System.Text.RegularExpressions;
using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Registry 1.12.0: build and pipeline files that assume Windows. <c>WINDOWS_BUILD_PIPELINE</c>, one per finding:
/// <list type="bullet">
/// <item>a Windows batch script (<c>.bat</c>, <c>.cmd</c>);</item>
/// <item>a CI workflow (GitHub Actions, Azure Pipelines, GitLab CI) that runs on a Windows agent: a
/// <c>runs-on</c>, <c>runner</c>, <c>vmImage</c>, <c>image</c> or <c>pool</c> naming windows, or a reusable workflow
/// whose name says windows;</item>
/// <item>a Jenkinsfile with a Windows agent label, or <c>bat</c> / <c>powershell</c> steps.</item>
/// </list>
/// The value names the file kind and what was found, located at its line. Text only: nothing is run.
/// </summary>
public static class WindowsBuild
{
    public const string WindowsBuildPipeline = "WINDOWS_BUILD_PIPELINE";

    private static readonly Regex YamlWindowsAgent = new(
        @"^\s*-?\s*(?<key>runs-on|runner|vmImage|image|pool|os)\s*:\s*['""]?(?<value>[^'""\s#]*windows[^'""\s#]*)",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex YamlWindowsWorkflow = new(@"^\s*-?\s*uses\s*:\s*\S*windows\S*", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex JenkinsWindowsLabel = new(@"\blabel\s*['""(]\s*['""]?(?<label>[^'"")]*windows[^'"")]*)", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex JenkinsWindowsStep = new(@"\b(?<step>bat|powershell)\s*[('""]", RegexOptions.CultureInvariant);

    public sealed record Finding(string Value, int Line);

    public static bool IsCandidate(string relativePath)
    {
        var name = Path.GetFileName(relativePath);
        var extension = Path.GetExtension(relativePath);
        return extension.Equals(".bat", StringComparison.OrdinalIgnoreCase) || extension.Equals(".cmd", StringComparison.OrdinalIgnoreCase)
               || IsJenkinsfile(name) || IsPipelineYaml(relativePath);
    }

    private static bool IsJenkinsfile(string name) =>
        name.Equals("Jenkinsfile", StringComparison.OrdinalIgnoreCase) || name.EndsWith(".jenkinsfile", StringComparison.OrdinalIgnoreCase);

    private static bool IsPipelineYaml(string relativePath)
    {
        var path = relativePath.Replace('\\', '/');
        var name = Path.GetFileName(path);
        var yaml = name.EndsWith(".yml", StringComparison.OrdinalIgnoreCase) || name.EndsWith(".yaml", StringComparison.OrdinalIgnoreCase);
        return yaml && (path.Contains(".github/workflows/", StringComparison.OrdinalIgnoreCase)
                        || name.StartsWith("azure-pipelines", StringComparison.OrdinalIgnoreCase)
                        || name.Equals(".gitlab-ci.yml", StringComparison.OrdinalIgnoreCase));
    }

    public static IReadOnlyList<Finding> Findings(string relativePath, string text)
    {
        var name = Path.GetFileName(relativePath);
        var extension = Path.GetExtension(relativePath);
        if (extension.Equals(".bat", StringComparison.OrdinalIgnoreCase) || extension.Equals(".cmd", StringComparison.OrdinalIgnoreCase))
        {
            return [new Finding($"Windows batch script {name}", 1)];
        }

        var findings = new List<Finding>();
        var lines = text.Replace("\r\n", "\n").Split('\n');
        for (var i = 0; i < lines.Length; i++)
        {
            var line = lines[i];
            if (IsJenkinsfile(name))
            {
                if (JenkinsWindowsLabel.Match(line) is { Success: true } label)
                {
                    findings.Add(new Finding($"Jenkins agent label {label.Groups["label"].Value.Trim()}", i + 1));
                }

                if (JenkinsWindowsStep.Match(line) is { Success: true } step && !line.TrimStart().StartsWith("//", StringComparison.Ordinal))
                {
                    findings.Add(new Finding($"Jenkins {step.Groups["step"].Value} step", i + 1));
                }
            }
            else if (YamlWindowsAgent.Match(line) is { Success: true } agent)
            {
                findings.Add(new Finding($"{agent.Groups["key"].Value}: {agent.Groups["value"].Value}", i + 1));
            }
            else if (YamlWindowsWorkflow.Match(line) is { Success: true } workflow)
            {
                findings.Add(new Finding($"Windows workflow {workflow.Value.Trim().TrimStart('-').Trim()}", i + 1));
            }
        }

        return findings;
    }

    public static IEnumerable<Signal> Signals(string filePath, string relativePath, string extractor)
    {
        if (!IsCandidate(relativePath)) return [];
        string text;
        try
        {
            text = File.ReadAllText(filePath);
        }
        catch (IOException)
        {
            return [];
        }

        return Findings(relativePath, text).GroupBy(f => f.Value).Select(g => new Signal
        {
            Name = WindowsBuildPipeline,
            Category = SignalCategories.DeploymentIndicator,
            Type = SignalTypes.ConfigElement,
            Value = g.Key,
            SourceType = EvidenceSourceTypes.DeploymentScript,
            SourcePath = relativePath,
            OccurrenceCount = g.Count(),
            Evidence = g.Select(f => new Evidence { LineStart = f.Line, LineEnd = f.Line }).ToList(),
            Extractor = extractor,
            ExtractionConfidence = 0.90m,
        });
    }
}
