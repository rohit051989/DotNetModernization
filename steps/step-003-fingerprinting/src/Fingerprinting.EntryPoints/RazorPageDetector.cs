using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

/// <summary>
/// <c>razor_page</c>: ASP.NET Core Razor Pages. A .cshtml with an
/// <c>@page</c> directive, its <c>PageModel</c> code-behind, and one entry
/// point per handler — <c>OnGet</c>, <c>OnPostAsync</c>, <c>OnPostDeleteAsync</c>
/// (a named handler, <c>Delete</c>). A page with no GET handler still
/// renders on GET, so it gets one.
///
/// The route follows the default convention: the path under
/// <c>Pages/</c> (or <c>Areas/{area}/Pages/</c>) without the extension, an
/// <c>Index</c> page answering at its folder; an <c>@page "template"</c>
/// appends, and one starting with <c>/</c> replaces.
/// </summary>
public sealed partial class RazorPageDetector : IEntryPointDetector
{
    private static readonly IReadOnlySet<string> PageModelBase = new HashSet<string>(StringComparer.Ordinal) { "PageModel" };

    [GeneratedRegex(@"^\s*@page(?:[ \t]+""(?<template>[^""]*)"")?[ \t]*$", RegexOptions.Multiline)]
    private static partial Regex PageLine();

    [GeneratedRegex(@"^\s*@model[ \t]+(?<model>[\w.]+)", RegexOptions.Multiline)]
    private static partial Regex ModelLine();

    [GeneratedRegex(@"^On(?<verb>Get|Post|Put|Delete|Patch)(?<handler>\w*?)(?:Async)?$")]
    private static partial Regex HandlerName();

    [GeneratedRegex(@"^Areas/(?<area>[^/]+)/Pages/(?<path>.+)\.cshtml$", RegexOptions.IgnoreCase)]
    private static partial Regex AreaPage();

    /// <summary>The <c>@page</c> directive's template: "" for a bare
    /// <c>@page</c>, null when the file is not a page. The directive must
    /// be the first directive, as Razor requires.</summary>
    public static string? PageDirective(string text)
    {
        // TrimEnd: a CRLF file leaves '\r' on the line, which '$' will not
        // match. The BOM is written as an escape so it stays visible.
        var firstLine = text.TrimStart('﻿', ' ', '\t', '\r', '\n').Split('\n', 2)[0].TrimEnd('\r');
        var match = PageLine().Match(firstLine);
        return match.Success ? match.Groups["template"].Value : null;
    }

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        foreach (var (pageFile, text) in project.AuxiliaryFiles.Where(a => a.RelativePath.EndsWith(".cshtml", StringComparison.OrdinalIgnoreCase)))
        {
            var template = PageDirective(text);
            if (template is null)
            {
                continue;
            }

            var confidence = new Confidence();
            var (area, pagePath) = PagePath(project.PathWithinProject(pageFile), confidence);
            var route = Route(area, pagePath, template);
            var model = PageModelFor(project, pageFile, text);

            var authorisation = new AuthorisationState();
            if (model is not null)
            {
                foreach (var level in project.SelfAndBaseClasses(model).AsEnumerable().Reverse())
                {
                    authorisation.AddAttributes(level.Syntax.AttributeLists);
                }
            }

            foreach (var convention in context.Conventions.RazorPageConventions.Where(c => c.Covers(pagePath, area)))
            {
                if (convention.Authorise)
                {
                    authorisation.AddGlobal([convention.Written]);
                }
                else
                {
                    authorisation.AddAnonymous(convention.Written);
                }
            }

            // Global MVC filters and a fallback policy reach pages too;
            // MapControllers().RequireAuthorization() does not.
            authorisation.AddGlobal(context.Conventions.ControllerAuthorisation.Where(c => c.StartsWith("global ", StringComparison.Ordinal)));
            authorisation.AddGlobal(context.Conventions.EndpointAuthorisation);

            var handlers = model?.Syntax.Members.OfType<MethodDeclarationSyntax>()
                .Where(m => SyntaxHelpers.HasModifier(m, "public") && !SyntaxHelpers.HasModifier(m, "static"))
                .Select(m => (Method: m, Match: HandlerName().Match(m.Identifier.Text)))
                .Where(x => x.Match.Success)
                .ToList() ?? [];

            foreach (var (method, match) in handlers)
            {
                var verb = match.Groups["verb"].Value.ToUpperInvariant();
                var handlerName = match.Groups["handler"].Value;
                yield return Entry(project, model!, method, pageFile, route, verb, handlerName.Length == 0 ? null : handlerName,
                    authorisation, confidence);
            }

            if (!handlers.Any(h => h.Match.Groups["verb"].Value == "Get"))
            {
                // Renders on GET with no handler at all.
                yield return Entry(project, model, null, pageFile, route, "GET", null, authorisation, confidence);
            }
        }
    }

    private static DetectedEntryPoint Entry(
        ProjectSource project, DeclaredType? model, MethodDeclarationSyntax? method, string pageFile, string route,
        string verb, string? handlerName, AuthorisationState authorisation, Confidence confidence)
    {
        var (start, end) = method is not null ? SyntaxHelpers.MemberLines(method)
            : model is not null ? SyntaxHelpers.MemberLines(model.Syntax)
            : (1, 1);
        var typeName = model?.Name ?? Path.GetFileNameWithoutExtension(pageFile);
        var handler = new HandlerLocation
        {
            Type = typeName,
            Namespace = model?.Namespace,
            Member = method?.Identifier.Text,
            FilePath = method is not null || model is not null ? model!.File.RelativePath : pageFile,
            LineStart = start,
            LineEnd = end,
        };
        var http = new HttpDetail
        {
            Verb = verb,
            RouteTemplate = route,
            Routing = HttpRouting.RazorPage,
            Parameters = HttpParameters.Build(method?.ParameterList, route, BindingInference.None),
            ReturnType = method is null ? null : SyntaxHelpers.Collapse(method.ReturnType.ToString()),
            Authorisation = authorisation.Text,
            PageFile = pageFile,
            PageHandler = handlerName,
        };
        return new DetectedEntryPoint(
            Detected.Record(EntryPointKinds.RazorPage, project, handler, confidence, AuthDeclared.From(authorisation)) with { Http = http },
            Detected.Identity(handler.Namespace, typeName, handler.Member ?? "(page)",
                method is null ? pageFile : SyntaxHelpers.ParameterSignature(method.ParameterList)),
            route,
            handlerName is null ? verb : $"{verb}?handler={handlerName}");
    }

    /// <summary>Area and page path (<c>/Basket/Checkout</c>, as
    /// <c>AuthorizePage</c> names pages) from the file's path within the
    /// project.</summary>
    private static (string? Area, string PagePath) PagePath(string pathWithinProject, Confidence confidence)
    {
        var areaMatch = AreaPage().Match(pathWithinProject);
        if (areaMatch.Success)
        {
            return (areaMatch.Groups["area"].Value, "/" + areaMatch.Groups["path"].Value);
        }

        if (pathWithinProject.StartsWith("Pages/", StringComparison.OrdinalIgnoreCase))
        {
            return (null, "/" + pathWithinProject["Pages/".Length..^".cshtml".Length]);
        }

        confidence.Reduce(0.7, $"page outside Pages/ ({pathWithinProject}): a custom RootDirectory is assumed to be its folder");
        var slash = pathWithinProject.IndexOf('/');
        return (null, "/" + (slash < 0 ? pathWithinProject : pathWithinProject[(slash + 1)..])[..^".cshtml".Length]);
    }

    private static string Route(string? area, string pagePath, string template)
    {
        if (template.StartsWith('/') || template.StartsWith("~/", StringComparison.Ordinal))
        {
            return RouteTemplates.JoinSegments([template.TrimStart('~')]);
        }

        var segments = pagePath.Trim('/').Split('/').ToList();
        if (segments[^1].Equals("Index", StringComparison.OrdinalIgnoreCase))
        {
            segments.RemoveAt(segments.Count - 1);
        }

        if (area is not null)
        {
            segments.Insert(0, area);
        }

        segments.Add(template);
        return RouteTemplates.JoinSegments(segments);
    }

    /// <summary>The code-behind (<c>Checkout.cshtml.cs</c>), else the class
    /// the <c>@model</c> directive names — a <c>PageModel</c>, directly or
    /// through an in-project base.</summary>
    private static DeclaredType? PageModelFor(ProjectSource project, string pageFile, string text)
    {
        var codeBehind = project.Types.FirstOrDefault(t =>
            t.File.RelativePath.Equals(pageFile + ".cs", StringComparison.OrdinalIgnoreCase)
            && project.ResolveBase(t, PageModelBase) is not null);
        if (codeBehind is not null)
        {
            return codeBehind;
        }

        var modelName = ModelLine().Match(text) is { Success: true } m ? m.Groups["model"].Value.Split('.')[^1] : null;
        return modelName is null
            ? null
            : project.TypesByName[modelName].FirstOrDefault(t => project.ResolveBase(t, PageModelBase) is not null);
    }
}
