using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Dependencies;

/// <summary>A changed member the project calls, with where.</summary>
public sealed record ChangeHit(ApiChange Change, IReadOnlyList<CallSite> Sites);

/// <summary>
/// Part C4: find the call sites of each changed API in a project's source.
/// Syntax only, guarded by the package's namespace — the same approach as
/// step 3's SYSTEM_DRAWING_USAGE — so a match is likely, not certain
/// (<see cref="Confidence"/> below 1.0). A file is considered only if it
/// imports the changed type's namespace (or names it fully). A removed type
/// matches by name. A removed or changed member matches a member access or
/// call of that name, and — unless it is an extension method — only in a
/// file that also names the declaring type, which keeps common member names
/// (Add, Value) from matching everything.
/// </summary>
public static class CallSiteFinder
{
    public const double Confidence = 0.7;

    /// <summary>A call that an unchanged overload could equally accept.</summary>
    public const double AmbiguousConfidence = 0.4;
    private const int MaxSitesPerChange = 50;

    public static IReadOnlyList<ChangeHit> Find(ProjectSource project, IReadOnlyList<ApiChange> changes)
    {
        if (changes.Count == 0) return [];
        var files = project.Files.Where(f => !f.IsGenerated).Select(f => (File: f, Imports: Imports(f.Root))).ToList();
        var hits = new List<ChangeHit>();

        foreach (var change in changes)
        {
            var ns = change.Type.Namespace;
            var sites = new List<CallSite>();
            foreach (var (file, imports) in files)
            {
                if (ns.Length > 0 && !imports.Contains(ns) && !file.Root.ToString().Contains(ns + ".", StringComparison.Ordinal)) continue;

                var identifiers = file.Root.DescendantNodes().OfType<SimpleNameSyntax>().ToList();
                var namesType = identifiers.Any(i => i.Identifier.Text == change.Type.SimpleName && !IsDeclaration(i));
                IEnumerable<SyntaxNode> matches = change.Change == "type_removed"
                    ? identifiers.Where(i => i.Identifier.Text == change.Type.SimpleName && !IsDeclaration(i) && QualifiedIfNested(i, change.Type))
                    : change.Member == ".ctor"
                        // A constructor that changed: `new Type(...)`, not every mention of Type.
                        ? identifiers.Where(i => i.Identifier.Text == change.Type.SimpleName
                                                 && i.Ancestors().OfType<ObjectCreationExpressionSyntax>().Any(o => o.Type.Span.Contains(i.Span)))
                    : !namesType && !change.IsExtension
                        ? []
                        : identifiers.Where(i => i.Identifier.Text == change.Member && IsMemberUse(i) && ArgumentsFit(i, change));

                foreach (var node in matches)
                {
                    var (start, end) = SyntaxHelpers.Lines(node);
                    sites.Add(new CallSite
                    {
                        FilePath = file.RelativePath,
                        LineStart = start,
                        LineEnd = end,
                        Member = change.Member is null or ".ctor" ? change.Type.FullName : $"{change.Type.FullName}.{change.Member}",
                        Certainty = node is SimpleNameSyntax name && MayBindElsewhere(name, change) ? CallSiteCertainty.Ambiguous : CallSiteCertainty.Confirmed,
                    });
                    if (sites.Count >= MaxSitesPerChange) break;
                }
            }

            if (sites.Count > 0)
            {
                hits.Add(new ChangeHit(change, sites.DistinctBy(s => (s.FilePath, s.LineStart, s.Member))
                    .OrderBy(s => s.FilePath, StringComparer.Ordinal).ThenBy(s => s.LineStart).ToList()));
            }
        }

        return hits;
    }

    /// <summary>
    /// A call whose argument count the changed signature could not have
    /// accepted is calling a different overload: <c>Assert.AreEqual(a, b)</c>
    /// is not a use of a changed <c>AreEqual(a, b, delta)</c>. An extension
    /// method called as <c>x.M(...)</c> passes its receiver as the first
    /// argument. A method group or member access with no call is kept.
    /// </summary>
    private static bool ArgumentsFit(SimpleNameSyntax name, ApiChange change)
    {
        if (change.MinArgs is not { } min || change.MaxArgs is not { } max) return true;
        SyntaxNode callee = name.Parent is MemberAccessExpressionSyntax access && access.Name == name ? access : name;
        if (callee.Parent is not InvocationExpressionSyntax invocation || invocation.Expression != callee) return true;
        var count = invocation.ArgumentList.Arguments.Count + (change.IsExtension && callee is MemberAccessExpressionSyntax ? 1 : 0);
        return count >= min && count <= max;
    }

    /// <summary>
    /// A nested type is written through its outer type (<c>Outer.Inner</c>),
    /// so only that counts: a bare <c>Cloud</c> is far more likely a property
    /// of the same name (<c>context.Cloud.RoleName</c>) than the nested type
    /// <c>MetricDimensionNames.TelemetryContext.Cloud</c>.
    /// </summary>
    private static bool QualifiedIfNested(SimpleNameSyntax name, ApiType type)
    {
        var plus = type.FullName.LastIndexOf('+');
        if (plus < 0) return true;
        var outer = ApiSurface.StripArity(type.FullName[..plus].Split('.', '+')[^1]);
        var qualifier = name.Parent switch
        {
            QualifiedNameSyntax q when q.Right == name => q.Left,
            MemberAccessExpressionSyntax a when a.Name == name => a.Expression,
            _ => null,
        };
        return qualifier is not null && LastIdentifier(qualifier) == outer;
    }

    private static string? LastIdentifier(SyntaxNode node) => node switch
    {
        SimpleNameSyntax simple => simple.Identifier.Text,
        QualifiedNameSyntax qualified => qualified.Right.Identifier.Text,
        MemberAccessExpressionSyntax access => access.Name.Identifier.Text,
        AliasQualifiedNameSyntax alias => alias.Name.Identifier.Text,
        _ => null,
    };

    /// <summary>
    /// Whether an unchanged overload of the same name could take this use:
    /// a call whose argument count it accepts, or a method group (no call,
    /// so no count to tell them apart). Without semantic binding the site
    /// is then possible, not certain — the <c>Assert.AreEqual(a, b)</c>
    /// case, where a removed IEquatable overload and the unchanged generic
    /// one both take two arguments.
    /// </summary>
    private static bool MayBindElsewhere(SimpleNameSyntax name, ApiChange change)
    {
        if (change.UnchangedOverloads is not { Count: > 0 } unchanged) return false;
        SyntaxNode callee = name.Parent is MemberAccessExpressionSyntax access && access.Name == name ? access : name;
        if (callee.Parent is not InvocationExpressionSyntax invocation || invocation.Expression != callee) return true;
        var count = invocation.ArgumentList.Arguments.Count + (change.IsExtension && callee is MemberAccessExpressionSyntax ? 1 : 0);
        return unchanged.Any(r => count >= r.Min && count <= r.Max);
    }

    private static HashSet<string> Imports(CompilationUnitSyntax root) =>
        root.DescendantNodes().OfType<UsingDirectiveSyntax>()
            .Select(u => u.Alias is null ? u.Name?.ToString() : TargetNamespace(u.Name?.ToString()))
            .OfType<string>()
            .ToHashSet(StringComparer.Ordinal);

    /// <summary><c>using J = Newtonsoft.Json.JsonConvert;</c> imports Newtonsoft.Json's type.</summary>
    private static string? TargetNamespace(string? aliased) =>
        aliased is null ? null : aliased.LastIndexOf('.') is var dot and > 0 ? aliased[..dot] : aliased;

    private static bool IsDeclaration(SimpleNameSyntax name) =>
        name.Parent is BaseTypeDeclarationSyntax or MethodDeclarationSyntax or PropertyDeclarationSyntax;

    /// <summary>A use, not a declaration: <c>x.Member</c>, <c>Member(...)</c>,
    /// <c>?.Member</c>, or an initializer's <c>Member = …</c>.</summary>
    private static bool IsMemberUse(SimpleNameSyntax name) => name.Parent switch
    {
        MemberAccessExpressionSyntax access => access.Name == name,
        MemberBindingExpressionSyntax => true,
        InvocationExpressionSyntax => true,
        AssignmentExpressionSyntax { Parent: InitializerExpressionSyntax } assignment => assignment.Left == name,
        _ => false,
    };
}
