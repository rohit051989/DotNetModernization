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

        foreach (var filePath in FileSystemWalk.EnumerateFiles(context.ProjectDirectory, cancellationToken))
        {
            var fileName = Path.GetFileName(filePath);
            var extension = Path.GetExtension(filePath);

            string? signalName = FileNameSignals.TryGetValue(fileName, out var byName)
                ? byName
                : ExtensionSignals.GetValueOrDefault(extension);

            if (signalName is not null)
            {
                signals.Add(BuildSignal(signalName, FileSystemWalk.ToRepositoryRelativePath(context.RepositoryRoot, filePath)));
            }
        }

        foreach (var directoryPath in FileSystemWalk.EnumerateDirectories(context.ProjectDirectory, cancellationToken))
        {
            var directoryName = Path.GetFileName(directoryPath.TrimEnd(Path.DirectorySeparatorChar));
            if (FolderSignals.TryGetValue(directoryName, out var signalName))
            {
                signals.Add(BuildSignal(signalName, FileSystemWalk.ToRepositoryRelativePath(context.RepositoryRoot, directoryPath)));
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
}
