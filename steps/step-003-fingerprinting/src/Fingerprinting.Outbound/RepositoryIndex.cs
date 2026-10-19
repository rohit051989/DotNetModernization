using System.Collections.Concurrent;
using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Outbound;

/// <summary>
/// Repository-wide facts the detectors look up, each built once per run on first use and shared by every project's
/// detection (rbc-release-5). Before, each project's detection re-derived them by walking every file of the repository
/// — once per project, and in places once per call site — so the work grew with the square of the code: a repository
/// with many projects and large generated proxies took hours.
/// Thread-safe: projects are detected in parallel.
/// </summary>
public sealed class RepositoryIndex(IReadOnlyList<ProjectSource> projects)
{
    private readonly ConcurrentDictionary<string, Lazy<object>> _built = new(StringComparer.Ordinal);

    public IReadOnlyList<ProjectSource> Projects { get; } = projects;

    /// <summary>The fact named <paramref name="key"/>, built by <paramref name="build"/> the first time anyone asks.</summary>
    public T Get<T>(string key, Func<IReadOnlyList<ProjectSource>, T> build) where T : class =>
        (T)_built.GetOrAdd(key, _ => new Lazy<object>(() => build(Projects), LazyThreadSafetyMode.ExecutionAndPublication)).Value;

    /// <summary>Per project, the type names constructed with <c>new</c> in its hand-written code.</summary>
    public IReadOnlyDictionary<ProjectSource, HashSet<string>> ConstructedTypeNames => Get("constructed", all =>
        (IReadOnlyDictionary<ProjectSource, HashSet<string>>)all.ToDictionary(p => p, p => p.Files.Where(f => !f.IsGenerated)
            .SelectMany(f => f.Root.DescendantNodes().OfType<ObjectCreationExpressionSyntax>())
            .Select(c => SyntaxHelpers.RightmostTypeName(c.Type))
            .OfType<string>()
            .ToHashSet(StringComparer.Ordinal)));

    /// <summary>Every interface declared anywhere, by name.</summary>
    public ILookup<string, (ProjectSource Project, DeclaredType Type)> InterfacesByName => Get("interfaces", all =>
        all.SelectMany(p => p.Types.Where(t => t.IsInterface).Select(t => (Project: p, Type: t)))
            .ToLookup(x => x.Type.Name, StringComparer.Ordinal));

    /// <summary>Property declarations with an initializer in hand-written code, by property name.</summary>
    public ILookup<string, PropertyDeclarationSyntax> InitializedProperties => Get("initialized-properties", all =>
        all.SelectMany(p => p.Files).Where(f => !f.IsGenerated)
            .SelectMany(f => f.Root.DescendantNodes().OfType<PropertyDeclarationSyntax>())
            .Where(p => p.Initializer is not null)
            .ToLookup(p => p.Identifier.Text, StringComparer.Ordinal));
}
