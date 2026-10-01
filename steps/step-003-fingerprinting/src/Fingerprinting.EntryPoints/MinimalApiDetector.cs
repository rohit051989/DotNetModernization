using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

/// <summary>
/// <c>http_minimal_api</c> — Part B1: <c>MapGet</c>, <c>MapPost</c>,
/// <c>MapPut</c>, <c>MapDelete</c>, <c>MapPatch</c>, <c>MapMethods</c>.
/// Part B2: <c>MapGroup</c> prefixes are composed where statically
/// resolvable — a literal, chained or through a local — and a prefix held in
/// a variable, or a group handed in by a caller, is recorded unresolved.
/// </summary>
public sealed class MinimalApiDetector : IEntryPointDetector
{
    private static readonly IReadOnlyDictionary<string, string> MapVerbs = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["MapGet"] = "GET",
        ["MapPost"] = "POST",
        ["MapPut"] = "PUT",
        ["MapDelete"] = "DELETE",
        ["MapPatch"] = "PATCH",
    };

    /// <summary>Endpoint conventions that can sit between a group and the
    /// Map call without changing the route.</summary>
    private static readonly IReadOnlySet<string> Conventions = new HashSet<string>(StringComparer.Ordinal)
    {
        "RequireAuthorization", "AllowAnonymous", "WithTags", "WithOpenApi", "WithName", "WithGroupName",
        "WithDescription", "WithSummary", "WithDisplayName", "WithMetadata", "AddEndpointFilter", "RequireCors",
        "RequireRateLimiting", "DisableRateLimiting", "CacheOutput", "Produces", "ProducesProblem",
        "ProducesValidationProblem", "ExcludeFromDescription", "RequireHost", "DisableAntiforgery",
    };

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        foreach (var file in project.Files)
        {
            foreach (var invocation in file.Root.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var name = SyntaxHelpers.InvokedName(invocation);
                if (name is null || (name != "MapMethods" && !MapVerbs.ContainsKey(name))
                    || invocation.Expression is not MemberAccessExpressionSyntax member)
                {
                    continue;
                }

                var arguments = invocation.ArgumentList.Arguments;
                if (arguments.Count < (name == "MapMethods" ? 3 : 2))
                {
                    continue;
                }

                foreach (var entry in Build(context, file, invocation, member.Expression, name))
                {
                    yield return entry;
                }
            }
        }
    }

    private sealed record GroupResolution(List<string> Prefixes, string? Unresolved, List<InvocationExpressionSyntax> ConventionCalls);

    private static IEnumerable<DetectedEntryPoint> Build(
        DetectionContext context, ParsedFile file, InvocationExpressionSyntax invocation, ExpressionSyntax receiver, string name)
    {
        var project = context.Project;
        var arguments = invocation.ArgumentList.Arguments;
        var patternArgument = Named(arguments, "pattern") ?? arguments[0];
        var handlerArgument = Named(arguments, "handler") ?? arguments[^1];
        var confidence = new Confidence();

        var mapped = SyntaxHelpers.StringValue(patternArgument.Expression);
        if (mapped is null)
        {
            confidence.Reduce(0.5, $"route pattern is not a literal: {SyntaxHelpers.Collapse(patternArgument.Expression.ToString())}");
        }

        IReadOnlyList<string> verbs = name == "MapMethods"
            ? MapMethodsVerbs(Named(arguments, "httpMethods") ?? arguments[1], confidence)
            : [MapVerbs[name]];

        var group = ResolveGroup(receiver, invocation, confidence, depth: 0);
        GroupPrefix? groupPrefix = null;
        string? template = null;
        if (group.Unresolved is not null)
        {
            confidence.Reduce(0.6, $"MapGroup prefix is not statically resolvable: {group.Unresolved}");
            groupPrefix = new GroupPrefix { Resolution = "unresolved", Expression = group.Unresolved };
        }
        else
        {
            if (group.Prefixes.Count > 0)
            {
                groupPrefix = new GroupPrefix { Resolution = "resolved", Prefix = RouteTemplates.JoinSegments(group.Prefixes) };
            }

            if (mapped is not null)
            {
                template = RouteTemplates.JoinSegments(group.Prefixes.Append(mapped));
            }
        }

        // Authorisation: attributes on the lambda, conventions chained on the
        // Map call and on its groups, and a project-wide fallback policy.
        var authorisation = new AuthorisationState();
        foreach (var call in group.ConventionCalls)
        {
            authorisation.AddConventionCall(call);
        }

        if (handlerArgument.Expression is LambdaExpressionSyntax lambdaWithAttributes)
        {
            authorisation.AddAttributes(lambdaWithAttributes.AttributeLists);
        }

        foreach (var chained in SyntaxHelpers.ChainedCalls(invocation))
        {
            authorisation.AddConventionCall(chained);
        }

        authorisation.AddGlobal(context.Conventions.EndpointAuthorisation);

        var (handler, form, parameterList, returnType, signature) = Handler(project, file, invocation, handlerArgument.Expression);
        var http = new HttpDetail
        {
            Verb = verbs[0],
            RouteTemplate = template,
            Routing = HttpRouting.MinimalApi,
            Parameters = HttpParameters.Build(parameterList, template ?? mapped, BindingInference.MinimalApi),
            ReturnType = returnType,
            Authorisation = authorisation.Text,
            MappedTemplate = mapped,
            GroupPrefix = groupPrefix,
            HandlerForm = form,
        };

        // MapMethods with several verbs: one entry point per verb.
        var record = Detected.Record(EntryPointKinds.HttpMinimalApi, project, handler, confidence, AuthDeclared.From(authorisation.NoneDeclared));
        var identity = Detected.Identity(handler.Namespace, handler.Type, handler.Member, signature);
        var route = template ?? mapped ?? "(unresolved)";
        foreach (var verb in verbs)
        {
            yield return new DetectedEntryPoint(record with { Http = http with { Verb = verb } }, identity, route, verb);
        }
    }

    private static ArgumentSyntax? Named(SeparatedSyntaxList<ArgumentSyntax> arguments, string name) =>
        arguments.FirstOrDefault(a => a.NameColon?.Name.Identifier.Text == name);

    private static GroupResolution ResolveGroup(ExpressionSyntax receiver, SyntaxNode site, Confidence confidence, int depth)
    {
        var conventionCalls = new List<InvocationExpressionSyntax>();
        if (depth > 8)
        {
            return new GroupResolution([], "group chain too deep to follow", conventionCalls);
        }

        // Step over conventions: app.MapGroup("/a").RequireAuthorization().MapGet(...)
        while (receiver is InvocationExpressionSyntax call && SyntaxHelpers.InvokedName(call) is { } callName
               && Conventions.Contains(callName) && SyntaxHelpers.Receiver(call) is { } inner)
        {
            conventionCalls.Add(call);
            receiver = inner;
        }

        switch (receiver)
        {
            case InvocationExpressionSyntax mapGroup when SyntaxHelpers.InvokedName(mapGroup) == "MapGroup":
            {
                var outer = SyntaxHelpers.Receiver(mapGroup) is { } outerReceiver
                    ? ResolveGroup(outerReceiver, mapGroup, confidence, depth + 1)
                    : new GroupResolution([], null, []);
                outer.ConventionCalls.AddRange(conventionCalls);
                var prefixArgument = mapGroup.ArgumentList.Arguments.FirstOrDefault();
                var prefix = SyntaxHelpers.StringValue(prefixArgument?.Expression);
                if (prefix is null)
                {
                    return outer with { Unresolved = outer.Unresolved ?? SyntaxHelpers.Collapse(prefixArgument?.Expression.ToString() ?? "(no prefix)") };
                }

                outer.Prefixes.Add(prefix);
                return outer;
            }

            case IdentifierNameSyntax identifier:
            {
                var variable = identifier.Identifier.Text;
                var initializer = FindLocalInitializer(site, variable);
                if (initializer is not null)
                {
                    var resolved = ResolveGroup(initializer, initializer, confidence, depth + 1);
                    resolved.ConventionCalls.AddRange(conventionCalls);
                    return resolved;
                }

                var parameter = FindParameter(site, variable);
                if (parameter?.Type is { } parameterType && SyntaxHelpers.RightmostTypeName(parameterType) == "RouteGroupBuilder")
                {
                    return new GroupResolution([], $"group '{variable}' is supplied by the caller", conventionCalls);
                }

                if (parameter is null && !IsWellKnownRoot(variable))
                {
                    confidence.Reduce(0.9, $"receiver '{variable}' not traced to a declaration; no group prefix assumed");
                }

                return new GroupResolution([], null, conventionCalls);
            }

            default:
                return new GroupResolution([], null, conventionCalls);
        }
    }

    /// <summary>Names a WebApplication or IEndpointRouteBuilder is
    /// conventionally held in — a field or top-level local we did not find
    /// an initializer for, but which is not a group.</summary>
    private static bool IsWellKnownRoot(string name) =>
        name is "app" or "application" or "endpoints" or "routes" or "webApp" or "web";

    private static ExpressionSyntax? FindLocalInitializer(SyntaxNode site, string variable)
    {
        SyntaxNode? scope = site.Ancestors().FirstOrDefault(a => a is BaseMethodDeclarationSyntax or LocalFunctionStatementSyntax or AnonymousFunctionExpressionSyntax)
                            ?? site.Ancestors().OfType<CompilationUnitSyntax>().FirstOrDefault();
        return scope?.DescendantNodes()
            .OfType<VariableDeclaratorSyntax>()
            .Where(v => v.Identifier.Text == variable && v.Initializer is not null && v.SpanStart < site.SpanStart)
            .Select(v => v.Initializer!.Value)
            .LastOrDefault();
    }

    private static ParameterSyntax? FindParameter(SyntaxNode site, string variable) =>
        site.Ancestors()
            .SelectMany(a => a switch
            {
                BaseMethodDeclarationSyntax m => m.ParameterList.Parameters,
                LocalFunctionStatementSyntax l => l.ParameterList.Parameters,
                ParenthesizedLambdaExpressionSyntax p => p.ParameterList.Parameters,
                SimpleLambdaExpressionSyntax s => new SeparatedSyntaxList<ParameterSyntax>().Add(s.Parameter),
                _ => new SeparatedSyntaxList<ParameterSyntax>(),
            })
            .FirstOrDefault(p => p.Identifier.Text == variable);

    private static IReadOnlyList<string> MapMethodsVerbs(ArgumentSyntax argument, Confidence confidence)
    {
        var verbs = new List<string>();
        foreach (var node in argument.Expression.DescendantNodesAndSelf())
        {
            if (node is LiteralExpressionSyntax && SyntaxHelpers.StringValue((ExpressionSyntax)node) is { } literal)
            {
                verbs.Add(literal.ToUpperInvariant());
            }
            else if (node is MemberAccessExpressionSyntax { Expression: IdentifierNameSyntax { Identifier.Text: "HttpMethods" } } member)
            {
                verbs.Add(member.Name.Identifier.Text.ToUpperInvariant());
            }
        }

        if (verbs.Count == 0)
        {
            confidence.Reduce(0.5, $"MapMethods verbs are not literals: {SyntaxHelpers.Collapse(argument.Expression.ToString())}; recorded as ANY");
            return ["ANY"];
        }

        return verbs.Distinct().OrderBy(v => v, StringComparer.Ordinal).ToList();
    }

    private static (HandlerLocation Handler, string Form, BaseParameterListSyntax? Parameters, string? ReturnType, string Signature) Handler(
        ProjectSource project, ParsedFile file, InvocationExpressionSyntax invocation, ExpressionSyntax handlerExpression)
    {
        var (enclosingType, enclosingNamespace, enclosingMember) = SyntaxHelpers.EnclosingMember(invocation);

        if (handlerExpression is LambdaExpressionSyntax lambda)
        {
            var (start, end) = SyntaxHelpers.Lines(lambda,
                lambda.AttributeLists.Count > 0 ? lambda.AttributeLists.Last().Span.End : null);
            BaseParameterListSyntax? parameters = lambda is ParenthesizedLambdaExpressionSyntax p ? p.ParameterList : null;
            var returnType = lambda is ParenthesizedLambdaExpressionSyntax { ReturnType: { } rt } ? SyntaxHelpers.Collapse(rt.ToString()) : null;
            var handler = new HandlerLocation
            {
                Type = enclosingType,
                Namespace = enclosingNamespace,
                Member = enclosingMember,
                FilePath = file.RelativePath,
                LineStart = start,
                LineEnd = end,
            };
            // No line number in the identity: it would change whenever code
            // above moved. Route and verb tell a member's lambdas apart.
            return (handler, "lambda", parameters, returnType, "lambda");
        }

        // A method group: GetTodo, or Handlers.GetTodo.
        var (qualifier, methodName) = handlerExpression switch
        {
            MemberAccessExpressionSyntax m => (SyntaxHelpers.Collapse(m.Expression.ToString()), m.Name.Identifier.Text),
            IdentifierNameSyntax i => ((string?)null, i.Identifier.Text),
            _ => (null, SyntaxHelpers.Collapse(handlerExpression.ToString())),
        };
        var ownerName = qualifier is null ? enclosingType : qualifier.Split('.')[^1];
        var target = project.TypesByName[ownerName]
            .SelectMany(t => t.Syntax.Members.OfType<MethodDeclarationSyntax>().Select(m => (Type: t, Method: m)))
            .FirstOrDefault(x => x.Method.Identifier.Text == methodName);

        if (target.Method is not null)
        {
            var (start, end) = SyntaxHelpers.MemberLines(target.Method);
            return (new HandlerLocation
            {
                Type = target.Type.Name,
                Namespace = target.Type.Namespace,
                Member = methodName,
                FilePath = target.Type.File.RelativePath,
                LineStart = start,
                LineEnd = end,
            }, "method_group", target.Method.ParameterList, SyntaxHelpers.Collapse(target.Method.ReturnType.ToString()),
                SyntaxHelpers.ParameterSignature(target.Method.ParameterList));
        }

        var (siteStart, siteEnd) = SyntaxHelpers.Lines(invocation);
        return (new HandlerLocation
        {
            Type = ownerName,
            Namespace = qualifier is null ? enclosingNamespace : null,
            Member = methodName,
            FilePath = file.RelativePath,
            LineStart = siteStart,
            LineEnd = siteEnd,
        }, "method_group", null, null, "");
    }
}
