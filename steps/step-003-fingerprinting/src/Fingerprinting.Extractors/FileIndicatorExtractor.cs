using System.Text.RegularExpressions;
using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Level 1 (file-system) extraction — the file and folder indicators from
/// step-3-application-fingerprinting.md section 7. Never fails to load and
/// works on code that does not compile; proves the pipeline end to end.
/// Same directory exclusions as steps 1 and 2
/// (backend/app/steps/repository_ingest.py SKIP_DIR_NAMES).
///
/// Deployment files (Dockerfile, Kubernetes/OpenShift manifests, Helm charts)
/// are found at two levels. Inside a project directory they are that
/// project's signals, from <see cref="ExtractAsync"/>. Anywhere else in the
/// repository — typically a root <c>deploy/</c>, <c>k8s/</c> or
/// <c>charts/</c> folder — they are repository-level signals, from
/// <see cref="ExtractRepositoryLevel"/>, and land in the artifact's
/// <c>repositorySignals</c>. Item detection must see both when evaluating a
/// project (28-ITEM-AND-CONVERSION-MODEL.md Part E).
/// </summary>
public sealed class FileIndicatorExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "FileIndicatorExtractor";

    public string Name => ExtractorName;

    public const string DockerfileFile = "DOCKERFILE_FILE";
    public const string WebConfigFile = "WEB_CONFIG_FILE";
    public const string Ocp4ManifestFile = "OCP4_MANIFEST_FILE";
    public const string HelmChartFile = "HELM_CHART_FILE";

    private static readonly IReadOnlyDictionary<string, string> ExtensionSignals =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            [".svc"] = "SVC_FILE",
            [".aspx"] = "ASPX_FILE",
            [".ascx"] = "ASCX_FILE",
            [".asmx"] = "ASMX_FILE",
            [".cshtml"] = "CSHTML_FILE",
            [".razor"] = "RAZOR_FILE",
            [".xaml"] = "XAML_FILE",
        };

    private static readonly IReadOnlyDictionary<string, string> FileNameSignals =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["Global.asax"] = "GLOBAL_ASAX_FILE",
            ["Startup.cs"] = "STARTUP_CS_FILE",
            ["Program.cs"] = "PROGRAM_CS_FILE",
            ["web.config"] = WebConfigFile,
        };

    private static readonly IReadOnlyDictionary<string, string> FolderSignals =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["Controllers"] = "CONTROLLERS_FOLDER",
            ["Views"] = "VIEWS_FOLDER",
            ["Pages"] = "PAGES_FOLDER",
            ["App_Start"] = "APP_START_FOLDER",
            ["Services"] = "SERVICES_FOLDER",
            ["Jobs"] = "JOBS_FOLDER",
            ["Tasks"] = "TASKS_FOLDER",
            ["Functions"] = "FUNCTIONS_FOLDER",
        };

    // A Kubernetes/OpenShift manifest: YAML with top-level apiVersion and
    // kind keys. Compose files, CI workflows and Helm values files have
    // neither, so they never match.
    private static readonly Regex ManifestApiVersion = new(@"^apiVersion:\s*\S", RegexOptions.Multiline | RegexOptions.CultureInvariant);
    private static readonly Regex ManifestKind = new(@"^kind:\s*\S", RegexOptions.Multiline | RegexOptions.CultureInvariant);
    private const int ManifestSniffBytes = 64 * 1024;

    public bool CanProcess(ProjectContext context) => Directory.Exists(context.ProjectDirectory);

    public Task<ExtractorResult> ExtractAsync(ProjectContext context, CancellationToken cancellationToken)
    {
        if (!CanProcess(context))
        {
            return Task.FromResult(new ExtractorResult
            {
                Warnings =
                [
                    new Warning
                    {
                        Code = WarningCodes.ProjectDirectoryNotFound,
                        Message = $"Project directory not found on disk: {context.ProjectDirectory}",
                        Severity = WarningSeverities.Warning,
                    },
                ],
            });
        }

        var signals = new List<Signal>();

        foreach (var filePath in FileSystemWalk.EnumerateFiles(context.ProjectDirectory, cancellationToken))
        {
            var fileName = Path.GetFileName(filePath);
            var extension = Path.GetExtension(filePath);
            var relativePath = FileSystemWalk.ToRepositoryRelativePath(context.RepositoryRoot, filePath);

            string? signalName = FileNameSignals.TryGetValue(fileName, out var byName)
                ? byName
                : ExtensionSignals.GetValueOrDefault(extension);

            if (signalName is not null)
            {
                signals.Add(BuildSignal(signalName, relativePath, SignalCategories.FileIndicator));
            }

            if (DeploymentSignal(filePath) is { } deployment)
            {
                signals.Add(BuildSignal(deployment, relativePath, SignalCategories.DeploymentIndicator));
            }
        }

        foreach (var directoryPath in FileSystemWalk.EnumerateDirectories(context.ProjectDirectory, cancellationToken))
        {
            var directoryName = Path.GetFileName(directoryPath.TrimEnd(Path.DirectorySeparatorChar));
            if (FolderSignals.TryGetValue(directoryName, out var signalName))
            {
                signals.Add(BuildSignal(signalName, FileSystemWalk.ToRepositoryRelativePath(context.RepositoryRoot, directoryPath), SignalCategories.FileIndicator));
            }
        }

        return Task.FromResult(new ExtractorResult { Signals = signals });
    }

    /// <summary>
    /// Deployment files anywhere in the repository <b>outside</b> every
    /// fingerprinted project directory — the ones no project's own walk sees.
    /// Only deployment signals are emitted at this level: a stray .svc or
    /// Controllers/ folder outside any project belongs to no project and
    /// means nothing on its own.
    /// </summary>
    public static IReadOnlyList<Signal> ExtractRepositoryLevel(
        string repositoryRoot, IReadOnlyCollection<string> projectDirectories, CancellationToken cancellationToken)
    {
        var claimed = projectDirectories
            .Select(d => Path.GetFullPath(d).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar)
            .ToList();

        var signals = new List<Signal>();
        foreach (var filePath in FileSystemWalk.EnumerateFiles(repositoryRoot, cancellationToken))
        {
            var full = Path.GetFullPath(filePath);
            if (claimed.Any(dir => full.StartsWith(dir, StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }

            if (DeploymentSignal(filePath) is { } deployment)
            {
                signals.Add(BuildSignal(deployment, FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, filePath), SignalCategories.DeploymentIndicator));
            }
        }

        return signals;
    }

    private static string? DeploymentSignal(string filePath)
    {
        var fileName = Path.GetFileName(filePath);

        if (string.Equals(fileName, "Dockerfile", StringComparison.OrdinalIgnoreCase)
            || fileName.StartsWith("Dockerfile.", StringComparison.OrdinalIgnoreCase)
            || fileName.EndsWith(".Dockerfile", StringComparison.OrdinalIgnoreCase))
        {
            return DockerfileFile;
        }

        if (string.Equals(fileName, "Chart.yaml", StringComparison.OrdinalIgnoreCase))
        {
            return HelmChartFile;
        }

        var extension = Path.GetExtension(filePath);
        var isYaml = extension.Equals(".yaml", StringComparison.OrdinalIgnoreCase) || extension.Equals(".yml", StringComparison.OrdinalIgnoreCase);
        if (isYaml && !IsHelmTemplate(filePath) && LooksLikeManifest(filePath))
        {
            return Ocp4ManifestFile;
        }

        return null;
    }

    // A file under <chart>/templates/ is part of that chart, already counted
    // as HELM_CHART_FILE; its Go-templated YAML is not a standalone manifest.
    private static bool IsHelmTemplate(string filePath)
    {
        for (var dir = Path.GetDirectoryName(filePath); dir is not null; dir = Path.GetDirectoryName(dir))
        {
            if (string.Equals(Path.GetFileName(dir), "templates", StringComparison.OrdinalIgnoreCase)
                && Path.GetDirectoryName(dir) is { } chartDir
                && File.Exists(Path.Combine(chartDir, "Chart.yaml")))
            {
                return true;
            }
        }

        return false;
    }

    private static bool LooksLikeManifest(string filePath)
    {
        try
        {
            using var stream = File.OpenRead(filePath);
            var buffer = new byte[Math.Min(ManifestSniffBytes, stream.Length)];
            var read = stream.Read(buffer, 0, buffer.Length);
            var head = System.Text.Encoding.UTF8.GetString(buffer, 0, read);
            return ManifestApiVersion.IsMatch(head) && ManifestKind.IsMatch(head);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }

    private static Signal BuildSignal(string name, string sourcePath, string category) => new()
    {
        Name = name,
        Category = category,
        Type = SignalTypes.FilePresence,
        Value = null,
        SourceType = category == SignalCategories.DeploymentIndicator
            ? EvidenceSourceTypes.DeploymentScript
            : EvidenceSourceTypes.FileStructure,
        SourcePath = sourcePath,
        OccurrenceCount = 1,
        Evidence = [],
        Extractor = ExtractorName,
        ExtractionConfidence = 1.00m,
    };
}
