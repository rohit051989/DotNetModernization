using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.TestCoverage;

/// <summary>
/// Part C: which test class exercises which source file.
///
/// <b>Type references, primary (C1).</b> A test class that references a
/// production type — creates it, mocks it, calls its statics, declares it,
/// passes it to an assertion — is testing it. Each reference resolves to the
/// file declaring the type. Syntax only, so never 1.0:
/// <list type="bullet">
/// <item>0.90 — the name is declared in one production file;</item>
/// <item>0.80 — declared in several, and the test file's usings or namespace
/// pick one;</item>
/// <item>0.40 — still ambiguous: every candidate is mapped at 0.40.</item>
/// </list>
///
/// <b>Naming, supporting (C2).</b> <c>OrderServiceTests</c> ↔
/// <c>OrderService</c> (class name, file name, or a namespace segment such as
/// eShopOnWeb's <c>...Entities.BasketTests</c>), and namespace mirroring
/// (<c>X.UnitTests.ApplicationCore.Entities</c> ↔
/// <c>X.ApplicationCore.Entities</c>). Each agreeing with a type reference
/// adds 0.05, to at most 0.95. Naming alone maps at 0.30, marked
/// <c>naming_only</c>.
/// </summary>
public sealed class TestMapper
{
    private static readonly string[] TestSuffixes = ["Tests", "Test", "Specs", "Spec", "Should", "Fixture"];
    private static readonly HashSet<string> TestNamespaceWords =
        new(["Tests", "Test", "UnitTests", "IntegrationTests", "FunctionalTests", "SmokeTests", "Unit", "Integration", "Functional", "Specs"], StringComparer.Ordinal);

    public sealed record ProductionType(string SourceFile, string Name, string QualifiedName, string? Namespace);

    private readonly Dictionary<string, List<ProductionType>> _byName = new(StringComparer.Ordinal);

    public TestMapper(IEnumerable<ProductionType> types)
    {
        foreach (var type in types)
        {
            if (!_byName.TryGetValue(type.Name, out var list)) _byName[type.Name] = list = [];
            list.Add(type);
        }
    }

    public IReadOnlyList<TestMapping> Map(TestDiscovery.DiscoveredClass testClass, string testFile, string testType, IReadOnlyList<string> fileUsings)
    {
        var allMethods = testClass.TestMethods.Select(m => m.Identifier.Text).Distinct().Order(StringComparer.Ordinal).ToList();
        var found = new Dictionary<(string File, string Type), (ProductionType Type, decimal Confidence, SortedSet<string> Methods, List<string> Evidence)>();

        // C1: references.
        foreach (var name in testClass.Syntax.DescendantNodes().OfType<SimpleNameSyntax>())
        {
            if (!_byName.TryGetValue(name.Identifier.Text, out var candidates) || IsMemberName(name)) continue;
            var (chosen, confidence, why) = Resolve(candidates, fileUsings, testClass.Namespace);
            var enclosing = name.Ancestors().OfType<MethodDeclarationSyntax>().FirstOrDefault();
            var methods = enclosing is not null && testClass.TestMethods.Contains(enclosing) ? [enclosing.Identifier.Text] : allMethods;
            foreach (var type in chosen)
            {
                var key = (type.SourceFile, type.QualifiedName);
                if (!found.TryGetValue(key, out var entry))
                {
                    entry = (type, confidence, new SortedSet<string>(StringComparer.Ordinal), [$"references {type.Name}{why}"]);
                    found[key] = entry;
                }

                entry.Methods.UnionWith(methods);
                if (confidence > entry.Confidence) found[key] = (entry.Type, confidence, entry.Methods, entry.Evidence);
            }
        }

        // C2: naming and namespace mirroring.
        var namedTypes = NamingCandidates(testClass, testFile);
        var mirrored = MirroredNamespace(testClass.Namespace);
        var result = new List<TestMapping>();
        foreach (var (key, entry) in found)
        {
            var confidence = entry.Confidence;
            var evidence = new List<string>(entry.Evidence);
            var named = namedTypes.Contains(entry.Type.Name);
            if (named)
            {
                confidence += 0.05m;
                evidence.Add($"name {testClass.ClassName} / {Path.GetFileName(testFile)} matches {entry.Type.Name}");
            }

            var mirrors = mirrored is not null && entry.Type.Namespace == mirrored;
            if (mirrors)
            {
                confidence += 0.05m;
                evidence.Add($"namespace {testClass.Namespace} mirrors {entry.Type.Namespace}");
            }

            result.Add(Mapping(entry.Type, testFile, testClass, testType, entry.Methods.ToList(), Math.Min(confidence, 0.95m),
                named || mirrors ? MappingMethods.TypeReferenceAndNaming : MappingMethods.TypeReference, evidence));
        }

        foreach (var name in namedTypes)
        {
            if (!_byName.TryGetValue(name, out var candidates)) continue;
            foreach (var type in candidates.Where(t => !found.ContainsKey((t.SourceFile, t.QualifiedName))))
            {
                result.Add(Mapping(type, testFile, testClass, testType, allMethods, candidates.Count == 1 ? 0.30m : 0.20m, MappingMethods.NamingOnly,
                    [$"name only: {testClass.ClassName} / {Path.GetFileName(testFile)} suggests {name}; no reference to it"]));
            }
        }

        return result;
    }

    private static TestMapping Mapping(ProductionType type, string testFile, TestDiscovery.DiscoveredClass testClass, string testType,
        IReadOnlyList<string> methods, decimal confidence, string method, IReadOnlyList<string> evidence) => new()
    {
        SourceFile = type.SourceFile,
        ProductionType = type.Namespace is null ? type.QualifiedName : $"{type.Namespace}.{type.QualifiedName}",
        TestFile = testFile,
        TestClass = testClass.Namespace is null ? testClass.ClassName : $"{testClass.Namespace}.{testClass.ClassName}",
        TestType = testType,
        TestMethods = methods,
        Method = method,
        Confidence = confidence,
        Evidence = evidence,
    };

    /// <summary>`x.Basket` is a member called Basket, not the type.</summary>
    private static bool IsMemberName(SimpleNameSyntax name) =>
        name.Parent is MemberAccessExpressionSyntax access && access.Name == name
        || name.Parent is MemberBindingExpressionSyntax
        || name.Parent is AttributeSyntax
        || name.Parent is NameColonSyntax;

    private static (IReadOnlyList<ProductionType> Chosen, decimal Confidence, string Why) Resolve(
        List<ProductionType> candidates, IReadOnlyList<string> usings, string? testNamespace)
    {
        if (candidates.Count == 1) return (candidates, 0.90m, "");
        var visible = candidates.Where(c => c.Namespace is not null
                                            && (usings.Contains(c.Namespace) || (testNamespace?.StartsWith(c.Namespace, StringComparison.Ordinal) ?? false)))
            .ToList();
        if (visible.Count == 1) return (visible, 0.80m, $" (one of {candidates.Count} with that name, chosen by the test file's usings)");
        return (candidates, 0.40m, $" (ambiguous: {candidates.Count} types with that name)");
    }

    private static HashSet<string> NamingCandidates(TestDiscovery.DiscoveredClass testClass, string testFile)
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        AddStripped(names, testClass.ClassName.Split('.')[^1]);
        AddStripped(names, Path.GetFileNameWithoutExtension(testFile));
        if (testClass.Namespace is not null) AddStripped(names, testClass.Namespace.Split('.')[^1]);
        return names;
    }

    private static void AddStripped(HashSet<string> names, string name)
    {
        foreach (var suffix in TestSuffixes)
        {
            if (name.Length > suffix.Length && name.EndsWith(suffix, StringComparison.Ordinal))
            {
                names.Add(name[..^suffix.Length]);
                return;
            }
        }
    }

    /// <summary>The test namespace with its test-only segments removed —
    /// what the production namespace would be if the tests mirror it.</summary>
    private static string? MirroredNamespace(string? testNamespace)
    {
        if (testNamespace is null) return null;
        var segments = testNamespace.Split('.')
            .Where(s => !TestNamespaceWords.Contains(s) && !TestSuffixes.Any(suffix => s.EndsWith(suffix, StringComparison.Ordinal)))
            .ToList();
        return segments.Count == 0 ? null : string.Join(".", segments);
    }

    public static IReadOnlyList<string> Usings(SyntaxNode root) =>
        root.DescendantNodes().OfType<UsingDirectiveSyntax>().Where(u => u.Alias is null && u.Name is not null)
            .Select(u => u.Name!.ToString()).Distinct().ToList();
}
