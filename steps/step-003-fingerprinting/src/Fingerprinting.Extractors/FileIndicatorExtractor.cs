using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Level 1 (file-system) extraction — the file and folder indicators from
/// step-3-application-fingerprinting.md section 7. Never fails to load and
/// works on code that does not compile; proves the pipeline end to end.
/// Same directory exclusions as steps 1 and 2
/// (backend/app/steps/repository_ingest.py SKIP_DIR_NAMES).
/// </summary>
public sealed class FileIndicatorExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "FileIndicatorExtractor";

    public string Name => ExtractorName;

    private static readonly HashSet<string> SkipDirNames =
        new(StringComparer.OrdinalIgnoreCase) { ".git", "node_modules", "bin", "obj", "packages" };

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

        foreach (var filePath in EnumerateFiles(context.ProjectDirectory, cancellationToken))
        {
            var fileName = Path.GetFileName(filePath);
            var extension = Path.GetExtension(filePath);

            string? signalName = FileNameSignals.TryGetValue(fileName, out var byName)
                ? byName
                : ExtensionSignals.GetValueOrDefault(extension);

            if (signalName is not null)
            {
                signals.Add(BuildSignal(signalName, ToRepositoryRelativePath(context.RepositoryRoot, filePath)));
            }
        }

        foreach (var directoryPath in EnumerateDirectories(context.ProjectDirectory, cancellationToken))
        {
            var directoryName = Path.GetFileName(directoryPath.TrimEnd(Path.DirectorySeparatorChar));
            if (FolderSignals.TryGetValue(directoryName, out var signalName))
            {
                signals.Add(BuildSignal(signalName, ToRepositoryRelativePath(context.RepositoryRoot, directoryPath)));
            }
        }

        return Task.FromResult(new ExtractorResult { Signals = signals });
    }

    private static Signal BuildSignal(string name, string sourcePath) => new()
    {
        Name = name,
        Category = SignalCategories.FileIndicator,
        Type = SignalTypes.FilePresence,
        Value = null,
        SourceType = EvidenceSourceTypes.FileStructure,
        SourcePath = sourcePath,
        OccurrenceCount = 1,
        Evidence = [],
        Extractor = ExtractorName,
        ExtractionConfidence = 1.00m,
    };

    private static IEnumerable<string> EnumerateFiles(string root, CancellationToken cancellationToken)
    {
        foreach (var directory in EnumerateDirectoriesIncludingRoot(root, cancellationToken))
        {
            IEnumerable<string> files;
            try
            {
                files = Directory.EnumerateFiles(directory);
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException or IOException)
            {
                continue;
            }

            foreach (var file in files)
            {
                cancellationToken.ThrowIfCancellationRequested();
                yield return file;
            }
        }
    }

    private static IEnumerable<string> EnumerateDirectories(string root, CancellationToken cancellationToken) =>
        EnumerateDirectoriesIncludingRoot(root, cancellationToken)
            .Where(d => !string.Equals(d, root, StringComparison.OrdinalIgnoreCase));

    /// <summary>Iterative (not recursive) so a deeply nested repository cannot
    /// blow the stack. Order is arbitrary — the CLI sorts signals centrally
    /// before serialization (21-STEP-003-FINGERPRINTING.md Part B rule 2).</summary>
    private static IEnumerable<string> EnumerateDirectoriesIncludingRoot(string root, CancellationToken cancellationToken)
    {
        var stack = new Stack<string>();
        stack.Push(root);

        while (stack.Count > 0)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var current = stack.Pop();
            yield return current;

            IEnumerable<string> children;
            try
            {
                children = Directory.EnumerateDirectories(current);
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException or IOException)
            {
                continue;
            }

            foreach (var child in children)
            {
                if (!SkipDirNames.Contains(Path.GetFileName(child)))
                {
                    stack.Push(child);
                }
            }
        }
    }

    private static string ToRepositoryRelativePath(string repositoryRoot, string absolutePath) =>
        Path.GetRelativePath(repositoryRoot, absolutePath).Replace('\\', '/');
}
