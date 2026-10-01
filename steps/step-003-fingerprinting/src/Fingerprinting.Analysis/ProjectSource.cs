using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Analysis;

/// <param name="IsGenerated">Generated code (Reference.cs, *.designer.cs):
/// only ever loaded when asked for, and only read where it is the evidence
/// itself — a generated WCF client's binding.</param>
public sealed record ParsedFile(string RelativePath, CompilationUnitSyntax Root, bool IsGenerated = false);

/// <summary>Which non-C# files a step wants loaded with a project, and which
/// of those to keep once read. Each step supplies its own: step 4 wants .svc,
/// .cshtml pages and App.xaml; step 5 wants none of those.</summary>
public interface IAuxiliaryFiles
{
    /// <summary>Whether to read <paramref name="path"/> at all.</summary>
    bool IsCandidate(string path);

    /// <summary>Whether to keep it, having read it.</summary>
    bool Keep(string path, string text);
}

/// <summary>No auxiliary files.</summary>
public sealed class NoAuxiliaryFiles : IAuxiliaryFiles
{
    public static NoAuxiliaryFiles Instance { get; } = new();
    public bool IsCandidate(string path) => false;
    public bool Keep(string path, string text) => false;
}

/// <summary>A class, record, struct or interface declared in the project,
/// with its base list reduced to rightmost identifiers as written.</summary>
public sealed record DeclaredType(
    TypeDeclarationSyntax Syntax,
    ParsedFile File,
    string Name,
    string? Namespace,
    IReadOnlyList<string> BaseNames)
{
    public bool IsInterface => Syntax is InterfaceDeclarationSyntax;
    public bool IsAbstract => Syntax.Modifiers.Any(m => m.Text == "abstract");
    public bool IsStatic => Syntax.Modifiers.Any(m => m.Text == "static");
}

/// <summary>
/// One project's C# source, parsed once and shared by every detector: the
/// same file set step 3 reads (<see cref="SourceFileScanner"/> — generated
/// code excluded unless asked for, capped per project), plus the non-C# files
/// the step asks for. Shared by steps 4 and 5.
/// </summary>
public sealed class ProjectSource
{
    public required string ProjectPath { get; init; }

    /// <summary>The project's directory, repository-relative, forward
    /// slashes, "" for the repository root.</summary>
    public required string ProjectDirectory { get; init; }

    public required IReadOnlyList<ParsedFile> Files { get; init; }
    public required IReadOnlyList<string> PackageNames { get; init; }
    public required bool Truncated { get; init; }

    /// <summary>Repository-relative paths of the non-C# files the loading
    /// step asked for (<see cref="IAuxiliaryFiles"/>), under the project
    /// directory, with their text.</summary>
    public required IReadOnlyList<(string RelativePath, string Text)> AuxiliaryFiles { get; init; }

    private IReadOnlyList<DeclaredType>? _types;
    private ILookup<string, DeclaredType>? _typesByName;

    public IReadOnlyList<DeclaredType> Types => _types ??= IndexTypes();

    public ILookup<string, DeclaredType> TypesByName =>
        _typesByName ??= Types.ToLookup(t => t.Name, StringComparer.Ordinal);

    /// <param name="includeGenerated">Load generated files too, flagged
    /// <see cref="ParsedFile.IsGenerated"/>. Off unless a step reads
    /// generated code as evidence.</param>
    public static async Task<ProjectSource> LoadAsync(
        string repositoryRoot,
        string projectPath,
        IReadOnlyList<string> packageNames,
        IAuxiliaryFiles auxiliaryFiles,
        CancellationToken cancellationToken,
        bool includeGenerated = false)
    {
        var projectDirectoryAbsolute = Path.GetDirectoryName(
            Path.Combine(repositoryRoot, projectPath.Replace('/', Path.DirectorySeparatorChar)))!;
        var projectDirectory = FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, projectDirectoryAbsolute);
        if (projectDirectory == ".")
        {
            projectDirectory = "";
        }

        var scan = SourceFileScanner.EnumerateCSharpFiles(repositoryRoot, projectDirectoryAbsolute, cancellationToken, includeGenerated);
        var files = new List<ParsedFile>();
        foreach (var file in scan.Files.OrderBy(f => f.RelativePath, StringComparer.Ordinal))
        {
            var root = await SourceFileScanner.ParseAsync(file.AbsolutePath, cancellationToken);
            files.Add(new ParsedFile(file.RelativePath, (CompilationUnitSyntax)root, file.IsGenerated));
        }

        var auxiliary = new List<(string, string)>();
        foreach (var path in FileSystemWalk.EnumerateFiles(projectDirectoryAbsolute, cancellationToken))
        {
            if (!auxiliaryFiles.IsCandidate(path))
            {
                continue;
            }

            // ReadAllText drops the BOM these files often start with.
            var text = await File.ReadAllTextAsync(path, cancellationToken);
            if (auxiliaryFiles.Keep(path, text))
            {
                auxiliary.Add((FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, path), text));
            }
        }

        return new ProjectSource
        {
            ProjectPath = projectPath,
            ProjectDirectory = projectDirectory,
            Files = files,
            PackageNames = packageNames,
            Truncated = scan.Truncated,
            AuxiliaryFiles = auxiliary.OrderBy(a => a.Item1, StringComparer.Ordinal).ToList(),
        };
    }

    /// <summary>Builds a project from in-memory source — for tests.</summary>
    public static ProjectSource FromText(
        string projectPath, IReadOnlyDictionary<string, string> files, IReadOnlyList<string>? packageNames = null,
        IReadOnlyList<(string, string)>? auxiliaryFiles = null)
    {
        var directory = projectPath.Contains('/') ? projectPath[..projectPath.LastIndexOf('/')] : "";
        return new ProjectSource
        {
            ProjectPath = projectPath,
            ProjectDirectory = directory,
            Files = files
                .OrderBy(f => f.Key, StringComparer.Ordinal)
                .Select(f => new ParsedFile(f.Key, (CompilationUnitSyntax)Microsoft.CodeAnalysis.CSharp.CSharpSyntaxTree.ParseText(f.Value).GetRoot()))
                .ToList(),
            PackageNames = packageNames ?? [],
            Truncated = false,
            AuxiliaryFiles = auxiliaryFiles ?? [],
        };
    }

    public bool HasPackage(params string[] names) =>
        PackageNames.Any(p => names.Any(n => string.Equals(p, n, StringComparison.OrdinalIgnoreCase)));

    /// <summary>The path of <paramref name="relativePath"/> relative to the
    /// project directory — the URL path of an .aspx or .asmx.</summary>
    public string PathWithinProject(string relativePath) =>
        ProjectDirectory.Length == 0 ? relativePath : relativePath[(ProjectDirectory.Length + 1)..];

    /// <summary>
    /// Follows <paramref name="type"/>'s base list through classes declared
    /// in this project until one of <paramref name="targets"/> is reached.
    /// Returns the target found and the in-project class it was reached
    /// through (null when <paramref name="type"/> names the target directly),
    /// or null when no path exists. Syntax only: a base named like a target
    /// is taken at its word (Part A2).
    /// </summary>
    public (string Target, string? Via)? ResolveBase(DeclaredType type, IReadOnlySet<string> targets)
    {
        var visited = new HashSet<string>(StringComparer.Ordinal) { type.Name };
        var queue = new Queue<(DeclaredType Type, string? Via)>();
        queue.Enqueue((type, null));

        while (queue.Count > 0)
        {
            var (current, via) = queue.Dequeue();
            foreach (var baseName in current.BaseNames)
            {
                if (targets.Contains(baseName))
                {
                    return (baseName, via);
                }

                if (!visited.Add(baseName))
                {
                    continue;
                }

                foreach (var declared in TypesByName[baseName].Where(t => !t.IsInterface || current.IsInterface))
                {
                    queue.Enqueue((declared, via ?? declared.Name));
                }
            }
        }

        return null;
    }

    /// <summary><paramref name="type"/> and every in-project class it
    /// derives from, nearest first — for attributes inherited from a base
    /// controller (<c>[Route]</c>, <c>[Authorize]</c>, <c>[ApiController]</c>).</summary>
    public IReadOnlyList<DeclaredType> SelfAndBaseClasses(DeclaredType type)
    {
        var chain = new List<DeclaredType> { type };
        var visited = new HashSet<string>(StringComparer.Ordinal) { type.Name };
        var current = type;
        while (true)
        {
            var next = current.BaseNames
                .Where(visited.Add)
                .SelectMany(n => TypesByName[n])
                .FirstOrDefault(t => !t.IsInterface);
            if (next is null)
            {
                return chain;
            }

            chain.Add(next);
            current = next;
        }
    }

    private List<DeclaredType> IndexTypes()
    {
        var types = new List<DeclaredType>();
        foreach (var file in Files)
        {
            foreach (var declaration in file.Root.DescendantNodes().OfType<TypeDeclarationSyntax>())
            {
                var baseNames = declaration.BaseList?.Types
                    .Select(b => SyntaxHelpers.RightmostTypeName(b.Type))
                    .OfType<string>()
                    .ToList() ?? [];
                types.Add(new DeclaredType(declaration, file, declaration.Identifier.Text, SyntaxHelpers.NamespaceOf(declaration), baseNames));
            }
        }

        return types;
    }
}
