using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using static Fingerprinting.Outbound.DetectionSupport;

namespace Fingerprinting.Outbound;

/// <summary>A step 4 entry point as step 5 reads it (1.3.0): its id and
/// where its handler is.</summary>
public sealed record InboundEntryPoint(
    string EntryPointId, string ProjectPath, string Kind, string HandlerType, string? HandlerMember, string HandlerFile, int HandlerLineStart);

/// <summary>
/// Which outbound call sites each inbound entry point reaches (1.3.0) —
/// syntax only. Directly, when the call sits in the entry point's own
/// method; or through the methods it calls, in the same class or in another
/// class of the repository (by the receiver's declared type, or
/// <c>Type.Method()</c>), up to <see cref="MaxDepth"/> calls deep. A call on
/// an interface or abstract type goes to every class listing it as a base.
/// For each call: the depth, the methods walked (<c>Method</c> in the same
/// class, <c>Type.Method</c> across classes), and whether it is conditional
/// or inside a loop, read from the code between the entry point and the
/// call. A path deeper than <see cref="MaxDepth"/> is recorded as an
/// unfollowed path — never guessed; a receiver whose type is not declared in
/// the repository is not followed.
/// </summary>
public static partial class BackendReach
{
    public const int MaxDepth = 8;

    public const string Yes = "yes";
    public const string No = "no";
    public const string Unresolved = "unresolved";

    private sealed record Site(string InvocationId, string Mechanism, string? Operation, CallSite CallSite);

    /// <summary>A method to walk; <paramref name="Owner"/> is the class it belongs to.</summary>
    private sealed record Step(
        MethodDeclarationSyntax Method, string Owner, int Depth, IReadOnlyList<string> Via, IReadOnlyList<string> Context, bool Conditional, bool InLoop);

    /// <summary>Every project's types and files, indexed once.</summary>
    private sealed class TypeIndex
    {
        public TypeIndex(IReadOnlyList<ProjectSource> sources)
        {
            var types = sources.SelectMany(s => s.Types).ToList();
            ByName = types.ToLookup(t => t.Name, StringComparer.Ordinal);
            // An interface or abstract type → the types listing it as a base.
            ByBase = types.SelectMany(t => t.BaseNames.Select(b => (Base: b, Type: t))).ToLookup(p => p.Base, p => p.Type, StringComparer.Ordinal);
            foreach (var file in sources.SelectMany(s => s.Files))
            {
                Files.TryAdd(file.Root.SyntaxTree, file);
            }
        }

        public ILookup<string, DeclaredType> ByName { get; }

        public ILookup<string, DeclaredType> ByBase { get; }

        public Dictionary<SyntaxTree, ParsedFile> Files { get; } = [];
    }

    /// <summary>By project path, each entry point's reach.</summary>
    public static IReadOnlyDictionary<string, IReadOnlyList<EntryPointBackend>> Build(
        IReadOnlyList<ProjectSource> sources, IReadOnlyList<Invocation> invocations, IReadOnlyList<InboundEntryPoint> entryPoints)
    {
        var index = new TypeIndex(sources);
        var sites = Sites(invocations, sources, index);

        var result = new Dictionary<string, IReadOnlyList<EntryPointBackend>>(StringComparer.Ordinal);
        foreach (var group in entryPoints.GroupBy(e => e.ProjectPath, StringComparer.Ordinal))
        {
            var source = sources.FirstOrDefault(s => s.ProjectPath == group.Key);
            if (source is null)
            {
                continue;   // a project step 5 did not load (skipped, failed)
            }

            result[group.Key] = group
                .OrderBy(e => e.EntryPointId, StringComparer.Ordinal)
                .Select(e => Reach(e, source, index, sites))
                .ToList();
        }

        return result;
    }

    private static Dictionary<string, List<Site>> Sites(IReadOnlyList<Invocation> invocations, IReadOnlyList<ProjectSource> sources, TypeIndex index)
    {
        var sites = new List<Site>();
        var used = invocations.Where(i => i.Usage == Usages.Used).ToList();
        foreach (var invocation in used)
        {
            var operations = invocation.Operations.Where(o => o.Resolution != Resolutions.Unresolved).ToList();
            if (operations.Count > 0)
            {
                sites.AddRange(operations.Select(o => new Site(invocation.InvocationId, invocation.Mechanism, Label(o), o.CallSite)));
            }
            else
            {
                sites.AddRange(invocation.CallSites.Select(c => new Site(invocation.InvocationId, invocation.Mechanism, null, c)));
            }
        }

        // Where a database or an HTTP client is used, not only where it is configured; after the recorded sites, so
        // a call both record keeps the recorded label.
        sites.AddRange(UseSites(used, sources, index));

        return sites.GroupBy(s => s.CallSite.FilePath, StringComparer.Ordinal).ToDictionary(g => g.Key, g => g.ToList(), StringComparer.Ordinal);
    }

    private static string? Label(InvokedOperation operation) =>
        operation.Operation ?? (operation.Path is null ? null : $"{operation.Verb ?? "?"} {operation.Path}");

    private static EntryPointBackend Reach(
        InboundEntryPoint entryPoint, ProjectSource source, TypeIndex index, IReadOnlyDictionary<string, List<Site>> sites)
    {
        // Partial classes: every declaration of the type in the project.
        var declarations = source.Types.Where(t => t.Name == entryPoint.HandlerType).ToList();
        var methods = declarations.SelectMany(t => t.Syntax.Members.OfType<MethodDeclarationSyntax>()).ToList();
        var handler = entryPoint.HandlerMember is null
            ? null
            : methods.Where(m => m.Identifier.Text == entryPoint.HandlerMember)
                .OrderBy(m => Contains(m, entryPoint.HandlerLineStart) ? 0 : 1).FirstOrDefault();
        if (handler is null)
        {
            return new EntryPointBackend
            {
                EntryPointId = entryPoint.EntryPointId,
                Status = Unresolved,
                Unresolved =
                [
                    new UnfollowedPath
                    {
                        Reason = entryPoint.HandlerMember is null
                            ? "the entry point is a type, not a method; its handlers are not walked"
                            : $"handler method {entryPoint.HandlerType}.{entryPoint.HandlerMember} not found in source",
                        CallSite = CallSiteAt(entryPoint.HandlerFile, entryPoint.HandlerLineStart),
                    },
                ],
            };
        }

        var calls = new Dictionary<(string, string, int), BackendCall>();
        var unfollowed = new Dictionary<(string, string, int), UnfollowedPath>();
        var visited = new HashSet<MethodDeclarationSyntax>();
        var queue = new Queue<Step>();
        queue.Enqueue(new Step(handler, entryPoint.HandlerType, 0, [handler.Identifier.Text], [], false, false));

        while (queue.Count > 0)
        {
            var step = queue.Dequeue();
            if (!visited.Add(step.Method))
            {
                continue;
            }

            var file = index.Files[step.Method.SyntaxTree];
            foreach (var site in sites.GetValueOrDefault(file.RelativePath) ?? [])
            {
                if (!Contains(step.Method, site.CallSite.LineStart))
                {
                    continue;
                }

                var node = NodeAt(step.Method, site.CallSite.LineStart);
                var (context, conditional, inLoop) = Context(node, step.Method);
                var key = (site.InvocationId, site.CallSite.FilePath, site.CallSite.LineStart);
                calls.TryAdd(key, new BackendCall
                {
                    InvocationId = site.InvocationId,
                    Mechanism = site.Mechanism,
                    Operation = site.Operation,
                    CallSite = site.CallSite,
                    Depth = step.Depth,
                    Via = step.Via,
                    Conditional = step.Conditional || conditional,
                    InLoop = step.InLoop || inLoop,
                    Context = [.. step.Context, .. context],
                });
            }

            foreach (var invocation in step.Method.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var name = SyntaxHelpers.InvokedName(invocation);
                var receiver = SyntaxHelpers.Receiver(invocation);
                if (name is null)
                {
                    continue;
                }

                // This class (no receiver, or this), else Type.Method(), or a field, parameter or local of a declared type.
                var typeName = receiver is null or ThisExpressionSyntax
                    ? step.Owner
                    : ReceiverType(receiver)
                      ?? (receiver is IdentifierNameSyntax id && index.ByName.Contains(id.Identifier.Text) ? id.Identifier.Text : null);
                if (typeName is null)
                {
                    continue;
                }

                foreach (var (owner, target) in MethodsOf(index, typeName, name).Where(t => !visited.Contains(t.Method)))
                {
                    var hop = owner == step.Owner ? name : $"{owner}.{name}";
                    if (step.Depth + 1 > MaxDepth)
                    {
                        var at = CallSiteOf(file, invocation);
                        unfollowed.TryAdd((hop, at.FilePath, at.LineStart), new UnfollowedPath
                        {
                            Reason = $"{hop}: more than {MaxDepth} calls deep from {entryPoint.HandlerType}; not followed",
                            CallSite = at,
                        });
                        continue;
                    }

                    var (context, conditional, inLoop) = Context(invocation, step.Method);
                    queue.Enqueue(new Step(target, owner, step.Depth + 1, [.. step.Via, hop], [.. step.Context, .. context],
                        step.Conditional || conditional, step.InLoop || inLoop));
                }
            }
        }

        var orderedCalls = calls.Values
            .OrderBy(c => c.CallSite.FilePath, StringComparer.Ordinal).ThenBy(c => c.CallSite.LineStart)
            .ThenBy(c => c.InvocationId, StringComparer.Ordinal).ToList();
        var orderedUnfollowed = unfollowed.Values
            .OrderBy(u => u.CallSite.FilePath, StringComparer.Ordinal).ThenBy(u => u.CallSite.LineStart)
            .ThenBy(u => u.Reason, StringComparer.Ordinal).ToList();
        return new EntryPointBackend
        {
            EntryPointId = entryPoint.EntryPointId,
            Status = orderedCalls.Count > 0 ? Yes : orderedUnfollowed.Count > 0 ? Unresolved : No,
            Calls = orderedCalls,
            Unresolved = orderedUnfollowed,
        };
    }

    /// <summary>The methods a call to <paramref name="typeName"/>.<paramref name="name"/> can run, with the
    /// class each belongs to: the type's own (every partial declaration), else an in-repository base class's;
    /// and, for an interface or abstract type, those of every class listing it as a base.</summary>
    private static List<(string Owner, MethodDeclarationSyntax Method)> MethodsOf(TypeIndex index, string typeName, string name)
    {
        var found = new List<(string, MethodDeclarationSyntax)>();
        Collect(index, typeName, name, found, new HashSet<string>(StringComparer.Ordinal));
        return found;
    }

    private static void Collect(TypeIndex index, string typeName, string name, List<(string Owner, MethodDeclarationSyntax Method)> found, HashSet<string> seen)
    {
        if (!seen.Add(typeName))
        {
            return;
        }

        var declarations = index.ByName[typeName].ToList();
        var own = declarations.SelectMany(t => t.Syntax.Members.OfType<MethodDeclarationSyntax>())
            .Where(m => m.Identifier.Text == name && (m.Body is not null || m.ExpressionBody is not null)).ToList();
        found.AddRange(own.Select(m => (typeName, m)));

        if (own.Count == 0)
        {
            foreach (var baseName in declarations.SelectMany(t => t.BaseNames).Distinct(StringComparer.Ordinal))
            {
                if (index.ByName[baseName].Any(b => !b.IsInterface))
                {
                    Collect(index, baseName, name, found, seen);
                }
            }
        }

        if (declarations.Any(t => t.IsInterface || t.IsAbstract))
        {
            foreach (var implementation in index.ByBase[typeName].Where(t => !t.IsInterface))
            {
                Collect(index, implementation.Name, name, found, seen);
            }
        }
    }

    // ---------- syntax ----------

    private static bool Contains(SyntaxNode node, int line)
    {
        var (start, end) = SyntaxHelpers.Lines(node);
        return line >= start && line <= end;
    }

    /// <summary>The call on <paramref name="line"/>: the outermost invocation
    /// or creation starting there, else any node on the line.</summary>
    private static SyntaxNode NodeAt(SyntaxNode method, int line) =>
        method.DescendantNodes()
            .Where(n => n is InvocationExpressionSyntax or ObjectCreationExpressionSyntax && SyntaxHelpers.Lines(n).Start == line)
            .OrderBy(n => n.SpanStart).FirstOrDefault()
        ?? method.DescendantNodes().Where(n => SyntaxHelpers.Lines(n).Start == line).OrderBy(n => n.SpanStart).FirstOrDefault()
        ?? method;

    private static readonly HashSet<string> LoopingMethods = new(StringComparer.Ordinal)
    {
        "ForEach", "Select", "SelectMany", "Where", "All", "Any", "Aggregate", "ForEachAsync", "Parallel",
    };

    /// <summary>The conditions and loops between <paramref name="root"/> and
    /// <paramref name="node"/>, outermost first, as written: <c>if</c> and
    /// <c>else</c>, <c>switch</c> cases, <c>?:</c>, the right side of
    /// <c>&amp;&amp;</c>/<c>||</c>/<c>??</c>, <c>catch</c>, an earlier
    /// <c>if (…) return</c> in the same block, and <c>for</c>, <c>foreach</c>,
    /// <c>while</c>, <c>do</c> or a lambda passed to <c>ForEach</c>/<c>Select</c>.</summary>
    public static (IReadOnlyList<string> Context, bool Conditional, bool InLoop) Context(SyntaxNode node, SyntaxNode root)
    {
        var context = new List<string>();
        var conditional = false;
        var inLoop = false;
        var child = node;
        foreach (var ancestor in node.Ancestors())
        {
            if (ancestor == root)
            {
                break;
            }

            switch (ancestor)
            {
                case IfStatementSyntax ifStatement when ifStatement.Statement.Span.Contains(child.Span):
                    conditional = true;
                    context.Add($"if ({Text(ifStatement.Condition)})");
                    break;
                case IfStatementSyntax ifStatement when ifStatement.Else?.Span.Contains(child.Span) == true:
                    conditional = true;
                    context.Add($"else of if ({Text(ifStatement.Condition)})");
                    break;
                case SwitchSectionSyntax section:
                    conditional = true;
                    context.Add($"{Text(section.Labels.First())} of a switch");
                    break;
                case SwitchExpressionArmSyntax arm:
                    conditional = true;
                    context.Add($"switch arm {Text(arm.Pattern)}");
                    break;
                case ConditionalExpressionSyntax ternary when ternary.WhenTrue.Span.Contains(child.Span):
                    conditional = true;
                    context.Add($"{Text(ternary.Condition)} ? …");
                    break;
                case ConditionalExpressionSyntax ternary when ternary.WhenFalse.Span.Contains(child.Span):
                    conditional = true;
                    context.Add($"{Text(ternary.Condition)} ? … : (else)");
                    break;
                case BinaryExpressionSyntax binary when binary.Right.Span.Contains(child.Span)
                                                        && binary.Kind() is SyntaxKind.LogicalAndExpression or SyntaxKind.LogicalOrExpression or SyntaxKind.CoalesceExpression:
                    conditional = true;
                    context.Add($"right of {binary.OperatorToken.Text} after {Text(binary.Left)}");
                    break;
                case CatchClauseSyntax catchClause:
                    conditional = true;
                    context.Add(catchClause.Declaration is null ? "in catch" : $"in catch ({Text(catchClause.Declaration.Type)})");
                    break;
                case ForStatementSyntax forStatement:
                    inLoop = true;
                    context.Add($"for ({Text(forStatement.Condition)})");
                    break;
                case ForEachStatementSyntax forEach:
                    inLoop = true;
                    context.Add($"foreach ({forEach.Identifier.Text} in {Text(forEach.Expression)})");
                    break;
                case WhileStatementSyntax whileStatement:
                    inLoop = true;
                    context.Add($"while ({Text(whileStatement.Condition)})");
                    break;
                case DoStatementSyntax doStatement:
                    inLoop = true;
                    context.Add($"do … while ({Text(doStatement.Condition)})");
                    break;
                case LambdaExpressionSyntax lambda when lambda.Parent is ArgumentSyntax { Parent.Parent: InvocationExpressionSyntax call }
                                                       && SyntaxHelpers.InvokedName(call) is { } method && LoopingMethods.Contains(method):
                    inLoop = true;
                    context.Add($"in a lambda passed to {method}");
                    break;
                case BlockSyntax block when child is StatementSyntax statement:
                    // if (…) return; earlier in the same block: only some calls get here.
                    foreach (var guard in block.Statements.TakeWhile(s => s != statement).OfType<IfStatementSyntax>().Where(Exits))
                    {
                        conditional = true;
                        context.Add($"after early return: if ({Text(guard.Condition)})");
                    }

                    break;
            }

            child = ancestor;
        }

        context.Reverse();
        return (context, conditional, inLoop);
    }

    /// <summary>An <c>if</c> without <c>else</c> whose body always leaves:
    /// it ends in <c>return</c> or <c>throw</c>.</summary>
    private static bool Exits(IfStatementSyntax ifStatement) =>
        ifStatement.Else is null && ifStatement.Statement switch
        {
            ReturnStatementSyntax or ThrowStatementSyntax => true,
            BlockSyntax { Statements: [.., ReturnStatementSyntax or ThrowStatementSyntax] } => true,
            _ => false,
        };

    private static string Text(SyntaxNode? node)
    {
        if (node is null)
        {
            return "";
        }

        var text = string.Join(' ', node.ToString().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        return text.Length > 80 ? text[..77] + "..." : text;
    }
}
