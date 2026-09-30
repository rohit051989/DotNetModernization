using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

/// <summary>
/// <c>http_controller_action</c> — Part B1: actions on <c>ControllerBase</c>,
/// <c>Controller</c> and <c>ApiController</c> subclasses, or classes marked
/// <c>[ApiController]</c>; routes composed per Part B2.
/// </summary>
public sealed class ControllerActionDetector : IEntryPointDetector
{
    private static readonly IReadOnlySet<string> ControllerBases =
        new HashSet<string>(StringComparer.Ordinal) { "ControllerBase", "Controller", "ApiController" };

    /// <summary>Ardalis.ApiEndpoints: EndpointBaseAsync.WithRequest&lt;T&gt;...
    /// and siblings, which derive ControllerBase inside the package — not
    /// visible syntactically.</summary>
    private static readonly IReadOnlySet<string> ArdalisBases =
        new HashSet<string>(StringComparer.Ordinal) { "EndpointBaseAsync", "EndpointBaseSync", "EndpointBase" };

    private static readonly IReadOnlyDictionary<string, string> VerbAttributes = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["HttpGet"] = "GET",
        ["HttpPost"] = "POST",
        ["HttpPut"] = "PUT",
        ["HttpDelete"] = "DELETE",
        ["HttpPatch"] = "PATCH",
        ["HttpHead"] = "HEAD",
        ["HttpOptions"] = "OPTIONS",
    };

    private static readonly string[] WebApiVerbPrefixes = ["Get", "Post", "Put", "Delete", "Patch", "Head", "Options"];

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        foreach (var type in project.Types)
        {
            if (type.Syntax is not ClassDeclarationSyntax || type.IsAbstract || type.IsStatic
                || SyntaxHelpers.HasAttribute(type.Syntax.AttributeLists, "NonController"))
            {
                continue;
            }

            var controller = Classify(project, type);
            if (controller is null)
            {
                continue;
            }

            foreach (var method in type.Syntax.Members.OfType<MethodDeclarationSyntax>())
            {
                if (!IsAction(method))
                {
                    continue;
                }

                foreach (var entry in EntriesFor(context, type, controller, method))
                {
                    yield return entry;
                }
            }
        }
    }

    private sealed record ControllerInfo(
        IReadOnlyList<DeclaredType> Chain,
        bool IsApiController,
        bool IsWebApi2,
        string? Area,
        IReadOnlyList<(string? Template, string? Unresolved)> Routes,
        Confidence Confidence);

    private static ControllerInfo? Classify(ProjectSource project, DeclaredType type)
    {
        var chain = project.SelfAndBaseClasses(type);
        var confidence = new Confidence();
        var hasApiControllerAttribute = chain.Any(t => SyntaxHelpers.HasAttribute(t.Syntax.AttributeLists, "ApiController"));

        var resolved = project.ResolveBase(type, ControllerBases);
        var ardalis = resolved is null ? ArdalisBase(type) : null;
        if (resolved is { Via: { } via })
        {
            confidence.Reduce(0.9, $"controller base {resolved.Value.Target} reached through in-project class {via}");
        }
        else if (ardalis is { } endpoint)
        {
            confidence.Reduce(0.9, $"{endpoint} (Ardalis.ApiEndpoints) taken to derive ControllerBase; not visible syntactically");
        }
        else if (resolved is null && !hasApiControllerAttribute)
        {
            return null;
        }

        // Nearest declaration wins, as with attribute inheritance.
        var routes = new List<(string?, string?)>();
        var declaring = chain.FirstOrDefault(t => RouteAttributes(t.Syntax.AttributeLists).Any());
        if (declaring is not null)
        {
            if (declaring != type)
            {
                confidence.Reduce(0.9, $"controller route inherited from in-project base {declaring.Name}");
            }

            routes.AddRange(RouteAttributes(declaring.Syntax.AttributeLists));
        }

        var area = chain
            .SelectMany(t => SyntaxHelpers.Attributes(t.Syntax.AttributeLists))
            .Where(a => a.Name == "Area")
            .Select(a => SyntaxHelpers.AttributeStringArgument(a.Attribute, "areaName").Value)
            .FirstOrDefault(v => v is not null);

        return new ControllerInfo(
            chain,
            hasApiControllerAttribute,
            IsWebApi2: resolved?.Target == "ApiController" && !hasApiControllerAttribute,
            area,
            routes,
            confidence);
    }

    /// <summary>Ardalis bases are written fluently —
    /// <c>EndpointBaseAsync.WithRequest&lt;TReq&gt;.WithActionResult&lt;TRes&gt;</c> —
    /// so the name that identifies them is the leftmost one, not the
    /// rightmost the base index keeps.</summary>
    private static string? ArdalisBase(DeclaredType type)
    {
        foreach (var baseType in type.Syntax.BaseList?.Types ?? default)
        {
            TypeSyntax current = baseType.Type;
            while (current is QualifiedNameSyntax qualified)
            {
                current = qualified.Left;
            }

            if (current is SimpleNameSyntax simple && ArdalisBases.Contains(simple.Identifier.Text))
            {
                return simple.Identifier.Text;
            }
        }

        return null;
    }

    /// <summary><c>[Route]</c> and MVC 5 / Web API 2 <c>[RoutePrefix]</c>
    /// templates; a non-literal template is carried as written.</summary>
    private static IEnumerable<(string? Template, string? Unresolved)> RouteAttributes(Microsoft.CodeAnalysis.SyntaxList<AttributeListSyntax> lists)
    {
        foreach (var (attribute, name) in SyntaxHelpers.Attributes(lists))
        {
            if (name is "Route" or "RoutePrefix")
            {
                var (_, value, expression) = SyntaxHelpers.AttributeStringArgument(attribute, "template", "prefix");
                yield return (value, value is null ? expression ?? "(no template)" : null);
            }
        }
    }

    private static bool IsAction(MethodDeclarationSyntax method) =>
        SyntaxHelpers.HasModifier(method, "public")
        && !SyntaxHelpers.HasModifier(method, "static")
        && !SyntaxHelpers.HasModifier(method, "abstract")
        && method.TypeParameterList is null
        && method.Identifier.Text != "Dispose"
        && !SyntaxHelpers.HasAttribute(method.AttributeLists, "NonAction");

    private static IEnumerable<DetectedEntryPoint> EntriesFor(
        DetectionContext context, DeclaredType type, ControllerInfo controller, MethodDeclarationSyntax method)
    {
        var project = context.Project;
        var methodName = method.Identifier.Text;
        var actionName = SyntaxHelpers.Attributes(method.AttributeLists)
            .Where(a => a.Name == "ActionName")
            .Select(a => SyntaxHelpers.AttributeStringArgument(a.Attribute, "name").Value)
            .FirstOrDefault(v => v is not null) ?? methodName;

        // Verb attributes with and without their own template; [Route] on the action.
        var verbRoutes = new List<(IReadOnlyList<string> Verbs, string? Template, string? Unresolved)>();
        var verbsWithoutTemplate = new List<string>();
        var actionRoutes = new List<(string? Template, string? Unresolved)>();
        foreach (var (attribute, name) in SyntaxHelpers.Attributes(method.AttributeLists))
        {
            if (VerbAttributes.TryGetValue(name, out var verb))
            {
                var (present, value, expression) = SyntaxHelpers.AttributeStringArgument(attribute, "template");
                if (present)
                {
                    verbRoutes.Add(([verb], value, value is null ? expression : null));
                }
                else
                {
                    verbsWithoutTemplate.Add(verb);
                }
            }
            else if (name == "AcceptVerbs")
            {
                verbsWithoutTemplate.AddRange(AcceptVerbs(attribute));
            }
            else if (name == "Route")
            {
                var (_, value, expression) = SyntaxHelpers.AttributeStringArgument(attribute, "template");
                actionRoutes.Add((value, value is null ? expression ?? "(no template)" : null));
            }
        }

        var confidence = controller.Confidence.Copy();
        IReadOnlyList<string> defaultVerbs;
        if (verbsWithoutTemplate.Count > 0)
        {
            defaultVerbs = verbsWithoutTemplate.Distinct().ToList();
        }
        else if (controller.IsWebApi2 && verbRoutes.Count == 0)
        {
            var prefix = WebApiVerbPrefixes.FirstOrDefault(p => methodName.StartsWith(p, StringComparison.Ordinal));
            if (prefix is not null)
            {
                confidence.Reduce(0.8, $"Web API 2: verb inferred from the '{prefix}' method-name prefix");
                defaultVerbs = [prefix.ToUpperInvariant()];
            }
            else
            {
                confidence.Reduce(0.7, "Web API 2: no verb attribute and no verb prefix, so POST by convention");
                defaultVerbs = ["POST"];
            }
        }
        else
        {
            if (controller.IsApiController && verbRoutes.Count == 0)
            {
                confidence.Reduce(0.7, "no verb attribute on an [ApiController] action: verb recorded as ANY");
            }

            defaultVerbs = ["ANY"];
        }

        // Each (action template, verbs) pair is its own route (Part B2:
        // multiple [Route] or verb attributes produce one entry each).
        var actionEntries = new List<(IReadOnlyList<string> Verbs, string? Template, string? Unresolved)>(verbRoutes);
        actionEntries.AddRange(actionRoutes.Select(r => (defaultVerbs, r.Template, r.Unresolved)));
        if (actionEntries.Count == 0)
        {
            actionEntries.Add((defaultVerbs, null, null));
        }

        var authorisation = new AuthorisationState();
        foreach (var level in controller.Chain.AsEnumerable().Reverse())
        {
            authorisation.AddAttributes(level.Syntax.AttributeLists);
        }

        authorisation.AddAttributes(method.AttributeLists);
        authorisation.AddGlobal(context.Conventions.ControllerAuthorisation.Concat(context.Conventions.EndpointAuthorisation));

        var (lineStart, lineEnd) = SyntaxHelpers.MemberLines(method);
        var handler = new HandlerLocation
        {
            Type = type.Name,
            Namespace = type.Namespace,
            Member = methodName,
            FilePath = type.File.RelativePath,
            LineStart = lineStart,
            LineEnd = lineEnd,
        };
        var identity = Detected.Identity(type.Namespace, type.Name, methodName, SyntaxHelpers.ParameterSignature(method.ParameterList));

        var controllerRoutes = controller.Routes.Count == 0
            ? new List<(string? Template, string? Unresolved)> { (null, null) }
            : controller.Routes.ToList();

        var seen = new HashSet<(string, string?)>();
        foreach (var (verbs, actionTemplate, actionUnresolved) in actionEntries)
        {
            var routesForAction = RouteTemplates.IsOverride(actionTemplate) ? controllerRoutes.Take(1) : controllerRoutes;
            foreach (var (controllerTemplate, controllerUnresolved) in routesForAction)
            {
                var entryConfidence = confidence.Copy();
                string? template;
                string routing;
                if (controllerUnresolved is not null || actionUnresolved is not null)
                {
                    entryConfidence.Reduce(0.5,
                        $"route template is not a literal: {controllerUnresolved ?? actionUnresolved}; composed route left null");
                    template = null;
                    routing = HttpRouting.Attribute;
                }
                else
                {
                    var combined = RouteTemplates.Combine(
                        RouteTemplates.IsOverride(actionTemplate) ? null : controllerTemplate, actionTemplate);
                    if (combined is null)
                    {
                        // No attribute routing anywhere: the route table is
                        // defined elsewhere. Record it, do not guess.
                        template = null;
                        routing = HttpRouting.Conventional;
                    }
                    else
                    {
                        template = RouteTemplates.ResolveTokens(combined, type.Name, actionName, controller.Area, entryConfidence);
                        routing = HttpRouting.Attribute;
                    }
                }

                foreach (var verb in verbs)
                {
                    if (!seen.Add((verb, template)))
                    {
                        continue;
                    }

                    var http = new HttpDetail
                    {
                        Verb = verb,
                        RouteTemplate = template,
                        Routing = routing,
                        Parameters = HttpParameters.Build(method.ParameterList, template,
                            controller.IsApiController ? BindingInference.ApiController : BindingInference.None),
                        ReturnType = SyntaxHelpers.Collapse(method.ReturnType.ToString()),
                        Authorisation = authorisation.Text,
                        Controller = RouteTemplates.ControllerTokenValue(type.Name),
                        Action = actionName,
                    };

                    yield return new DetectedEntryPoint(
                        Detected.Record(EntryPointKinds.HttpControllerAction, project, handler, entryConfidence, AuthDeclared.From(authorisation)) with
                        {
                            Http = http,
                        },
                        identity,
                        template ?? (routing == HttpRouting.Conventional ? "(conventional)" : "(unresolved)"),
                        verb);
                }
            }
        }
    }

    /// <summary><c>[AcceptVerbs("GET", "POST")]</c> (ASP.NET Core) and
    /// <c>[AcceptVerbs(HttpVerbs.Get | HttpVerbs.Post)]</c> (MVC 5).</summary>
    private static IEnumerable<string> AcceptVerbs(AttributeSyntax attribute)
    {
        foreach (var argument in attribute.ArgumentList?.Arguments ?? default)
        {
            if (SyntaxHelpers.StringValue(argument.Expression) is { } literal)
            {
                yield return literal.ToUpperInvariant();
                continue;
            }

            foreach (var member in argument.Expression.DescendantNodesAndSelf().OfType<MemberAccessExpressionSyntax>())
            {
                if (member.Expression is IdentifierNameSyntax { Identifier.Text: "HttpVerbs" })
                {
                    yield return member.Name.Identifier.Text.ToUpperInvariant();
                }
            }
        }
    }
}
