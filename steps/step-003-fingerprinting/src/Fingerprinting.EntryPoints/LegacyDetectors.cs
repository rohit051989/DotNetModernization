using Fingerprinting.Analysis;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

// The classic .NET Framework entry points — 2.0.0. Detection rules from the
// find-dotnet-entry-points pattern catalog (references/dotnet-entry-point-
// patterns.md, sections 2, 4 and 6), reimplemented on syntax trees: markers
// are matched on declarations, not on text.

/// <summary><c>windows_service</c>: classic <c>ServiceBase</c> subclasses.
/// One entry per service, handled at <c>OnStart</c>.</summary>
public sealed class WindowsServiceDetector : IEntryPointDetector
{
    private static readonly IReadOnlySet<string> ServiceBaseName = new HashSet<string>(StringComparer.Ordinal) { "ServiceBase" };

    private static readonly string[] Hooks =
        ["OnStart", "OnStop", "OnPause", "OnContinue", "OnShutdown", "OnCustomCommand", "OnSessionChange", "OnPowerEvent"];

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax && !t.IsAbstract))
        {
            if (project.ResolveBase(type, ServiceBaseName) is not { } resolved)
            {
                continue;
            }

            var confidence = new Confidence();
            if (resolved.Via is not null)
            {
                confidence.Reduce(0.9, $"ServiceBase reached through in-project base {resolved.Via}");
            }

            // A simple-name collision guard: the base should be System.ServiceProcess's.
            if (!Imports(type.File, "System.ServiceProcess")
                && type.Syntax.BaseList?.Types.Any(b => b.Type.ToString().Contains("ServiceProcess", StringComparison.Ordinal)) != true)
            {
                confidence.Reduce(0.7, "ServiceBase not confirmed as System.ServiceProcess.ServiceBase (no using or qualified name)");
            }

            var methods = type.Syntax.Members.OfType<MethodDeclarationSyntax>().ToList();
            var hooks = Hooks.Where(h => methods.Any(m => m.Identifier.Text == h && SyntaxHelpers.HasModifier(m, "override"))).ToList();
            var onStart = methods.FirstOrDefault(m => m.Identifier.Text == "OnStart");
            var serviceName = type.Syntax.DescendantNodes().OfType<AssignmentExpressionSyntax>()
                .Where(a => a.Left.ToString().Replace("this.", "") == "ServiceName")
                .Select(a => SyntaxHelpers.StringValue(a.Right))
                .FirstOrDefault(v => v is not null);
            var runAt = project.Files
                .SelectMany(f => f.Root.DescendantNodes().OfType<InvocationExpressionSyntax>().Select(i => (File: f, Call: i)))
                .Where(x => RoslynNameHelpers.IsStaticCallOn(x.Call, "ServiceBase", "Run")
                            && x.Call.ArgumentList.DescendantNodes().OfType<ObjectCreationExpressionSyntax>()
                                .Any(c => SyntaxHelpers.RightmostTypeName(c.Type) == type.Name))
                .Select(x => $"{x.File.RelativePath}:{SyntaxHelpers.Lines(x.Call).Start}")
                .FirstOrDefault();

            var (start, end) = onStart is null ? SyntaxHelpers.MemberLines(type.Syntax) : SyntaxHelpers.MemberLines(onStart);
            var handler = new HandlerLocation
            {
                Type = type.Name,
                Namespace = type.Namespace,
                Member = onStart?.Identifier.Text,
                FilePath = type.File.RelativePath,
                LineStart = start,
                LineEnd = end,
            };
            yield return new DetectedEntryPoint(
                Detected.Record(EntryPointKinds.WindowsService, project, handler, confidence, authDeclared: null) with
                {
                    WindowsService = new WindowsServiceDetail { ServiceClass = type.Name, ServiceName = serviceName, Hooks = hooks, RunAt = runAt },
                },
                Detected.Identity(type.Namespace, type.Name, handler.Member),
                null,
                null);
        }
    }

    internal static bool Imports(ParsedFile file, string ns) =>
        file.Root.DescendantNodes().OfType<UsingDirectiveSyntax>().Any(u => u.Name?.ToString() == ns);
}

/// <summary>
/// <c>http_handler</c>: <c>IHttpHandler</c> / <c>IHttpAsyncHandler</c> /
/// <c>HttpTaskAsyncHandler</c> handlers and <c>IHttpModule</c> modules in
/// source, .ashx files (self-describing handlers), and the handler and
/// module registrations in web.config — <c>&lt;httpHandlers&gt;</c> and
/// <c>&lt;httpModules&gt;</c> (classic pipeline), <c>&lt;handlers&gt;</c> and
/// <c>&lt;modules&gt;</c> (integrated). A registration of a type with no
/// source here — a framework or package module — is recorded too, flagged
/// <c>inRepository: false</c>: it still sees the traffic.
/// </summary>
public sealed partial class HttpHandlerDetector : IEntryPointDetector
{
    private static readonly IReadOnlySet<string> HandlerBases =
        new HashSet<string>(StringComparer.Ordinal) { "IHttpHandler", "IHttpAsyncHandler", "HttpTaskAsyncHandler" };

    private static readonly IReadOnlySet<string> ModuleBases = new HashSet<string>(StringComparer.Ordinal) { "IHttpModule" };

    [GeneratedRegex(@"<%@\s*WebHandler\b[^%]*\bClass\s*=\s*""(?<class>[^""]+)""", RegexOptions.IgnoreCase)]
    private static partial Regex WebHandlerDirective();

    private sealed record Registration(string Role, string TypeFullName, string? Path, string? Verb, string Where, string Section);

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        var registrations = Registrations(context.ProjectConfigs, project.ProjectDirectory).ToList();
        var ashx = project.AuxiliaryFiles
            .Where(a => a.RelativePath.EndsWith(".ashx", StringComparison.OrdinalIgnoreCase))
            .Select(a => (Path: "/" + project.PathWithinProject(a.RelativePath),
                          Class: WebHandlerDirective().Match(a.Text) is { Success: true } m ? m.Groups["class"].Value.Split('.')[^1] : null))
            .ToList();
        var matched = new HashSet<Registration>();

        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax && !t.IsAbstract))
        {
            var role = project.ResolveBase(type, HandlerBases) is not null ? "handler"
                : project.ResolveBase(type, ModuleBases) is not null ? "module"
                : null;
            if (role is null)
            {
                continue;
            }

            var registration = registrations.FirstOrDefault(r => r.Role == role && SimpleName(r.TypeFullName) == type.Name);
            if (registration is not null)
            {
                matched.UnionWith(registrations.Where(r => r.Role == role && SimpleName(r.TypeFullName) == type.Name));
            }

            var path = role == "handler" ? ashx.FirstOrDefault(a => a.Class == type.Name).Path ?? registration?.Path : null;
            var member = type.Syntax.Members.OfType<MethodDeclarationSyntax>().FirstOrDefault(m =>
                m.Identifier.Text is "ProcessRequest" or "ProcessRequestAsync" or "BeginProcessRequest" or "Init");
            var (start, end) = member is null ? SyntaxHelpers.MemberLines(type.Syntax) : SyntaxHelpers.MemberLines(member);
            var handler = new HandlerLocation
            {
                Type = type.Name,
                Namespace = type.Namespace,
                Member = member?.Identifier.Text,
                FilePath = type.File.RelativePath,
                LineStart = start,
                LineEnd = end,
            };
            yield return Entry(context, handler, role, type.Namespace is null ? type.Name : $"{type.Namespace}.{type.Name}",
                path, registration, inRepository: true, new AuthorisationState().AddAttributes(type.Syntax.AttributeLists));
        }

        // Registered types with no source here: one entry per (role, type),
        // however many sections register it.
        foreach (var group in registrations.Except(matched).GroupBy(r => (r.Role, r.TypeFullName)))
        {
            var first = group.First();
            var (file, line) = SplitWhere(first.Where);
            var handler = new HandlerLocation
            {
                Type = SimpleName(first.TypeFullName),
                Namespace = first.TypeFullName.Contains('.') ? first.TypeFullName[..first.TypeFullName.LastIndexOf('.')] : null,
                Member = null,
                FilePath = file,
                LineStart = line,
                LineEnd = line,
            };
            var merged = first with { Where = string.Join("; ", group.Select(r => r.Where)), Section = string.Join("; ", group.Select(r => r.Section).Distinct()) };
            yield return Entry(context, handler, first.Role, first.TypeFullName, first.Path, merged, inRepository: false, new AuthorisationState());
        }
    }

    private static DetectedEntryPoint Entry(
        DetectionContext context, HandlerLocation handler, string role, string typeName, string? path,
        Registration? registration, bool inRepository, AuthorisationState attributes)
    {
        // A handler answers at a path, so web.config <authorization> for that
        // path applies; a pattern ("*.axd") takes the root's rules. A module
        // sees every request and authenticates nothing itself.
        string? authorisation = null;
        string? authDeclared = null;
        if (role == "handler")
        {
            var urlPath = path is null || path.Contains('*') ? "" : path;
            (authorisation, authDeclared) = context.WebAuthorisation(attributes, urlPath);
        }

        return new DetectedEntryPoint(
            Detected.Record(EntryPointKinds.HttpHandler, context.Project, handler, new Confidence(), authDeclared) with
            {
                HttpHandler = new HttpHandlerDetail
                {
                    Role = role,
                    TypeName = typeName,
                    Path = path,
                    Verb = registration?.Verb,
                    RegisteredAt = registration?.Where,
                    ConfigSection = registration?.Section,
                    InRepository = inRepository,
                    Authorisation = authorisation,
                },
            },
            Detected.Identity(handler.Namespace, handler.Type, handler.Member),
            $"{role}:{path ?? ""}",
            null);
    }

    /// <summary>A folder web.config's <c>path</c> is relative to its folder
    /// (Views/web.config's <c>*</c> is <c>Views/*</c>), so it is qualified
    /// with the folder's path within the project.</summary>
    private static IEnumerable<Registration> Registrations(IReadOnlyList<ConfigFile> configs, string projectDirectory)
    {
        foreach (var config in configs)
        {
            var root = config.Document?.Root;
            if (root is null)
            {
                continue;
            }

            var folder = projectDirectory.Length == 0 ? config.Directory
                : config.Directory.Length > projectDirectory.Length ? config.Directory[(projectDirectory.Length + 1)..] : "";

            var sections = new[]
            {
                ("handler", root.Element("system.web")?.Element("httpHandlers"), "system.web/httpHandlers"),
                ("handler", root.Element("system.webServer")?.Element("handlers"), "system.webServer/handlers"),
                ("module", root.Element("system.web")?.Element("httpModules"), "system.web/httpModules"),
                ("module", root.Element("system.webServer")?.Element("modules"), "system.webServer/modules"),
            };
            foreach (var (role, section, name) in sections)
            {
                foreach (var add in section?.Elements("add") ?? Enumerable.Empty<XElement>())
                {
                    // An <add> with no type is IIS plumbing (an ISAPI or
                    // static-file mapping), not managed code.
                    var type = ((string?)add.Attribute("type"))?.Split(',')[0].Trim();
                    if (string.IsNullOrEmpty(type))
                    {
                        continue;
                    }

                    var path = (string?)add.Attribute("path");
                    if (path is not null && folder.Length > 0)
                    {
                        path = $"{folder}/{path.TrimStart('/')}";
                    }

                    yield return new Registration(role, type, path, (string?)add.Attribute("verb"), config.Where(add), name);
                }
            }
        }
    }

    private static string SimpleName(string fullName) => fullName.Split('.')[^1];

    private static (string File, int Line) SplitWhere(string where)
    {
        var colon = where.LastIndexOf(':');
        return (where[..colon], int.TryParse(where[(colon + 1)..], out var line) ? line : 1);
    }
}

/// <summary><c>global_asax</c>: the <c>HttpApplication</c> event methods —
/// Application_Start, Application_BeginRequest, Session_Start and their
/// siblings — one entry per method written.</summary>
public sealed partial class GlobalAsaxDetector : IEntryPointDetector
{
    private static readonly IReadOnlySet<string> HttpApplication = new HashSet<string>(StringComparer.Ordinal) { "HttpApplication" };

    [GeneratedRegex(@"^(Application|Session)_[A-Za-z]+$")]
    private static partial Regex EventMethod();

    private static readonly IReadOnlySet<string> ApplicationScoped = new HashSet<string>(StringComparer.Ordinal)
    {
        "Application_Start", "Application_End", "Application_Init", "Application_Disposed", "Application_OnStart", "Application_OnEnd",
    };

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax && !t.IsAbstract))
        {
            if (project.ResolveBase(type, HttpApplication) is not { } resolved)
            {
                continue;
            }

            var confidence = new Confidence();
            if (resolved.Via is not null)
            {
                confidence.Reduce(0.9, $"HttpApplication reached through in-project base {resolved.Via}");
            }

            foreach (var method in type.Syntax.Members.OfType<MethodDeclarationSyntax>().Where(m => EventMethod().IsMatch(m.Identifier.Text)))
            {
                var name = method.Identifier.Text;
                var scope = name.StartsWith("Session_", StringComparison.Ordinal) ? "session"
                    : ApplicationScoped.Contains(name) ? "application"
                    : "request";
                var (start, end) = SyntaxHelpers.MemberLines(method);
                var handler = new HandlerLocation
                {
                    Type = type.Name,
                    Namespace = type.Namespace,
                    Member = name,
                    FilePath = type.File.RelativePath,
                    LineStart = start,
                    LineEnd = end,
                };
                yield return new DetectedEntryPoint(
                    Detected.Record(EntryPointKinds.GlobalAsax, project, handler, confidence, authDeclared: null) with
                    {
                        GlobalAsax = new GlobalAsaxDetail { ApplicationClass = type.Name, Event = name, Scope = scope },
                    },
                    Detected.Identity(type.Namespace, type.Name, name, SyntaxHelpers.ParameterSignature(method.ParameterList)),
                    null,
                    null);
            }
        }
    }
}

/// <summary>
/// <c>owin_startup</c>: the OWIN pipeline's startup class — named by
/// <c>[assembly: OwinStartup(typeof(X))]</c>, by the <c>owin:appStartup</c>
/// app setting, or by convention (a class named Startup with
/// <c>Configuration(IAppBuilder)</c>) — handled at <c>Configuration</c>, with
/// the middleware it registers across every part of the partial class.
/// </summary>
public sealed class OwinStartupDetector : IEntryPointDetector
{
    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        var declared = new List<(string Class, string DeclaredBy, string Where)>();

        foreach (var file in project.Files)
        {
            foreach (var list in file.Root.AttributeLists.Where(l => l.Target?.Identifier.Text == "assembly"))
            {
                foreach (var attribute in list.Attributes.Where(a => RoslynNameHelpers.AttributeSimpleName(a.Name) == "OwinStartup"))
                {
                    var typeOf = attribute.ArgumentList?.Arguments.Select(a => a.Expression).OfType<TypeOfExpressionSyntax>().FirstOrDefault();
                    if (typeOf is not null && SyntaxHelpers.RightmostTypeName(typeOf.Type) is { } name)
                    {
                        declared.Add((name, "assembly_attribute", $"{file.RelativePath}:{SyntaxHelpers.Lines(attribute).Start}"));
                    }
                }
            }
        }

        foreach (var config in context.ProjectConfigs)
        {
            var add = config.Document?.Root?.Element("appSettings")?.Elements("add")
                .FirstOrDefault(a => (string?)a.Attribute("key") == "owin:appStartup");
            if (add is not null && ((string?)add.Attribute("value"))?.Split(',')[0].Trim().Split('.')[^1] is { Length: > 0 } name)
            {
                declared.Add((name, "app_setting", config.Where(add)));
            }
        }

        if (declared.Count == 0)
        {
            var automaticOff = context.ProjectConfigs.Any(c => c.Document?.Root?.Element("appSettings")?.Elements("add")
                .Any(a => (string?)a.Attribute("key") == "owin:AutomaticAppStartup" && ((string?)a.Attribute("value"))?.ToLowerInvariant() == "false") == true);
            if (!automaticOff && project.TypesByName["Startup"].Any(t => ConfigurationMethod(t) is not null))
            {
                declared.Add(("Startup", "convention", ""));
            }
        }

        foreach (var (className, declaredBy, where) in declared.DistinctBy(d => d.Class))
        {
            var parts = project.TypesByName[className].Where(t => t.Syntax is ClassDeclarationSyntax).ToList();
            var withConfiguration = parts.Select(p => (Part: p, Method: ConfigurationMethod(p))).FirstOrDefault(x => x.Method is not null);
            if (parts.Count == 0)
            {
                continue;
            }

            var confidence = new Confidence();
            if (withConfiguration.Method is null)
            {
                confidence.Reduce(0.7, $"{className} has no Configuration(IAppBuilder) method written");
            }

            var owner = withConfiguration.Part ?? parts[0];
            var (start, end) = withConfiguration.Method is null ? SyntaxHelpers.MemberLines(owner.Syntax) : SyntaxHelpers.MemberLines(withConfiguration.Method);
            var handler = new HandlerLocation
            {
                Type = className,
                Namespace = owner.Namespace,
                Member = withConfiguration.Method?.Identifier.Text,
                FilePath = owner.File.RelativePath,
                LineStart = start,
                LineEnd = end,
            };
            yield return new DetectedEntryPoint(
                Detected.Record(EntryPointKinds.OwinStartup, project, handler, confidence, authDeclared: null) with
                {
                    OwinStartup = new OwinStartupDetail
                    {
                        StartupClass = className,
                        DeclaredBy = declaredBy,
                        DeclaredAt = where.Length == 0 ? null : where,
                        Middleware = Middleware(parts),
                    },
                },
                Detected.Identity(owner.Namespace, className, handler.Member),
                null,
                null);
        }
    }

    private static MethodDeclarationSyntax? ConfigurationMethod(DeclaredType type) =>
        type.Syntax.Members.OfType<MethodDeclarationSyntax>().FirstOrDefault(m =>
            m.Identifier.Text == "Configuration"
            && m.ParameterList.Parameters.Any(p => p.Type is not null && SyntaxHelpers.RightmostTypeName(p.Type) == "IAppBuilder"));

    /// <summary><c>app.UseX(...)</c> and <c>app.Use&lt;T&gt;()</c> calls on
    /// an <c>IAppBuilder</c> parameter, in file then source order.</summary>
    private static IReadOnlyList<string> Middleware(IReadOnlyList<DeclaredType> parts)
    {
        var middleware = new List<string>();
        foreach (var part in parts.OrderBy(p => p.File.RelativePath, StringComparer.Ordinal))
        {
            var builders = part.Syntax.DescendantNodes().OfType<ParameterSyntax>()
                .Where(p => p.Type is not null && SyntaxHelpers.RightmostTypeName(p.Type) == "IAppBuilder")
                .Select(p => p.Identifier.Text)
                .ToHashSet(StringComparer.Ordinal);
            foreach (var call in part.Syntax.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                if (call.Expression is MemberAccessExpressionSyntax { Expression: IdentifierNameSyntax receiver, Name: var name }
                    && builders.Contains(receiver.Identifier.Text)
                    && name.Identifier.Text.StartsWith("Use", StringComparison.Ordinal))
                {
                    middleware.Add(name is GenericNameSyntax generic ? $"{generic.Identifier.Text}<{generic.TypeArgumentList.Arguments}>" : name.Identifier.Text);
                }
            }
        }

        return middleware;
    }
}
