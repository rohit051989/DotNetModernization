using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using static Fingerprinting.Outbound.DetectionSupport;

namespace Fingerprinting.Outbound;

/// <summary>
/// Call sites at the point of use (1.3.0), for the mechanisms the inventory records where they are
/// configured: a database is found at its connection string and an HTTP client at its registration,
/// so no method an entry point walks contains one. These sites are found in the code that uses them,
/// matched to the invocation by name — never guessed. Syntax only.
/// </summary>
public static partial class BackendReach
{
    private static readonly HashSet<string> ContextBases = new(StringComparer.Ordinal)
    {
        "DbContext", "IdentityDbContext", "ObjectContext",
    };

    /// <summary>A member of a context that reaches the database besides its sets.</summary>
    private static readonly HashSet<string> ContextMembers = new(StringComparer.Ordinal)
    {
        "Database", "Set", "Entry", "Add", "AddAsync", "AddRange", "AddRangeAsync", "Remove", "RemoveRange", "Update", "UpdateRange",
        "Attach", "Find", "FindAsync",
    };

    private const int MaxMembersInLabel = 3;

    private static List<Site> UseSites(IReadOnlyList<Invocation> invocations, IReadOnlyList<ProjectSource> sources, TypeIndex index)
    {
        var pairs = sources.SelectMany(s => s.Types.Select(t => (Source: s, Type: t))).ToList();
        var found = new List<Site>();
        found.AddRange(HttpUseSites(invocations.Where(i => i.Mechanism == Mechanisms.HttpClient && i.Http is not null).ToList(), pairs, index));
        found.AddRange(DatabaseUseSites(invocations.Where(i => i.Mechanism == Mechanisms.Database && i.Database?.Name is not null).ToList(), pairs, index));
        return found;
    }

    // ---------- HTTP ----------

    /// <summary><c>factory.CreateClient("name")</c>, and <c>helper.CallAsync("name", path, HttpMethod.Post, …)</c> on an
    /// HTTP helper, where the name is a literal or a constant of the repository. Matched to the invocation registered under
    /// that name; a name no registration carries (names read from configuration) goes to the one registration of the same
    /// project that names nothing, when there is exactly one.</summary>
    private static List<Site> HttpUseSites(
        IReadOnlyList<Invocation> clients, IReadOnlyList<(ProjectSource Source, DeclaredType Type)> pairs, TypeIndex index)
    {
        var found = new List<Site>();
        if (clients.Count == 0)
        {
            return found;
        }

        foreach (var (source, type) in pairs)
        {
            foreach (var call in type.Syntax.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var arguments = call.ArgumentList.Arguments;
                var name = SyntaxHelpers.InvokedName(call);
                string? clientName = null;
                string? verb = null;
                string? path = null;
                // CreateClient is also what a WCF helper calls its channel factory's method: only an HTTP factory counts.
                if (name == "CreateClient" && arguments.Count >= 1
                    && SyntaxHelpers.Receiver(call) is { } factory && ReceiverType(factory)?.Contains("Http", StringComparison.Ordinal) == true)
                {
                    clientName = ConstantString(arguments[0].Expression, type, index);
                    (verb, path) = ChainedRequest(call, type, index);
                }
                else if (name == "CallAsync" && arguments.Count >= 1
                         && (SyntaxHelpers.Receiver(call) is { } receiver && ReceiverType(receiver)?.Contains("Http", StringComparison.Ordinal) == true
                             || arguments.Any(a => a.Expression is MemberAccessExpressionSyntax { Expression: IdentifierNameSyntax { Identifier.Text: "HttpMethod" } })))
                {
                    clientName = ConstantString(arguments[0].Expression, type, index);
                    verb = arguments.Select(a => a.Expression).OfType<MemberAccessExpressionSyntax>()
                        .Where(m => m.Expression is IdentifierNameSyntax { Identifier.Text: "HttpMethod" })
                        .Select(m => m.Name.Identifier.Text.ToUpperInvariant()).FirstOrDefault();
                    path = arguments.Count >= 2 ? ConstantString(arguments[1].Expression, type, index) : null;
                }

                if (clientName is null)
                {
                    continue;
                }

                var targets = HttpTargets(clients, clientName, source.ProjectPath);
                if (targets.Count == 0)
                {
                    continue;
                }

                var label = string.Join(' ', new[] { verb, path, $"({clientName})" }.Where(p => !string.IsNullOrEmpty(p)));
                var at = CallSiteOf(index.Files[call.SyntaxTree], call);
                found.AddRange(targets.Select(t => new Site(t.InvocationId, Mechanisms.HttpClient, label, at)));
            }
        }

        return found;
    }

    private static List<Invocation> HttpTargets(IReadOnlyList<Invocation> clients, string clientName, string projectPath)
    {
        var named = clients.Where(c => c.Http!.ClientName == clientName).ToList();
        if (named.Count > 0)
        {
            return named;
        }

        var unnamed = clients.Where(c => c.Http!.ClientName is null && c.ProjectPath == projectPath).ToList();
        return unnamed.Count == 1 ? unnamed : [];
    }

    /// <summary><c>CreateClient("n").PostAsJsonAsync("path", …)</c>, or the same on the variable it is assigned to: the
    /// verb and path of the request made with it.</summary>
    private static (string? Verb, string? Path) ChainedRequest(InvocationExpressionSyntax create, DeclaredType within, TypeIndex index)
    {
        var request = SyntaxHelpers.ChainedCalls(create).FirstOrDefault();
        if (request is null && create.Parent is EqualsValueClauseSyntax { Parent: VariableDeclaratorSyntax holder })
        {
            request = create.Ancestors().OfType<MethodDeclarationSyntax>().FirstOrDefault()?.DescendantNodes().OfType<InvocationExpressionSyntax>()
                .FirstOrDefault(i => SyntaxHelpers.Receiver(i) is IdentifierNameSyntax receiver && receiver.Identifier.Text == holder.Identifier.Text
                                     && VerbOf(SyntaxHelpers.InvokedName(i)) is not null);
        }

        var verb = request is null ? null : VerbOf(SyntaxHelpers.InvokedName(request));
        var path = verb is not null && request!.ArgumentList.Arguments.Count >= 1 ? ConstantString(request.ArgumentList.Arguments[0].Expression, within, index) : null;
        return (verb, path);
    }

    /// <summary>The HTTP verb a request method is named for: <c>PostAsJsonAsync</c> is POST.</summary>
    private static string? VerbOf(string? method) => method switch
    {
        { } n when n.StartsWith("Get", StringComparison.Ordinal) => "GET",
        { } n when n.StartsWith("Post", StringComparison.Ordinal) => "POST",
        { } n when n.StartsWith("Put", StringComparison.Ordinal) => "PUT",
        { } n when n.StartsWith("Patch", StringComparison.Ordinal) => "PATCH",
        { } n when n.StartsWith("Delete", StringComparison.Ordinal) => "DELETE",
        _ => null,
    };

    // ---------- database ----------

    /// <summary>A method that uses a <c>DbContext</c> subclass of the repository — one of its sets, or
    /// <c>SaveChanges</c>, <c>Database</c>, <c>Set&lt;T&gt;</c> and the like — reaches the databases that context is
    /// registered with. The registration names the connection (<c>AddDbContext&lt;T&gt;(… "name")</c>, or a helper
    /// taking the context as a type argument and the name as a literal or constant); a context with no such name
    /// is not matched.</summary>
    private static List<Site> DatabaseUseSites(
        IReadOnlyList<Invocation> databases, IReadOnlyList<(ProjectSource Source, DeclaredType Type)> pairs, TypeIndex index)
    {
        var found = new List<Site>();
        if (databases.Count == 0)
        {
            return found;
        }

        var contexts = ContextTypes(pairs.Select(p => p.Type));
        if (contexts.Count == 0)
        {
            return found;
        }

        var names = ConnectionNames(pairs, contexts, index);
        var targets = contexts.ToDictionary(
            c => c,
            c => databases.Where(d => names.TryGetValue(c, out var n) && n.Contains(d.Database!.Name!)).ToList(),
            StringComparer.Ordinal);
        var sets = contexts.ToDictionary(c => c, c => SetNames(c, index, new HashSet<string>(StringComparer.Ordinal)), StringComparer.Ordinal);

        foreach (var (_, type) in pairs)
        {
            if (contexts.Contains(type.Name))
            {
                continue;   // the context's own members are its configuration, not a use
            }

            var file = index.Files[type.Syntax.SyntaxTree];
            var held = HeldContexts(type.Syntax.ParameterList?.Parameters.Select(p => (p.Identifier.Text, p.Type)), contexts);
            foreach (var member in type.Syntax.Members)
            {
                switch (member)
                {
                    case FieldDeclarationSyntax field:
                        foreach (var variable in field.Declaration.Variables)
                        {
                            AddHeld(held, variable.Identifier.Text, field.Declaration.Type, contexts);
                        }

                        break;
                    case PropertyDeclarationSyntax property:
                        AddHeld(held, property.Identifier.Text, property.Type, contexts);
                        break;
                }
            }

            foreach (var method in type.Syntax.Members.OfType<MethodDeclarationSyntax>())
            {
                var holders = new Dictionary<string, string>(held, StringComparer.Ordinal);
                foreach (var parameter in method.ParameterList.Parameters)
                {
                    AddHeld(holders, parameter.Identifier.Text, parameter.Type, contexts);
                }

                foreach (var declaration in method.DescendantNodes().OfType<VariableDeclarationSyntax>())
                {
                    foreach (var variable in declaration.Variables)
                    {
                        AddHeld(holders, variable.Identifier.Text, declaration.Type, contexts);
                    }
                }

                if (holders.Count == 0)
                {
                    continue;
                }

                foreach (var group in ContextUses(method, holders, sets).GroupBy(u => u.Context, StringComparer.Ordinal))
                {
                    var first = group.OrderBy(u => u.Top.SpanStart).First();
                    var members = string.Join(", ", group.Select(u => u.Member).Distinct(StringComparer.Ordinal).Take(MaxMembersInLabel));
                    var at = CallSiteOf(file, first.Top);
                    found.AddRange(targets[group.Key].Select(t => new Site(t.InvocationId, Mechanisms.Database, $"{t.Database!.Name}: {members}", at)));
                }
            }
        }

        return found;
    }

    /// <summary>The repository's context classes: those listing a context base, directly or through another.</summary>
    private static HashSet<string> ContextTypes(IEnumerable<DeclaredType> types)
    {
        var all = types.ToList();
        var contexts = new HashSet<string>(StringComparer.Ordinal);
        bool grew;
        do
        {
            grew = false;
            foreach (var type in all.Where(t => !contexts.Contains(t.Name) && t.BaseNames.Any(b => ContextBases.Contains(b) || contexts.Contains(b))))
            {
                grew |= contexts.Add(type.Name);
            }
        }
        while (grew);
        return contexts;
    }

    /// <summary>For each context, the connection names its registration or its own configuration carries.</summary>
    private static Dictionary<string, HashSet<string>> ConnectionNames(
        IReadOnlyList<(ProjectSource Source, DeclaredType Type)> pairs, IReadOnlySet<string> contexts, TypeIndex index)
    {
        var names = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        void Add(string context, SyntaxNode scope, DeclaredType within)
        {
            if (!names.TryGetValue(context, out var set))
            {
                names[context] = set = new HashSet<string>(StringComparer.Ordinal);
            }

            foreach (var argument in scope.DescendantNodesAndSelf().OfType<ArgumentSyntax>())
            {
                if (ConstantString(argument.Expression, within, index) is { } value)
                {
                    set.Add(value);
                }
            }
        }

        foreach (var (_, type) in pairs)
        {
            if (contexts.Contains(type.Name))
            {
                Add(type.Name, type.Syntax, type);   // OnConfiguring / constructor: GetConnectionString("name")
            }

            foreach (var call in type.Syntax.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var generic = call.Expression switch
                {
                    GenericNameSyntax g => g,
                    MemberAccessExpressionSyntax { Name: GenericNameSyntax g } => g,
                    _ => null,
                };
                foreach (var argument in generic?.TypeArgumentList.Arguments ?? default)
                {
                    if (DeclaredTypeName(argument) is { } context && contexts.Contains(context))
                    {
                        Add(context, call, type);
                    }
                }
            }
        }

        return names;
    }

    /// <summary>The properties of a context (and of the contexts it derives from) that are sets.</summary>
    private static HashSet<string> SetNames(string context, TypeIndex index, HashSet<string> seen)
    {
        var sets = new HashSet<string>(StringComparer.Ordinal);
        if (!seen.Add(context))
        {
            return sets;
        }

        foreach (var type in index.ByName[context])
        {
            sets.UnionWith(type.Syntax.Members.OfType<PropertyDeclarationSyntax>()
                .Where(p => DeclaredTypeName(p.Type) is "DbSet" or "DbQuery")
                .Select(p => p.Identifier.Text));
            foreach (var baseName in type.BaseNames.Where(b => index.ByName.Contains(b)))
            {
                sets.UnionWith(SetNames(baseName, index, seen));
            }
        }

        return sets;
    }

    private static Dictionary<string, string> HeldContexts(IEnumerable<(string Name, TypeSyntax? Type)>? declared, IReadOnlySet<string> contexts)
    {
        var held = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (name, type) in declared ?? [])
        {
            AddHeld(held, name, type, contexts);
        }

        return held;
    }

    private static void AddHeld(Dictionary<string, string> held, string name, TypeSyntax? type, IReadOnlySet<string> contexts)
    {
        if (type is not null && DeclaredTypeName(type) is { } typeName && contexts.Contains(typeName))
        {
            held[name] = typeName;
        }
    }

    /// <summary>Each use of a held context in a method: <c>_db.Accounts…</c>, <c>this._db.SaveChangesAsync()</c>. The
    /// node is the whole chain, so its line is where the statement reads.</summary>
    private static List<(SyntaxNode Top, string Context, string Member)> ContextUses(
        MethodDeclarationSyntax method, IReadOnlyDictionary<string, string> holders, IReadOnlyDictionary<string, HashSet<string>> sets)
    {
        var uses = new List<(SyntaxNode, string, string)>();
        foreach (var identifier in method.DescendantNodes().OfType<IdentifierNameSyntax>())
        {
            if (!holders.TryGetValue(identifier.Identifier.Text, out var context))
            {
                continue;
            }

            SyntaxNode holder = identifier;
            if (identifier.Parent is MemberAccessExpressionSyntax named && named.Name == identifier)
            {
                if (named.Expression is not ThisExpressionSyntax)
                {
                    continue;   // someone else's member of the same name
                }

                holder = named;
            }

            if (holder.Parent is not MemberAccessExpressionSyntax access || access.Expression != holder)
            {
                continue;
            }

            var member = access.Name.Identifier.Text;
            if (!sets[context].Contains(member) && !ContextMembers.Contains(member)
                && !member.StartsWith("SaveChanges", StringComparison.Ordinal) && !member.StartsWith("FromSql", StringComparison.Ordinal))
            {
                continue;
            }

            SyntaxNode top = access;
            while (IsChainParent(top))
            {
                top = top.Parent!;
            }

            uses.Add((top, context, member));
        }

        return uses;
    }

    /// <summary>Whether <paramref name="node"/> is the receiver or callee of its parent, so the chain goes on.</summary>
    private static bool IsChainParent(SyntaxNode node) => node.Parent switch
    {
        MemberAccessExpressionSyntax m => m.Expression == node,
        InvocationExpressionSyntax i => i.Expression == node,
        ElementAccessExpressionSyntax e => e.Expression == node,
        _ => false,
    };

    // ---------- names ----------

    private static string? DeclaredTypeName(TypeSyntax type) => type switch
    {
        IdentifierNameSyntax id => id.Identifier.Text,
        GenericNameSyntax generic => generic.Identifier.Text,
        QualifiedNameSyntax qualified => DeclaredTypeName(qualified.Right),
        NullableTypeSyntax nullable => DeclaredTypeName(nullable.ElementType),
        _ => null,
    };

    /// <summary>A literal, or a <c>const</c> / <c>static readonly</c> string of the repository: <c>Name</c> in the same
    /// class, or <c>Type.Name</c>.</summary>
    private static string? ConstantString(ExpressionSyntax expression, DeclaredType within, TypeIndex index) => expression switch
    {
        _ when SyntaxHelpers.StringValue(expression) is { } literal => literal,
        IdentifierNameSyntax id => FieldString(within.Name, id.Identifier.Text, index),
        MemberAccessExpressionSyntax { Expression: IdentifierNameSyntax owner } member => FieldString(owner.Identifier.Text, member.Name.Identifier.Text, index),
        _ => null,
    };

    private static string? FieldString(string typeName, string field, TypeIndex index) =>
        index.ByName[typeName].SelectMany(t => t.Syntax.Members.OfType<FieldDeclarationSyntax>())
            .Where(f => f.Modifiers.Any(m => m.Text is "const" or "readonly"))
            .SelectMany(f => f.Declaration.Variables)
            .Where(v => v.Identifier.Text == field)
            .Select(v => SyntaxHelpers.StringValue(v.Initializer?.Value))
            .FirstOrDefault(v => v is not null);
}
