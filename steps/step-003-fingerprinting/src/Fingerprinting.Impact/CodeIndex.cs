using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Impact;

/// <summary>
/// One syntax pass over the repository for impact-analysis's traversal primitives
/// (33-IMPACT-ANALYSIS Part E): declared types with their attributes, base types and
/// member signatures; the names each file references; reflection markers;
/// configuration files; and convention files (.svc, .asmx, svcutil proxies,
/// WSDL, Web Forms markup). Everything stays inside the repository.
/// </summary>
public sealed class CodeIndex
{
    public sealed record Member(string Name, IReadOnlyList<string> SignatureNames);

    public sealed record TypeInfo(
        string Name, string? Namespace, string QualifiedName, string Kind, string File,
        IReadOnlySet<string> Attributes, IReadOnlyList<string> BaseNames, IReadOnlyList<Member> Members, IReadOnlyList<string> Usings)
    {
        public string FullName => Namespace is null ? QualifiedName : $"{Namespace}.{QualifiedName}";

        /// <summary>IOrderService → OrderService, for proposed paths.</summary>
        public string BaseName => Name.Length > 2 && Name[0] == 'I' && char.IsUpper(Name[1]) ? Name[1..] : Name;
    }

    public sealed record ConfigFile(string Path, XDocument Document);

    public sealed record ConventionFile(string Path, string Kind, string? Target, string Text);

    private static readonly Regex DirectiveTarget = new(@"(?i)\b(Service|Class|Inherits)\s*=\s*""([^""]+)""", RegexOptions.Compiled);
    private static readonly string[] ReflectionMarkers = ["Type.GetType", "Activator.CreateInstance", "Assembly.Load", "Assembly.LoadFrom", "GetMethod", "InvokeMember"];

    public List<TypeInfo> Types { get; } = [];
    public Dictionary<string, List<TypeInfo>> TypesByName { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, HashSet<string>> ReferencedNames { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, List<string>> Reflection { get; } = new(StringComparer.Ordinal);
    public List<ConfigFile> Configs { get; } = [];
    public List<ConventionFile> Conventions { get; } = [];
    public HashSet<string> GeneratedFiles { get; } = new(StringComparer.Ordinal);

    /// <summary>Every file in the repository, so a proposed new file that already exists is seen.</summary>
    public HashSet<string> Files { get; } = new(StringComparer.OrdinalIgnoreCase);

    public static async Task<CodeIndex> BuildAsync(string repositoryRoot, CancellationToken ct)
    {
        var index = new CodeIndex();
        foreach (var absolute in FileSystemWalk.EnumerateFiles(repositoryRoot, ct).Order(StringComparer.Ordinal))
        {
            var path = FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, absolute);
            index.Files.Add(path);
            var name = Path.GetFileName(path).ToLowerInvariant();
            var extension = Path.GetExtension(name);
            if (extension == ".cs")
            {
                await index.AddSourceAsync(path, absolute, ct);
            }
            else if (extension == ".config" && !name.EndsWith(".exe.config", StringComparison.Ordinal))
            {
                try
                {
                    index.Configs.Add(new ConfigFile(path, XDocument.Load(absolute, LoadOptions.SetLineInfo)));
                }
                catch (XmlException)
                {
                    // An unreadable config file is not traversed.
                }
            }
            else if (extension is ".svc" or ".asmx" or ".aspx" or ".ascx" or ".master" or ".asax" or ".wsdl" or ".xsd")
            {
                var text = await File.ReadAllTextAsync(absolute, ct);
                var kind = extension switch
                {
                    ".svc" => "svc", ".asmx" => "asmx", ".wsdl" or ".xsd" => "wsdl", _ => "webforms_markup",
                };
                var target = kind == "wsdl" ? null : DirectiveTarget.Matches(text).Select(m => m.Groups[2].Value.Split(',')[0].Trim()).FirstOrDefault();
                index.Conventions.Add(new ConventionFile(path, kind, target, kind == "wsdl" ? text : ""));
            }
        }

        foreach (var type in index.Types)
        {
            if (!index.TypesByName.TryGetValue(type.Name, out var list)) index.TypesByName[type.Name] = list = [];
            list.Add(type);
        }

        return index;
    }

    private async Task AddSourceAsync(string path, string absolute, CancellationToken ct)
    {
        var text = await File.ReadAllTextAsync(absolute, ct);
        var root = await Microsoft.CodeAnalysis.CSharp.CSharpSyntaxTree.ParseText(text, cancellationToken: ct).GetRootAsync(ct);
        var name = Path.GetFileName(path);
        var generated = name.EndsWith(".designer.cs", StringComparison.OrdinalIgnoreCase) || name.EndsWith(".g.cs", StringComparison.OrdinalIgnoreCase)
                        || name.Equals("Reference.cs", StringComparison.OrdinalIgnoreCase) || text.Contains("<auto-generated", StringComparison.Ordinal);
        if (generated) GeneratedFiles.Add(path);
        if (name.Equals("Reference.cs", StringComparison.OrdinalIgnoreCase))
        {
            Conventions.Add(new ConventionFile(path, "reference", null, text));
        }

        var usings = root.DescendantNodes().OfType<UsingDirectiveSyntax>().Where(u => u.Name is not null).Select(u => u.Name!.ToString()).Distinct().ToList();
        foreach (var declaration in root.DescendantNodes().OfType<BaseTypeDeclarationSyntax>())
        {
            var attributes = declaration.AttributeLists.SelectMany(l => l.Attributes).Select(a => SimpleName(a.Name)).ToHashSet(StringComparer.Ordinal);
            var bases = declaration.BaseList?.Types.Select(t => MainName(t.Type)).Where(n => n is not null).Select(n => n!).ToList() ?? [];
            var members = new List<Member>();
            if (declaration is TypeDeclarationSyntax typeDeclaration)
            {
                foreach (var member in typeDeclaration.Members)
                {
                    switch (member)
                    {
                        case MethodDeclarationSyntax method:
                            members.Add(new Member(method.Identifier.Text,
                                [.. Names(method.ReturnType), .. method.ParameterList.Parameters.SelectMany(p => p.Type is null ? [] : Names(p.Type))]));
                            break;
                        case PropertyDeclarationSyntax property:
                            members.Add(new Member(property.Identifier.Text, Names(property.Type)));
                            break;
                    }
                }
            }

            Types.Add(new TypeInfo(
                declaration.Identifier.Text, NamespaceOf(declaration), QualifiedName(declaration),
                declaration switch
                {
                    InterfaceDeclarationSyntax => "interface", EnumDeclarationSyntax => "enum", StructDeclarationSyntax => "struct",
                    RecordDeclarationSyntax => "record", _ => "class",
                },
                path, attributes, bases, members, usings));
        }

        ReferencedNames[path] = root.DescendantNodes().OfType<SimpleNameSyntax>()
            .Where(n => !(n.Parent is MemberAccessExpressionSyntax access && access.Name == n) && n.Parent is not AttributeSyntax)
            .Select(n => n.Identifier.Text).ToHashSet(StringComparer.Ordinal);

        var markers = ReflectionMarkers.Where(m => text.Contains(m, StringComparison.Ordinal)).ToList();
        if (markers.Count > 0) Reflection[path] = markers;
    }

    /// <summary>The types a name resolves to, preferring one the referencing
    /// type can see (same namespace, or imported). Ambiguous: possible.</summary>
    public (IReadOnlyList<TypeInfo> Types, bool Unique) Resolve(string name, TypeInfo? from)
    {
        if (!TypesByName.TryGetValue(name, out var candidates)) return ([], false);
        if (candidates.Count == 1) return (candidates, true);
        if (from is not null)
        {
            var visible = candidates.Where(c => c.Namespace is not null
                                                && (c.Namespace == from.Namespace || from.Usings.Contains(c.Namespace)
                                                    || (from.Namespace?.StartsWith(c.Namespace + ".", StringComparison.Ordinal) ?? false)))
                .ToList();
            if (visible.Count == 1) return (visible, true);
            // Copies of one codebase in one repository (two solutions holding
            // the same project) declare identical full names: the reference
            // binds to the copy nearest the referencing file.
            if (visible.Count > 1 && visible.Select(c => c.FullName).Distinct().Count() == 1
                && Nearest(visible, from.File) is var nearest && OneCopy(nearest))
            {
                return (nearest, true);
            }
        }

        return (candidates, false);
    }

    /// <summary>Whether some declared type has exactly this full name — then
    /// a name match by simple name alone means that type, not another.</summary>
    public bool Declares(string fullName) => (_fullNames ??= Types.Select(t => t.FullName).ToHashSet(StringComparer.Ordinal)).Contains(fullName);

    private HashSet<string>? _fullNames;

    /// <summary>Whether a file naming <paramref name="type"/> by full name
    /// (an .svc directive, a config element) means this declaration: always
    /// when the full name is declared in one place (one file, or one
    /// directory's partial files); when copies of the codebase declare it
    /// too, only if this copy is the one nearest the file.</summary>
    public bool IsNearestCopy(TypeInfo type, string file)
    {
        var copies = (TypesByName.GetValueOrDefault(type.Name) ?? []).Where(t => t.FullName == type.FullName).ToList();
        if (copies.Count <= 1) return true;
        var nearest = Nearest(copies, file);
        return OneCopy(nearest) && nearest.Contains(type);
    }

    /// <summary>Declarations in one directory are one copy: a partial class
    /// split across Default.aspx.cs and Default.aspx.designer.cs.</summary>
    private static bool OneCopy(List<TypeInfo> declarations) =>
        declarations.Select(d => Path.GetDirectoryName(d.File)).Distinct(StringComparer.OrdinalIgnoreCase).Count() == 1;

    /// <summary>The candidates whose file shares the most leading directories with <paramref name="file"/>.</summary>
    private static List<TypeInfo> Nearest(IReadOnlyList<TypeInfo> candidates, string file)
    {
        var target = file.Split('/');
        int Shared(TypeInfo t)
        {
            var parts = t.File.Split('/');
            var n = 0;
            while (n < parts.Length - 1 && n < target.Length - 1 && string.Equals(parts[n], target[n], StringComparison.OrdinalIgnoreCase)) n++;
            return n;
        }

        var best = candidates.Max(Shared);
        return candidates.Where(c => Shared(c) == best).ToList();
    }

    private static IReadOnlyList<string> Names(TypeSyntax type) =>
        type.DescendantNodesAndSelf().OfType<SimpleNameSyntax>().Select(n => n.Identifier.Text).Distinct().ToList();

    private static string? MainName(TypeSyntax type) => type switch
    {
        QualifiedNameSyntax q => q.Right.Identifier.Text,
        SimpleNameSyntax s => s.Identifier.Text,
        _ => null,
    };

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

    private static string QualifiedName(BaseTypeDeclarationSyntax declaration) =>
        string.Join(".", declaration.AncestorsAndSelf().OfType<BaseTypeDeclarationSyntax>().Reverse().Select(t => t.Identifier.Text));

    private static string? NamespaceOf(SyntaxNode node)
    {
        var parts = node.Ancestors().OfType<BaseNamespaceDeclarationSyntax>().Select(n => n.Name.ToString()).Reverse().ToList();
        return parts.Count == 0 ? null : string.Join(".", parts);
    }
}
