using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

public sealed record ParsedFile(string RelativePath, CompilationUnitSyntax Root);

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
/// code excluded, capped per project), plus the non-C# files some kinds are
/// declared in (.svc, .proto).
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

    /// <summary>Repository-relative paths of the non-C# files entry points
    /// are declared in, under the project directory, with their text: .svc,
    /// .proto, .ashx, Global.asax, Razor Pages (.cshtml with <c>@page</c>),
    /// routable Blazor components (.razor with <c>@page</c>) and WPF
    /// App.xaml.</summary>
    public required IReadOnlyList<(string RelativePath, string Text)> AuxiliaryFiles { get; init; }

    private IReadOnlyList<DeclaredType>? _types;
    private ILookup<string, DeclaredType>? _typesByName;

    public IReadOnlyList<DeclaredType> Types => _types ??= IndexTypes();

    public ILookup<string, DeclaredType> TypesByName =>
        _typesByName ??= Types.ToLookup(t => t.Name, StringComparer.Ordinal);

    public static async Task<ProjectSource> LoadAsync(
        string repositoryRoot,
        string projectPath,
        IReadOnlyList<string> packageNames,
        CancellationToken cancellationToken)
    {
        var projectDirectoryAbsolute = Path.GetDirectoryName(
            Path.Combine(repositoryRoot, projectPath.Replace('/', Path.DirectorySeparatorChar)))!;
        var projectDirectory = FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, projectDirectoryAbsolute);
        if (projectDirectory == ".")
        {
            projectDirectory = "";
        }

        var scan = SourceFileScanner.EnumerateCSharpFiles(repositoryRoot, projectDirectoryAbsolute, cancellationToken);
        var files = new List<ParsedFile>();
        foreach (var file in scan.Files.OrderBy(f => f.RelativePath, StringComparer.Ordinal))
        {
            var root = await SourceFileScanner.ParseAsync(file.AbsolutePath, cancellationToken);
            files.Add(new ParsedFile(file.RelativePath, (CompilationUnitSyntax)root));
        }

        var auxiliary = new List<(string, string)>();
        foreach (var path in FileSystemWalk.EnumerateFiles(projectDirectoryAbsolute, cancellationToken))
        {
            if (path.EndsWith(".svc", StringComparison.OrdinalIgnoreCase)
                || path.EndsWith(".proto", StringComparison.OrdinalIgnoreCase)
                || path.EndsWith(".ashx", StringComparison.OrdinalIgnoreCase)
                || Path.GetFileName(path).Equals("Global.asax", StringComparison.OrdinalIgnoreCase))
            {
                auxiliary.Add((FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, path),
                    await File.ReadAllTextAsync(path, cancellationToken)));
            }
            else if (path.EndsWith(".cshtml", StringComparison.OrdinalIgnoreCase))
            {
                // Only pages: a view or partial has no @page directive.
                // ReadAllText drops the BOM these files usually start with.
                var text = await File.ReadAllTextAsync(path, cancellationToken);
                if (RazorPageDetector.PageDirective(text) is not null)
                {
                    auxiliary.Add((FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, path), text));
                }
            }
            else if (path.EndsWith(".razor", StringComparison.OrdinalIgnoreCase))
            {
                // Only routable components; layouts and partials have no @page.
                var text = await File.ReadAllTextAsync(path, cancellationToken);
                if (BlazorComponentDetector.Routes(text).Count > 0)
                {
                    auxiliary.Add((FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, path), text));
                }
            }
            else if (path.EndsWith(".xaml", StringComparison.OrdinalIgnoreCase))
            {
                // Only the application definition (App.xaml), not every window.
                var text = await File.ReadAllTextAsync(path, cancellationToken);
                if (DesktopAppDetector.IsApplicationXaml(text))
                {
                    auxiliary.Add((FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, path), text));
                }
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
