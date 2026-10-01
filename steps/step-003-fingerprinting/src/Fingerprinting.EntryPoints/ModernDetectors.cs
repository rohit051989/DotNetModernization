using Fingerprinting.Analysis;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

// 2.0.0 kinds beyond the classic four. Rules from the find-dotnet-entry-points
// pattern catalog (sections 1, 4 and 5), reimplemented on syntax trees.

/// <summary><c>blazor_component</c>: a .razor component made routable by one
/// or more <c>@page "/route"</c> directives — one entry per route.</summary>
public sealed partial class BlazorComponentDetector : IEntryPointDetector
{
    [GeneratedRegex(@"^\s*@page\s+""(?<route>[^""]*)""", RegexOptions.Multiline)]
    private static partial Regex PageRoute();

    [GeneratedRegex(@"^\s*@attribute\s+\[(?<attribute>[^\]]+)\]", RegexOptions.Multiline)]
    private static partial Regex AttributeDirective();

    /// <summary>The <c>@page</c> routes a .razor file declares.</summary>
    public static IReadOnlyList<(string Route, int Line)> Routes(string text) =>
        PageRoute().Matches(text)
            .Select(m => (m.Groups["route"].Value, text[..(m.Index + m.Value.IndexOf("@page", StringComparison.Ordinal))].Count(c => c == '\n') + 1))
            .ToList();

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        foreach (var (file, text) in project.AuxiliaryFiles.Where(a => a.RelativePath.EndsWith(".razor", StringComparison.OrdinalIgnoreCase)))
        {
            var component = Path.GetFileNameWithoutExtension(file);

            // @attribute [Authorize] in the component, or on its code-behind.
            var attributes = AttributeDirective().Matches(text).Select(m => m.Groups["attribute"].Value.Trim()).ToList();
            var codeBehind = project.Types.FirstOrDefault(t => t.File.RelativePath.Equals(file + ".cs", StringComparison.OrdinalIgnoreCase));
            var authorisation = new AuthorisationState();
            if (codeBehind is not null)
            {
                authorisation.AddAttributes(codeBehind.Syntax.AttributeLists);
            }

            var written = new List<string>();
            foreach (var attribute in attributes)
            {
                var name = attribute.Split('(')[0].Trim().Split('.')[^1];
                name = name.EndsWith("Attribute", StringComparison.Ordinal) ? name[..^"Attribute".Length] : name;
                if (name == "AllowAnonymous")
                {
                    authorisation.AddAnonymous($"@attribute [{attribute}]");
                }
                else if (AuthorisationState.IsAuthorise(name))
                {
                    authorisation.AddGlobal([$"@attribute [{attribute}]"]);
                    written.Add(attribute);
                }
            }

            foreach (var (route, line) in Routes(text))
            {
                var handler = new HandlerLocation
                {
                    Type = component,
                    Namespace = codeBehind?.Namespace,
                    Member = null,
                    FilePath = file,
                    LineStart = line,
                    LineEnd = line,
                };
                yield return new DetectedEntryPoint(
                    Detected.Record(EntryPointKinds.BlazorComponent, project, handler, new Confidence(), AuthDeclared.From(authorisation.NoneDeclared)) with
                    {
                        Blazor = new BlazorDetail
                        {
                            Route = route,
                            ComponentFile = file,
                            Authorisation = authorisation.Text?.Replace(" (global)", ""),
                        },
                    },
                    Detected.Identity(null, component, null, file),
                    route,
                    null);
            }
        }
    }
}

/// <summary>
/// <c>azure_function</c>: methods marked <c>[FunctionName("X")]</c>
/// (in-process) or <c>[Function("X")]</c> (isolated worker). The trigger
/// attribute on the triggered parameter decides what kind of entry point it
/// is, and is always recorded. An HTTP trigger's authorisation level is its
/// declared authentication; other triggers are not called by clients.
/// </summary>
public sealed class AzureFunctionDetector : IEntryPointDetector
{
    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        var isolatedPackage = project.PackageNames.Any(p => p.StartsWith("Microsoft.Azure.Functions.Worker", StringComparison.OrdinalIgnoreCase));

        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax))
        {
            foreach (var method in type.Syntax.Members.OfType<MethodDeclarationSyntax>())
            {
                var marker = SyntaxHelpers.Attributes(method.AttributeLists).FirstOrDefault(a => a.Name is "FunctionName" or "Function");
                if (marker.Attribute is null)
                {
                    continue;
                }

                var functionName = SyntaxHelpers.AttributeStringArgument(marker.Attribute, "name").Value;
                if (functionName is null)
                {
                    continue;
                }

                var model = marker.Name == "FunctionName" ? "in_process" : "isolated";
                var trigger = method.ParameterList.Parameters
                    .SelectMany(p => SyntaxHelpers.Attributes(p.AttributeLists))
                    .FirstOrDefault(a => a.Name.EndsWith("Trigger", StringComparison.Ordinal));

                var confidence = new Confidence();
                if (model == "isolated" && trigger.Attribute is null && !isolatedPackage)
                {
                    // [Function] is a common attribute name; without a
                    // trigger or the worker package it may be something else.
                    confidence.Reduce(0.6, "[Function] with no trigger parameter and no Microsoft.Azure.Functions.Worker package");
                }
                else if (trigger.Attribute is null)
                {
                    confidence.Reduce(0.8, "no *Trigger attribute on any parameter; trigger unknown");
                }

                string? level = null, route = null;
                var methods = new List<string>();
                string? authDeclared = null;
                if (trigger.Name == "HttpTrigger")
                {
                    foreach (var argument in trigger.Attribute!.ArgumentList?.Arguments ?? default)
                    {
                        if (argument.Expression is MemberAccessExpressionSyntax { Expression: var owner } member
                            && owner.ToString().EndsWith("AuthorizationLevel", StringComparison.Ordinal))
                        {
                            level = member.Name.Identifier.Text;
                        }
                        else if (argument.NameEquals?.Name.Identifier.Text == "Route")
                        {
                            route = SyntaxHelpers.StringValue(argument.Expression) ?? SyntaxHelpers.Collapse(argument.Expression.ToString());
                        }
                        else if (SyntaxHelpers.StringValue(argument.Expression) is { } verb)
                        {
                            methods.Add(verb.ToUpperInvariant());
                        }
                    }

                    // An omitted level is the in-process default, Function —
                    // a function key is declared authentication.
                    if (level is null)
                    {
                        confidence.Reduce(0.9, "HttpTrigger authorization level not written; the default (Function) is assumed");
                    }

                    authDeclared = (level ?? "Function") == "Anonymous" ? AuthDeclared.NoneDeclared : AuthDeclared.Declared;
                }

                var (start, end) = SyntaxHelpers.MemberLines(method);
                var handler = new HandlerLocation
                {
                    Type = type.Name,
                    Namespace = type.Namespace,
                    Member = method.Identifier.Text,
                    FilePath = type.File.RelativePath,
                    LineStart = start,
                    LineEnd = end,
                };
                yield return new DetectedEntryPoint(
                    Detected.Record(EntryPointKinds.AzureFunction, project, handler, confidence, authDeclared) with
                    {
                        Function = new FunctionDetail
                        {
                            FunctionName = functionName,
                            Model = model,
                            Trigger = trigger.Name,
                            TriggerAttribute = trigger.Attribute is null ? null : SyntaxHelpers.AsWritten(trigger.Attribute),
                            AuthorizationLevel = level,
                            Methods = methods,
                            Route = route,
                        },
                    },
                    Detected.Identity(type.Namespace, type.Name, method.Identifier.Text, SyntaxHelpers.ParameterSignature(method.ParameterList)),
                    functionName,
                    null);
            }
        }
    }
}

/// <summary>
/// <c>desktop_app</c>: WinForms and WPF application entry. WinForms: a
/// <c>[STAThread] Main</c> in a file importing System.Windows.Forms or
/// calling <c>Application.Run</c>, with the form it opens. WPF: the
/// <c>System.Windows.Application</c> subclass App.xaml defines, with its
/// <c>StartupUri</c>. Recorded instead of console_main.
/// </summary>
public sealed partial class DesktopAppDetector : IEntryPointDetector
{
    [GeneratedRegex(@"x:Class\s*=\s*""(?<class>[^""]+)""")]
    private static partial Regex XamlClass();

    [GeneratedRegex(@"StartupUri\s*=\s*""(?<uri>[^""]+)""")]
    private static partial Regex StartupUri();

    [GeneratedRegex(@"^\s*(<\?xml[^>]*\?>\s*)?<Application\b", RegexOptions.Singleline)]
    private static partial Regex ApplicationRoot();

    public static bool IsApplicationXaml(string text) => ApplicationRoot().IsMatch(text.TrimStart('﻿'));

    private static readonly IReadOnlySet<string> WpfApplication = new HashSet<string>(StringComparer.Ordinal) { "Application" };

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;

        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax or StructDeclarationSyntax))
        {
            foreach (var main in type.Syntax.Members.OfType<MethodDeclarationSyntax>()
                         .Where(m => m.Identifier.Text == "Main" && SyntaxHelpers.HasModifier(m, "static")))
            {
                var run = main.DescendantNodes().OfType<InvocationExpressionSyntax>()
                    .FirstOrDefault(i => RoslynNameHelpers.IsStaticCallOn(i, "Application", "Run"));
                var winForms = WindowsServiceDetector.Imports(type.File, "System.Windows.Forms");
                if (!winForms && run is null)
                {
                    continue;
                }

                var confidence = new Confidence();
                if (!winForms)
                {
                    confidence.Reduce(0.8, "Application.Run with no using System.Windows.Forms; taken as WinForms");
                }

                var (start, end) = SyntaxHelpers.MemberLines(main);
                var handler = new HandlerLocation
                {
                    Type = type.Name,
                    Namespace = type.Namespace,
                    Member = "Main",
                    FilePath = type.File.RelativePath,
                    LineStart = start,
                    LineEnd = end,
                };
                yield return new DetectedEntryPoint(
                    Detected.Record(EntryPointKinds.DesktopApp, project, handler, confidence, authDeclared: null) with
                    {
                        Desktop = new DesktopDetail
                        {
                            Framework = "winforms",
                            MainWindow = MainForm(main, run),
                            StaThread = SyntaxHelpers.HasAttribute(main.AttributeLists, "STAThread"),
                        },
                    },
                    Detected.Identity(type.Namespace, type.Name, "Main", SyntaxHelpers.ParameterSignature(main.ParameterList)),
                    null,
                    null);
            }
        }

        foreach (var (xamlFile, text) in project.AuxiliaryFiles.Where(a => a.RelativePath.EndsWith(".xaml", StringComparison.OrdinalIgnoreCase)))
        {
            var className = XamlClass().Match(text) is { Success: true } m ? m.Groups["class"].Value.Split('.')[^1] : null;
            var app = className is null ? null : project.TypesByName[className].FirstOrDefault(t => t.Syntax is ClassDeclarationSyntax);
            var confidence = new Confidence();
            if (app is not null && project.ResolveBase(app, WpfApplication) is null)
            {
                confidence.Reduce(0.8, $"{className} does not derive Application as written (base may be in the generated partial)");
            }

            var onStartup = app?.Syntax.Members.OfType<MethodDeclarationSyntax>().FirstOrDefault(x => x.Identifier.Text == "OnStartup");
            var (start, end) = onStartup is not null ? SyntaxHelpers.MemberLines(onStartup) : app is not null ? SyntaxHelpers.MemberLines(app.Syntax) : (1, 1);
            var handler = new HandlerLocation
            {
                Type = className ?? Path.GetFileNameWithoutExtension(xamlFile),
                Namespace = app?.Namespace,
                Member = onStartup?.Identifier.Text,
                FilePath = app?.File.RelativePath ?? xamlFile,
                LineStart = start,
                LineEnd = end,
            };
            yield return new DetectedEntryPoint(
                Detected.Record(EntryPointKinds.DesktopApp, project, handler, confidence, authDeclared: null) with
                {
                    Desktop = new DesktopDetail
                    {
                        Framework = "wpf",
                        MainWindow = StartupUri().Match(text) is { Success: true } s ? s.Groups["uri"].Value : null,
                        StaThread = true,
                    },
                },
                Detected.Identity(handler.Namespace, handler.Type, handler.Member, xamlFile),
                null,
                null);
        }
    }

    /// <summary>The form <c>Application.Run(new X())</c> opens, else the
    /// type of a local whose <c>ShowDialog()</c> or <c>Show()</c> is called.</summary>
    private static string? MainForm(MethodDeclarationSyntax main, InvocationExpressionSyntax? run)
    {
        if (run?.ArgumentList.Arguments.FirstOrDefault()?.Expression is ObjectCreationExpressionSyntax created)
        {
            return SyntaxHelpers.RightmostTypeName(created.Type);
        }

        var shown = main.DescendantNodes().OfType<InvocationExpressionSyntax>()
            .Select(i => i.Expression)
            .OfType<MemberAccessExpressionSyntax>()
            .Where(m => m.Name.Identifier.Text is "ShowDialog" or "Show" && m.Expression is IdentifierNameSyntax)
            .Select(m => ((IdentifierNameSyntax)m.Expression).Identifier.Text)
            .FirstOrDefault();
        if (shown is null)
        {
            return null;
        }

        var initializer = main.DescendantNodes().OfType<VariableDeclaratorSyntax>()
            .FirstOrDefault(v => v.Identifier.Text == shown)?.Initializer?.Value;
        return initializer is ObjectCreationExpressionSyntax creation ? SyntaxHelpers.RightmostTypeName(creation.Type) : null;
    }
}
