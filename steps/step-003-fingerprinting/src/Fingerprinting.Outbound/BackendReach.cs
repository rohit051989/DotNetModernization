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
/// method; or through methods of the same class it calls, up to
/// <see cref="MaxDepth"/> calls deep. For each call: the depth, the methods
/// walked, and whether it is conditional or inside a loop, read from the
/// code between the entry point and the call. A call into another class or
/// an injected dependency that itself makes backend calls is recorded as an
/// unfollowed path — never guessed — as is a same-class path deeper than
/// <see cref="MaxDepth"/>.
/// </summary>
public static class BackendReach
{
    public const int MaxDepth = 3;

    public const string Yes = "yes";
    public const string No = "no";
    public const string Unresolved = "unresolved";

    private sealed record Site(string InvocationId, string Mechanism, string? Operation, CallSite CallSite);

    private sealed record Step(MethodDeclarationSyntax Method, int Depth, IReadOnlyList<string> Via, IReadOnlyList<string> Context, bool Conditional, bool InLoop);

    /// <summary>By project path, each entry point's reach.</summary>
    public static IReadOnlyDictionary<string, IReadOnlyList<EntryPointBackend>> Build(
        IReadOnlyList<ProjectSource> sources, IReadOnlyList<Invocation> invocations, IReadOnlyList<InboundEntryPoint> entryPoints)
    {
        var sites = Sites(invocations);
        var types = sources.SelectMany(s => s.Types).ToList();
        var backendTypes = types.Where(t => sites.TryGetValue(t.File.RelativePath, out var inFile) && inFile.Any(s => Contains(t.Syntax, s.CallSite.LineStart)))
            .Select(t => t.Name).ToHashSet(StringComparer.Ordinal);
        // An interface or base class is a backend type when a class implementing it is.
        foreach (var type in types.Where(t => backendTypes.Contains(t.Name)).ToList())
        {
            backendTypes.UnionWith(type.BaseNames);
        }

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
                .Select(e => Reach(e, source, types, sites, backendTypes))
                .ToList();
        }

        return result;
    }

    private static Dictionary<string, List<Site>> Sites(IReadOnlyList<Invocation> invocations)
    {
        var sites = new List<Site>();
        foreach (var invocation in invocations.Where(i => i.Usage == Usages.Used))
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

        return sites.GroupBy(s => s.CallSite.FilePath, StringComparer.Ordinal).ToDictionary(g => g.Key, g => g.ToList(), StringComparer.Ordinal);
    }

    private static string? Label(InvokedOperation operation) =>
        operation.Operation ?? (operation.Path is null ? null : $"{operation.Verb ?? "?"} {operation.Path}");

    private static EntryPointBackend Reach(
        InboundEntryPoint entryPoint, ProjectSource source, IReadOnlyList<DeclaredType> types,
        IReadOnlyDictionary<string, List<Site>> sites, IReadOnlySet<string> backendTypes)
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

        var byName = methods.ToLookup(m => m.Identifier.Text, StringComparer.Ordinal);
        var calls = new Dictionary<(string, string, int), BackendCall>();
        var unfollowed = new Dictionary<(string, string, int), UnfollowedPath>();
        var visited = new HashSet<MethodDeclarationSyntax>();
        var queue = new Queue<Step>();
        queue.Enqueue(new Step(handler, 0, [handler.Identifier.Text], [], false, false));

        while (queue.Count > 0)
        {
            var step = queue.Dequeue();
            if (!visited.Add(step.Method))
            {
                continue;
            }

            var file = FileOf(source, step.Method);
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

                if ((receiver is null or ThisExpressionSyntax) && byName.Contains(name))
                {
                    foreach (var target in byName[name].Where(t => !visited.Contains(t)))
                    {
                        var (context, conditional, inLoop) = Context(invocation, step.Method);
                        if (step.Depth + 1 > MaxDepth)
                        {
                            var at = CallSiteOf(file, invocation);
                            unfollowed.TryAdd((name, at.FilePath, at.LineStart), new UnfollowedPath
                            {
                                Reason = $"{name}: more than {MaxDepth} calls deep in {entryPoint.HandlerType}; not followed",
                                CallSite = at,
                            });
                            continue;
                        }

                        queue.Enqueue(new Step(target, step.Depth + 1, [.. step.Via, name], [.. step.Context, .. context],
                            step.Conditional || conditional, step.InLoop || inLoop));
                    }

                    continue;
                }

                if (receiver is null)
                {
                    continue;
                }

                // Another class: Type.Method(), or a field, parameter or local of a type.
                var typeName = ReceiverType(receiver)
                               ?? (receiver is IdentifierNameSyntax id && types.Any(t => t.Name == id.Identifier.Text) ? id.Identifier.Text : null);
                if (typeName is null || typeName == entryPoint.HandlerType || !backendTypes.Contains(typeName))
                {
                    continue;
                }

                var injected = types.Any(t => t.Name == typeName && t.IsInterface) || IsConstructorInjected(receiver, declarations);
                var site = CallSiteOf(file, invocation);
                unfollowed.TryAdd((typeName + "." + name, site.FilePath, site.LineStart), new UnfollowedPath
                {
                    Reason = $"{typeName}.{name}: {(injected ? "a dependency-injected" : "another")} class that makes backend calls; " +
                             "paths through other classes are not followed",
                    CallSite = site,
                });
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

    /// <summary>A field assigned from a constructor parameter.</summary>
    private static bool IsConstructorInjected(ExpressionSyntax receiver, IReadOnlyList<DeclaredType> declarations)
    {
        var name = receiver switch
        {
            IdentifierNameSyntax id => id.Identifier.Text,
            MemberAccessExpressionSyntax { Expression: ThisExpressionSyntax } member => member.Name.Identifier.Text,
            _ => null,
        };
        if (name is null)
        {
            return false;
        }

        return declarations.SelectMany(d => d.Syntax.Members.OfType<ConstructorDeclarationSyntax>())
            .Any(c => c.DescendantNodes().OfType<AssignmentExpressionSyntax>().Any(a =>
                (a.Left is IdentifierNameSyntax l && l.Identifier.Text == name
                 || a.Left is MemberAccessExpressionSyntax { Name.Identifier.Text: var n } && n == name)
                && a.Right is IdentifierNameSyntax r && c.ParameterList.Parameters.Any(p => p.Identifier.Text == r.Identifier.Text)));
    }

    // ---------- syntax ----------

    private static ParsedFile FileOf(ProjectSource source, SyntaxNode node) =>
        source.Files.First(f => f.Root.SyntaxTree == node.SyntaxTree);

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
