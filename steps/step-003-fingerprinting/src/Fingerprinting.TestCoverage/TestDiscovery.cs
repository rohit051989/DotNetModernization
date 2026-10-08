using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.TestCoverage;

/// <summary>
/// Part B: test classes and their type. Syntax only.
///
/// A test class declares at least one test method: <c>[Fact]</c>,
/// <c>[Theory]</c>, <c>[Test]</c>, <c>[TestMethod]</c>, <c>[TestCase]</c>
/// (Part B1), plus their direct variants <c>[DataTestMethod]</c> and
/// <c>[TestCaseSource]</c>.
///
/// Classification (Part B2) is per class and never guessed:
/// <list type="bullet">
/// <item><b>strong</b> — the project name (<c>*.UnitTests</c>,
/// <c>*IntegrationTests</c>, ...) and declared categories
/// (<c>[Trait("Category", …)]</c>, <c>[TestCategory]</c>, NUnit
/// <c>[Category]</c>). Two strong types disagreeing is a conflict.</item>
/// <item><b>indicative</b> of integration — WebApplicationFactory,
/// TestServer, Testcontainers in the class, or a real connection string or
/// service URL in it. A class declared unit that shows these is a
/// conflict.</item>
/// <item><b>supporting</b> of unit — a mocking library (Moq, NSubstitute,
/// FakeItEasy) and no infrastructure.</item>
/// </list>
/// Conflict, or no evidence at all, is <c>unclassified</c>.
/// </summary>
public static class TestDiscovery
{
    private static readonly HashSet<string> TestMethodAttributes =
        new(["Fact", "Theory", "Test", "TestMethod", "TestCase", "DataTestMethod", "TestCaseSource"], StringComparer.Ordinal);

    private static readonly (string Suffix, string Type)[] ProjectNameSuffixes =
    [
        ("unittests", TestTypes.Unit), ("unittest", TestTypes.Unit), ("tests.unit", TestTypes.Unit),
        ("integrationtests", TestTypes.Integration), ("integrationtest", TestTypes.Integration), ("tests.integration", TestTypes.Integration),
        ("functionaltests", TestTypes.Functional), ("functionaltest", TestTypes.Functional), ("tests.functional", TestTypes.Functional),
        ("e2e", TestTypes.Functional), ("e2etests", TestTypes.Functional), ("endtoendtests", TestTypes.Functional),
        ("smoketests", TestTypes.Smoke), ("smoketest", TestTypes.Smoke), ("tests.smoke", TestTypes.Smoke),
    ];

    private static readonly string[] InfrastructureIdentifiers = ["WebApplicationFactory", "TestServer", "ContainerBuilder", "TestcontainersBuilder"];

    private static readonly Regex ConnectionString = new(
        @"(?i)\b(server|data source|host|initial catalog|database)\s*=[^;""]+;", RegexOptions.Compiled);

    private static readonly Regex ServiceUrl = new(@"(?i)\bhttps?://([a-z0-9.\-]+)", RegexOptions.Compiled);

    /// <summary>Hosts that are not a real system: loopback and names reserved
    /// for examples and tests (RFC 2606).</summary>
    private static bool IsFakeHost(string host)
    {
        host = host.ToLowerInvariant();
        return host is "localhost" or "127.0.0.1" or "0.0.0.0" or "[::1]"
               || host.EndsWith("example.com", StringComparison.Ordinal) || host.EndsWith("example.org", StringComparison.Ordinal)
               || host.EndsWith("example.net", StringComparison.Ordinal) || host.EndsWith(".test", StringComparison.Ordinal)
               || host.EndsWith(".invalid", StringComparison.Ordinal) || host.EndsWith(".localhost", StringComparison.Ordinal);
    }

    public sealed record DiscoveredClass(
        string ClassName, string? Namespace, int LineStart, ClassDeclarationSyntax Syntax, IReadOnlyList<MethodDeclarationSyntax> TestMethods);

    /// <summary>Every class in the file declaring at least one test method.</summary>
    public static IReadOnlyList<DiscoveredClass> FindTestClasses(SyntaxNode root)
    {
        var result = new List<DiscoveredClass>();
        foreach (var declaration in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
        {
            var methods = declaration.Members.OfType<MethodDeclarationSyntax>()
                .Where(m => AttributeNames(m.AttributeLists).Any(TestMethodAttributes.Contains))
                .ToList();
            if (methods.Count == 0) continue;
            result.Add(new DiscoveredClass(QualifiedClassName(declaration), NamespaceOf(declaration),
                declaration.GetLocation().GetLineSpan().StartLinePosition.Line + 1, declaration, methods));
        }

        return result;
    }

    /// <summary>The project-name evidence for a test project, if any. Matched
    /// on the project file's name, case-insensitive, as a suffix — so
    /// eShopOnWeb's <c>PublicApiIntegrationTests</c> is integration.</summary>
    public static (string Type, string Suffix)? ProjectNameType(string projectPath)
    {
        var name = Path.GetFileNameWithoutExtension(projectPath).ToLowerInvariant();
        foreach (var (suffix, type) in ProjectNameSuffixes)
        {
            if (name == suffix || name.EndsWith("." + suffix, StringComparison.Ordinal) || name.EndsWith(suffix, StringComparison.Ordinal))
            {
                return (type, suffix);
            }
        }

        return null;
    }

    /// <summary>Classifies one test class. <paramref name="projectEvidence"/>
    /// is evidence that applies to every class in the project: its name, and
    /// connection strings in its configuration.</summary>
    public static (string Type, string Reason, IReadOnlyList<ClassificationEvidence> Evidence) Classify(
        DiscoveredClass testClass, IReadOnlyList<ClassificationEvidence> projectEvidence)
    {
        var evidence = new List<ClassificationEvidence>(projectEvidence);
        evidence.AddRange(CategoryEvidence(testClass, out var categoryConflict));
        evidence.AddRange(CodeEvidence(testClass.Syntax));
        evidence = evidence.Distinct().OrderBy(e => e.Kind, StringComparer.Ordinal).ThenBy(e => e.Value, StringComparer.Ordinal).ToList();

        if (categoryConflict is not null)
        {
            return (TestTypes.Unclassified, categoryConflict, evidence);
        }

        var strong = evidence.Where(e => e.Strength == "strong").Select(e => e.Indicates).Distinct().OrderBy(t => t, StringComparer.Ordinal).ToList();
        var infrastructure = evidence.Where(e => e.Strength == "indicative").ToList();
        if (strong.Count > 1)
        {
            return (TestTypes.Unclassified, "conflicting evidence: " + string.Join(" vs ", strong), evidence);
        }

        if (strong.Count == 1)
        {
            var declared = strong[0];
            if (declared == TestTypes.Unit && infrastructure.Count > 0)
            {
                return (TestTypes.Unclassified,
                    $"conflicting evidence: declared unit, but the class uses {string.Join(", ", infrastructure.Select(e => e.Value))}", evidence);
            }

            var source = evidence.First(e => e.Strength == "strong");
            return (declared, $"{source.Kind} {source.Value}", evidence);
        }

        if (infrastructure.Count > 0)
        {
            return (TestTypes.Integration, "uses " + string.Join(", ", infrastructure.Select(e => e.Value)), evidence);
        }

        var mocking = evidence.Where(e => e.Kind == "mocking").ToList();
        if (mocking.Count > 0)
        {
            return (TestTypes.Unit, $"mocking only ({string.Join(", ", mocking.Select(e => e.Value))}), no infrastructure — supporting evidence", evidence);
        }

        return (TestTypes.Unclassified, "no classification evidence", evidence);
    }

    /// <summary>Declared categories, class and method level. Methods
    /// declaring different types make the class a conflict.</summary>
    private static IEnumerable<ClassificationEvidence> CategoryEvidence(DiscoveredClass testClass, out string? conflict)
    {
        conflict = null;
        var found = new List<ClassificationEvidence>();
        foreach (var value in CategoryValues(testClass.Syntax.AttributeLists))
        {
            if (CategoryType(value) is { } type) found.Add(Category(value, type));
        }

        var methodTypes = new HashSet<string>(StringComparer.Ordinal);
        foreach (var method in testClass.TestMethods)
        {
            foreach (var value in CategoryValues(method.AttributeLists))
            {
                if (CategoryType(value) is { } type)
                {
                    methodTypes.Add(type);
                    found.Add(Category(value, type));
                }
            }
        }

        if (methodTypes.Count > 1)
        {
            conflict = "conflicting evidence: test methods declare different categories (" + string.Join(", ", methodTypes.Order(StringComparer.Ordinal)) + ")";
        }

        return found;
    }

    private static ClassificationEvidence Category(string value, string type) =>
        new() { Kind = "category", Value = value, Indicates = type, Strength = "strong" };

    private static string? CategoryType(string value)
    {
        var v = value.ToLowerInvariant();
        if (v.Contains("unit")) return TestTypes.Unit;
        if (v.Contains("integration")) return TestTypes.Integration;
        if (v.Contains("smoke")) return TestTypes.Smoke;
        if (v.Contains("functional") || v.Contains("e2e") || v.Contains("endtoend") || v.Contains("end-to-end") || v.Contains("acceptance")) return TestTypes.Functional;
        return null;
    }

    /// <summary><c>[Trait("Category", "X")]</c>, <c>[TestCategory("X")]</c>,
    /// <c>[Category("X")]</c>: the string literal X.</summary>
    private static IEnumerable<string> CategoryValues(SyntaxList<AttributeListSyntax> lists)
    {
        foreach (var attribute in lists.SelectMany(l => l.Attributes))
        {
            var name = SimpleName(attribute.Name);
            var args = attribute.ArgumentList?.Arguments.Select(a => a.Expression).OfType<LiteralExpressionSyntax>()
                .Where(l => l.IsKind(SyntaxKind.StringLiteralExpression)).Select(l => l.Token.ValueText).ToList() ?? [];
            if (name == "Trait" && args.Count == 2 && string.Equals(args[0], "Category", StringComparison.OrdinalIgnoreCase)) yield return args[1];
            else if (name is "TestCategory" or "Category" && args.Count >= 1) yield return args[0];
        }
    }

    private static IEnumerable<ClassificationEvidence> CodeEvidence(ClassDeclarationSyntax declaration)
    {
        var identifiers = declaration.DescendantNodes().OfType<SimpleNameSyntax>().Select(n => n.Identifier.Text).ToHashSet(StringComparer.Ordinal);
        foreach (var marker in InfrastructureIdentifiers)
        {
            if (identifiers.Any(i => i.Contains(marker, StringComparison.Ordinal)))
            {
                yield return new ClassificationEvidence { Kind = "infrastructure", Value = marker, Indicates = TestTypes.Integration, Strength = "indicative" };
            }
        }

        foreach (var literal in declaration.DescendantNodes().OfType<LiteralExpressionSyntax>().Where(l => l.IsKind(SyntaxKind.StringLiteralExpression)))
        {
            var text = literal.Token.ValueText;
            if (ConnectionString.IsMatch(text))
            {
                yield return new ClassificationEvidence { Kind = "connection_string", Value = "connection string literal", Indicates = TestTypes.Integration, Strength = "indicative" };
            }

            foreach (Match url in ServiceUrl.Matches(text))
            {
                if (!IsFakeHost(url.Groups[1].Value))
                {
                    yield return new ClassificationEvidence { Kind = "service_url", Value = url.Groups[1].Value.ToLowerInvariant(), Indicates = TestTypes.Integration, Strength = "indicative" };
                }
            }
        }

        // Moq's Mock<T>, NSubstitute's Substitute.For<T>, FakeItEasy's A.Fake<T>.
        var mocks = declaration.DescendantNodes().OfType<GenericNameSyntax>().Select(g => g.Identifier.Text)
            .Concat(declaration.DescendantNodes().OfType<MemberAccessExpressionSyntax>().Select(m => m.Expression.ToString()))
            .Where(name => name is "Mock" or "Substitute" or "A")
            .Distinct()
            .ToList();
        var fakes = declaration.DescendantNodes().OfType<MemberAccessExpressionSyntax>()
            .Any(m => m.Expression.ToString() == "A" && m.Name.Identifier.Text == "Fake");
        if (mocks.Contains("Mock")) yield return Mocking("Moq");
        if (mocks.Contains("Substitute")) yield return Mocking("NSubstitute");
        if (fakes) yield return Mocking("FakeItEasy");
    }

    private static ClassificationEvidence Mocking(string library) =>
        new() { Kind = "mocking", Value = library, Indicates = TestTypes.Unit, Strength = "supporting" };

    /// <summary>Connection strings in a test project's configuration
    /// (app.config, appsettings*.json): project-level integration evidence.</summary>
    public static IReadOnlyList<ClassificationEvidence> ConfigEvidence(IEnumerable<string> configTexts)
    {
        foreach (var text in configTexts)
        {
            if (ConnectionString.IsMatch(text))
            {
                return [new ClassificationEvidence { Kind = "connection_string", Value = "connection string in test configuration", Indicates = TestTypes.Integration, Strength = "indicative" }];
            }
        }

        return [];
    }

    public static IEnumerable<string> AttributeNames(SyntaxList<AttributeListSyntax> lists) =>
        lists.SelectMany(l => l.Attributes).Select(a => SimpleName(a.Name));

    private static string SimpleName(NameSyntax name)
    {
        var text = name switch
        {
            QualifiedNameSyntax q => q.Right.Identifier.Text,
            AliasQualifiedNameSyntax a => a.Name.Identifier.Text,
            SimpleNameSyntax s => s.Identifier.Text,
            _ => name.ToString(),
        };
        return text.EndsWith("Attribute", StringComparison.Ordinal) ? text[..^"Attribute".Length] : text;
    }

    public static string QualifiedClassName(BaseTypeDeclarationSyntax declaration) =>
        string.Join(".", declaration.AncestorsAndSelf().OfType<BaseTypeDeclarationSyntax>().Reverse().Select(t => t.Identifier.Text));

    public static string? NamespaceOf(SyntaxNode node)
    {
        var parts = node.Ancestors().OfType<BaseNamespaceDeclarationSyntax>().Select(n => n.Name.ToString()).Reverse().ToList();
        return parts.Count == 0 ? null : string.Join(".", parts);
    }
}
