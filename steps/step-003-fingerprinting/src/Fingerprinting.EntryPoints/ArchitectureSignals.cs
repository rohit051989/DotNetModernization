using Fingerprinting.Domain;

namespace Fingerprinting.EntryPoints;

/// <summary>
/// Step 4 as a signal producer (scanner 2.2.0, signal registry 1.8.0) — the
/// way step 6 emits PACKAGE_* signals. A WCF service is assembled across
/// projects: the contract in one, the implementation in another, the
/// ServiceHost and system.serviceModel configuration in a third, .svc files
/// in a folder with no project file. Step 3 sees each piece in isolation, so
/// an item that needs them together never fires. Step 4 has already put the
/// pieces together; these signals say so, per project:
/// <list type="bullet">
/// <item><c>EXPOSES_WCF_SERVICE</c> — on the project implementing a service
/// contract; value the contract, evidence the implementing class.</item>
/// <item><c>WCF_SERVICE_HOSTING</c> — on the same project, one per host: where
/// the service is hosted (ServiceHost, IIS .svc, CoreWCF, and in which
/// project or folder). Recorded as the WCF item's hosting attribute.</item>
/// <item><c>HOSTS_WCF_SERVICE</c> — on the project constructing the
/// ServiceHost or holding the .svc file; value the contract.</item>
/// <item><c>EXPOSES_HTTP_API</c>, <c>EXPOSES_ASMX_SERVICE</c>,
/// <c>EXPOSES_GRPC_SERVICE</c>, <c>EXPOSES_WEBFORMS_UI</c>.</item>
/// </list>
/// Application-origin entry points only: a framework type the application
/// merely registers exposes nothing of its own.
/// </summary>
public static class ArchitectureSignals
{
    public const string Extractor = "EntryPointInventory";

    public const string ExposesWcfService = "EXPOSES_WCF_SERVICE";
    public const string WcfServiceHosting = "WCF_SERVICE_HOSTING";
    public const string HostsWcfService = "HOSTS_WCF_SERVICE";
    public const string ExposesHttpApi = "EXPOSES_HTTP_API";
    public const string ExposesAsmxService = "EXPOSES_ASMX_SERVICE";
    public const string ExposesGrpcService = "EXPOSES_GRPC_SERVICE";
    public const string ExposesWebFormsUi = "EXPOSES_WEBFORMS_UI";

    private const int MaxEvidencePerSignal = 20;

    private sealed record Key(string ProjectPath, string Name, string? SourcePath, string? Value);

    private sealed class Entry
    {
        public required string Category { get; init; }
        public required string SourceType { get; init; }
        public int Count { get; set; }
        public List<Evidence> Evidence { get; } = [];
    }

    /// <summary>By project path, the architecture signals. <paramref name="projectPaths"/>
    /// is every project of the repository (step 2's list): a host file is
    /// attributed to the project whose directory holds it.</summary>
    public static IReadOnlyDictionary<string, IReadOnlyList<Signal>> Build(
        IReadOnlyList<ProjectEntryPoints> projects, IReadOnlyList<string> projectPaths)
    {
        var entries = new Dictionary<Key, Entry>();

        void Add(string projectPath, string name, string category, string sourceType, string? sourcePath, string? value, Evidence evidence)
        {
            var key = new Key(projectPath, name, sourcePath, value);
            if (!entries.TryGetValue(key, out var entry))
            {
                entry = new Entry { Category = category, SourceType = sourceType };
                entries[key] = entry;
            }

            entry.Count++;
            if (entry.Evidence.Count < MaxEvidencePerSignal && !entry.Evidence.Contains(evidence))
            {
                entry.Evidence.Add(evidence);
            }
        }

        foreach (var project in projects)
        {
            foreach (var entry in project.EntryPoints.Where(e => e.Origin == EntryPointOrigins.Application))
            {
                var handler = new Evidence
                {
                    LineStart = entry.Handler.LineStart,
                    LineEnd = entry.Handler.LineEnd,
                    DeclaringType = entry.Handler.Type,
                    Member = entry.Handler.Member,
                };
                switch (entry.Kind)
                {
                    case EntryPointKinds.WcfOperation when entry.Wcf is { } wcf:
                        Add(project.ProjectPath, ExposesWcfService, SignalCategories.EntryPoint, EvidenceSourceTypes.SourceCode,
                            entry.Handler.FilePath, wcf.Contract, handler);
                        foreach (var endpoint in wcf.Endpoints)
                        {
                            var (file, line, via) = Location(endpoint.HostedAt);
                            var host = OwnerOf(file, projectPaths);
                            var where = host ?? Folder(file);
                            var kind = endpoint.HostKind switch
                            {
                                "svc" => "IIS .svc",
                                "corewcf" => "CoreWCF",
                                _ => "ServiceHost",
                            };
                            var at = new Evidence { LineStart = line, LineEnd = line, DeclaringType = wcf.Contract, Member = via };
                            Add(project.ProjectPath, WcfServiceHosting, SignalCategories.HostingIndicator, EvidenceSourceTypes.SourceCode,
                                file, $"{kind} in {where}{(host is null ? " (no project file)" : "")}", at);
                            if (host is not null)
                            {
                                Add(host, HostsWcfService, SignalCategories.HostingIndicator,
                                    endpoint.HostKind == "svc" ? EvidenceSourceTypes.FileStructure : EvidenceSourceTypes.SourceCode,
                                    file, wcf.Contract, at);
                            }
                        }

                        if (wcf.Endpoints.Count == 0)
                        {
                            Add(project.ProjectPath, WcfServiceHosting, SignalCategories.HostingIndicator, EvidenceSourceTypes.SourceCode,
                                entry.Handler.FilePath, "no host found", handler);
                        }

                        break;
                    case EntryPointKinds.HttpControllerAction or EntryPointKinds.HttpMinimalApi:
                        Add(project.ProjectPath, ExposesHttpApi, SignalCategories.EntryPoint, EvidenceSourceTypes.SourceCode,
                            entry.Handler.FilePath, entry.Handler.Type, handler);
                        break;
                    case EntryPointKinds.AsmxWebMethod when entry.Asmx is { } asmx:
                        Add(project.ProjectPath, ExposesAsmxService, SignalCategories.EntryPoint, EvidenceSourceTypes.SourceCode,
                            entry.Handler.FilePath, asmx.ServicePath, handler);
                        break;
                    case EntryPointKinds.GrpcServiceMethod when entry.Grpc is { } grpc:
                        Add(project.ProjectPath, ExposesGrpcService, SignalCategories.EntryPoint, EvidenceSourceTypes.SourceCode,
                            entry.Handler.FilePath, grpc.Service, handler);
                        break;
                    case EntryPointKinds.WebFormsPage when entry.WebForms is { } page:
                        Add(project.ProjectPath, ExposesWebFormsUi, SignalCategories.EntryPoint, EvidenceSourceTypes.SourceCode,
                            entry.Handler.FilePath, page.PagePath, handler);
                        break;
                }
            }
        }

        return entries
            .GroupBy(e => e.Key.ProjectPath, StringComparer.Ordinal)
            .ToDictionary(
                g => g.Key,
                g => (IReadOnlyList<Signal>)g
                    .OrderBy(e => e.Key.Name, StringComparer.Ordinal)
                    .ThenBy(e => e.Key.SourcePath ?? "", StringComparer.Ordinal)
                    .ThenBy(e => e.Key.Value ?? "", StringComparer.Ordinal)
                    .Select(e => new Signal
                    {
                        Name = e.Key.Name,
                        Category = e.Value.Category,
                        Type = SignalTypes.EntryPoint,
                        Value = e.Key.Value,
                        SourceType = e.Value.SourceType,
                        SourcePath = e.Key.SourcePath,
                        EvidenceKind = SignalEvidenceKinds.File,
                        OccurrenceCount = e.Value.Count,
                        Evidence = e.Value.Evidence
                            .OrderBy(x => x.LineStart ?? 0).ThenBy(x => x.DeclaringType ?? "", StringComparer.Ordinal)
                            .ThenBy(x => x.Member ?? "", StringComparer.Ordinal).ToList(),
                        Extractor = Extractor,
                        ExtractionConfidence = 1.00m,
                    })
                    .ToList(),
                StringComparer.Ordinal);
    }

    /// <summary><c>src/Catalog.Host/Program.cs:61 via BuildTcpHost</c> → (file, 61, "via BuildTcpHost").</summary>
    private static (string File, int? Line, string? Via) Location(string hostedAt)
    {
        var via = hostedAt.IndexOf(" via ", StringComparison.Ordinal);
        var location = via < 0 ? hostedAt : hostedAt[..via];
        var colon = location.LastIndexOf(':');
        return colon > 0 && int.TryParse(location[(colon + 1)..], out var line)
            ? (location[..colon], line, via < 0 ? null : hostedAt[(via + 1)..])
            : (location, null, via < 0 ? null : hostedAt[(via + 1)..]);
    }

    /// <summary>The project whose directory holds <paramref name="file"/> — the deepest one.</summary>
    public static string? OwnerOf(string file, IReadOnlyList<string> projectPaths) =>
        projectPaths
            .Select(p => (Path: p, Directory: p.Contains('/') ? p[..(p.LastIndexOf('/') + 1)] : ""))
            .Where(p => file.StartsWith(p.Directory, StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(p => p.Directory.Length)
            .Select(p => p.Path)
            .FirstOrDefault();

    private static string Folder(string file) => file.Contains('/') ? file[..file.LastIndexOf('/')] : ".";
}
