using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

/// <summary>What applies to one entry point, as written. None declared
/// when nothing requires authentication, or when <c>[AllowAnonymous]</c>
/// applies anywhere — in both ASP.NET Core and MVC 5 it wins over
/// <c>[Authorize]</c>.</summary>
public sealed class AuthorisationState
{
    private readonly List<string> _written = [];

    public bool AnyAuthorise { get; private set; }
    public bool AnyAnonymous { get; private set; }

    public string? Text => _written.Count == 0 ? null : string.Join(" + ", _written);

    public bool NoneDeclared => !AnyAuthorise || AnyAnonymous;

    public AuthorisationState AddAttributes(SyntaxList<AttributeListSyntax> lists)
    {
        foreach (var (attribute, name) in SyntaxHelpers.Attributes(lists))
        {
            if (name == "AllowAnonymous")
            {
                AnyAnonymous = true;
                Add(SyntaxHelpers.AsWritten(attribute));
            }
            else if (IsAuthorise(name))
            {
                AnyAuthorise = true;
                Add(SyntaxHelpers.AsWritten(attribute));
            }
        }

        return this;
    }

    /// <summary><c>RequireAuthorization(...)</c> and <c>AllowAnonymous()</c>
    /// chained on a minimal API or its group.</summary>
    public AuthorisationState AddConventionCall(InvocationExpressionSyntax call)
    {
        switch (SyntaxHelpers.InvokedName(call))
        {
            case "RequireAuthorization":
                AnyAuthorise = true;
                Add($".RequireAuthorization{SyntaxHelpers.Collapse(call.ArgumentList.ToString())}");
                break;
            case "AllowAnonymous":
                AnyAnonymous = true;
                Add(".AllowAnonymous()");
                break;
        }

        return this;
    }

    /// <summary>An anonymous-access convention written outside the class,
    /// such as <c>AllowAnonymousToPage</c>.</summary>
    public AuthorisationState AddAnonymous(string written)
    {
        AnyAnonymous = true;
        Add(written);
        return this;
    }

    public AuthorisationState AddGlobal(IEnumerable<string> global)
    {
        foreach (var text in global)
        {
            AnyAuthorise = true;
            Add($"{text} (global)");
        }

        return this;
    }

    public AuthorisationState Copy()
    {
        var copy = new AuthorisationState { AnyAuthorise = AnyAuthorise, AnyAnonymous = AnyAnonymous };
        copy._written.AddRange(_written);
        return copy;
    }

    /// <summary><c>[Authorize]</c>, a custom <c>[...Authorize]</c> (a
    /// subclass named for it, as written), and WCF's
    /// <c>[PrincipalPermission]</c>.</summary>
    public static bool IsAuthorise(string attributeName) =>
        attributeName == "Authorize"
        || attributeName.EndsWith("Authorize", StringComparison.Ordinal)
        || attributeName == "PrincipalPermission";

    private void Add(string text)
    {
        if (!_written.Contains(text))
        {
            _written.Add(text);
        }
    }
}

/// <summary>Project-wide routing and authorisation written in source —
/// read once per project.</summary>
public sealed record ProjectConventions(
    IReadOnlyList<string> ControllerAuthorisation,
    IReadOnlyList<string> EndpointAuthorisation,
    IReadOnlyList<string> ConventionalRoutes,
    IReadOnlyList<RazorPageConvention> RazorPageConventions)
{
    public IReadOnlyList<string> AllGlobalAuthorisation =>
        ControllerAuthorisation.Concat(EndpointAuthorisation).Distinct().OrderBy(s => s, StringComparer.Ordinal).ToList();

    public static ProjectConventions Read(ProjectSource project)
    {
        var controllers = new List<string>();
        var endpoints = new List<string>();
        var routes = new List<string>();
        var razor = new List<RazorPageConvention>();

        foreach (var file in project.Files)
        {
            foreach (var node in file.Root.DescendantNodes())
            {
                switch (node)
                {
                    case InvocationExpressionSyntax invocation:
                        var name = SyntaxHelpers.InvokedName(invocation);
                        if (name == "MapControllers" && SyntaxHelpers.ChainedCalls(invocation).Any(c => SyntaxHelpers.InvokedName(c) == "RequireAuthorization"))
                        {
                            controllers.Add($"MapControllers().RequireAuthorization() at {Where(file, node)}");
                        }
                        else if (name == "SetFallbackPolicy")
                        {
                            endpoints.Add($"fallback authorisation policy at {Where(file, node)}");
                        }
                        else if (ConventionalRoute(invocation) is { } route)
                        {
                            routes.Add($"{route} at {Where(file, node)}");
                        }
                        else if (RazorPageConvention.From(invocation, Where(file, node)) is { } convention)
                        {
                            razor.Add(convention);
                        }

                        break;

                    // options.Filters.Add(new AuthorizeFilter()) in ASP.NET
                    // Core; filters.Add(new AuthorizeAttribute()) in MVC 5.
                    case BaseObjectCreationExpressionSyntax creation
                        when creation is ObjectCreationExpressionSyntax { Type: var type }
                             && SyntaxHelpers.RightmostTypeName(type) is "AuthorizeFilter" or "AuthorizeAttribute":
                        controllers.Add($"global {SyntaxHelpers.RightmostTypeName(((ObjectCreationExpressionSyntax)creation).Type)} at {Where(file, node)}");
                        break;

                    case AssignmentExpressionSyntax { Left: MemberAccessExpressionSyntax { Name.Identifier.Text: "FallbackPolicy" } }:
                        endpoints.Add($"fallback authorisation policy at {Where(file, node)}");
                        break;
                }
            }
        }

        return new ProjectConventions(Sorted(controllers), Sorted(endpoints), Sorted(routes),
            razor.OrderBy(r => r.Written, StringComparer.Ordinal).ToList());
    }

    private static string? ConventionalRoute(InvocationExpressionSyntax invocation)
    {
        var name = SyntaxHelpers.InvokedName(invocation);
        var (templateIndex, templateNames) = name switch
        {
            "MapControllerRoute" => (1, new[] { "pattern" }),
            "MapAreaControllerRoute" => (2, new[] { "pattern" }),
            "MapRoute" => (1, new[] { "url", "template" }),
            "MapHttpRoute" => (1, new[] { "routeTemplate" }),
            "MapDefaultControllerRoute" => (-1, Array.Empty<string>()),
            _ => (-2, Array.Empty<string>()),
        };

        if (templateIndex == -2)
        {
            return null;
        }

        if (templateIndex == -1)
        {
            return "MapDefaultControllerRoute()";
        }

        var arguments = invocation.ArgumentList.Arguments;
        var template = arguments.FirstOrDefault(a => a.NameColon is { } nc && templateNames.Contains(nc.Name.Identifier.Text))
                       ?? (arguments.Count > templateIndex && arguments[templateIndex].NameColon is null ? arguments[templateIndex] : null);
        if (template is null)
        {
            return null;
        }

        var routeName = arguments.Count > 0 ? SyntaxHelpers.StringValue(arguments[0].Expression) : null;
        var written = SyntaxHelpers.StringValue(template.Expression) ?? SyntaxHelpers.Collapse(template.Expression.ToString());
        return $"{name} {routeName ?? "(unnamed)"}: {written}";
    }

    private static string Where(ParsedFile file, SyntaxNode node) =>
        $"{file.RelativePath}:{SyntaxHelpers.Lines(node).Start}";

    private static IReadOnlyList<string> Sorted(List<string> values) =>
        values.Distinct().OrderBy(v => v, StringComparer.Ordinal).ToList();
}

/// <summary>A Razor Pages authorisation convention —
/// <c>options.Conventions.AuthorizePage("/Basket/Checkout")</c> and its
/// folder, area and anonymous siblings — as written.</summary>
public sealed record RazorPageConvention(bool Authorise, bool Folder, string? Area, string Path, string Written)
{
    public static RazorPageConvention? From(InvocationExpressionSyntax invocation, string where)
    {
        var name = SyntaxHelpers.InvokedName(invocation);
        (bool Authorise, bool Folder, bool Area)? kind = name switch
        {
            "AuthorizePage" => (true, false, false),
            "AuthorizeFolder" => (true, true, false),
            "AuthorizeAreaPage" => (true, false, true),
            "AuthorizeAreaFolder" => (true, true, true),
            "AllowAnonymousToPage" => (false, false, false),
            "AllowAnonymousToFolder" => (false, true, false),
            "AllowAnonymousToAreaPage" => (false, false, true),
            "AllowAnonymousToAreaFolder" => (false, true, true),
            _ => null,
        };
        if (kind is not { } k)
        {
            return null;
        }

        var (authorise, folder, area) = k;

        var arguments = invocation.ArgumentList.Arguments;
        var areaName = area && arguments.Count > 0 ? SyntaxHelpers.StringValue(arguments[0].Expression) : null;
        var pathArgument = arguments.Count > (area ? 1 : 0) ? SyntaxHelpers.StringValue(arguments[area ? 1 : 0].Expression) : null;
        if (pathArgument is null || (area && areaName is null))
        {
            return null;
        }

        return new RazorPageConvention(authorise, folder, areaName, pathArgument,
            $"{name}({SyntaxHelpers.Collapse(invocation.ArgumentList.Arguments.ToString())}) at {where}");
    }

    /// <summary>Whether this convention covers the page at
    /// <paramref name="pagePath"/> (<c>/Basket/Checkout</c>) in
    /// <paramref name="area"/>.</summary>
    public bool Covers(string pagePath, string? area)
    {
        if (!string.Equals(Area, area, StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (!Folder)
        {
            return string.Equals(Path, pagePath, StringComparison.OrdinalIgnoreCase);
        }

        var folder = Path.TrimEnd('/');
        return folder.Length == 0 || pagePath.StartsWith(folder + "/", StringComparison.OrdinalIgnoreCase);
    }
}
