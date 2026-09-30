using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

/// <summary><c>wcf_operation</c>: <c>[OperationContract]</c> members on
/// <c>[ServiceContract]</c> interfaces, with the implementing class where
/// found. Recorded in the implementing project.</summary>
public sealed class WcfOperationDetector : IEntryPointDetector
{
    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        foreach (var service in context.WcfContracts.Services.Where(s => s.Project.ProjectPath == context.Project.ProjectPath))
        {
            var implementation = service.Implementation;
            var owner = implementation ?? service.Contract.Type;
            var chain = implementation is null ? [] : context.Project.SelfAndBaseClasses(implementation);

            foreach (var operation in service.Contract.Operations)
            {
                // The implementing method, where one is written; else the
                // contract's declaration.
                var method = chain
                    .SelectMany(t => t.Syntax.Members.OfType<MethodDeclarationSyntax>().Select(m => (Type: t, Method: m)))
                    .FirstOrDefault(x => x.Method.Identifier.Text == operation.Name);
                var located = method.Method is not null ? (method.Type, method.Method) : (service.Contract.Type, operation.Method);
                var (start, end) = SyntaxHelpers.MemberLines(located.Item2);

                var authorisation = new AuthorisationState();
                if (implementation is not null)
                {
                    authorisation.AddAttributes(implementation.Syntax.AttributeLists);
                }

                if (method.Method is not null)
                {
                    authorisation.AddAttributes(method.Method.AttributeLists);
                }

                var handler = new HandlerLocation
                {
                    Type = owner.Name,
                    Namespace = owner.Namespace,
                    Member = operation.Name,
                    FilePath = located.Item1.File.RelativePath,
                    LineStart = start,
                    LineEnd = end,
                };
                var endpoints = Endpoints(service);
                var record = Detected.Record(EntryPointKinds.WcfOperation, context.Project, handler, service.Confidence,
                    AuthDeclared.From(NoneDeclared(authorisation, endpoints))) with
                {
                    Wcf = new WcfDetail
                    {
                        Contract = service.Contract.Type.Name,
                        Operation = operation.Name,
                        Implementation = implementation?.Name,
                        IsOneWay = operation.IsOneWay,
                        HostedBy = service.Hosts.FirstOrDefault()?.Kind,
                        HostFile = service.Hosts.FirstOrDefault()?.Where.Split(' ')[0],
                        Authorisation = authorisation.Text,
                        Endpoints = endpoints,
                    },
                };

                yield return new DetectedEntryPoint(
                    record,
                    Detected.Identity(owner.Namespace, owner.Name, operation.Name, SyntaxHelpers.ParameterSignature(operation.Method.ParameterList)),
                    $"{service.Contract.Type.Name}/{operation.Name}",
                    null);
            }
        }
    }

    /// <summary>The endpoints serving this contract, across every host. An
    /// endpoint whose contract could not be read is kept: it may serve it.</summary>
    private static IReadOnlyList<WcfEndpointDetail> Endpoints(WcfContractIndex.Service service) =>
        service.Hosts
            .SelectMany(h => h.Endpoints.Select(e => (Host: h, Endpoint: e)))
            .Where(x => x.Endpoint.Contract is null || x.Endpoint.Contract == service.Contract.Type.Name)
            .Select(x =>
            {
                var security = WcfSecurity.Resolve(x.Endpoint.Binding, x.Endpoint.SecurityMode,
                    x.Endpoint.TransportClientCredentialType, x.Endpoint.MessageClientCredentialType);
                return new WcfEndpointDetail
                {
                    HostKind = x.Host.Kind,
                    HostedAt = x.Host.Where,
                    Binding = security.Binding,
                    SecurityMode = security.SecurityMode,
                    ClientCredentialType = security.ClientCredentialType,
                    SecuritySource = security.SecuritySource,
                    Anonymous = security.Anonymous,
                    Address = x.Endpoint.Address,
                    Source = x.Endpoint.Source,
                    DeclaredAt = x.Endpoint.Where,
                    Condition = x.Endpoint.Condition,
                };
            })
            .OrderBy(e => e.HostKind, StringComparer.Ordinal)
            .ThenBy(e => e.HostedAt, StringComparer.Ordinal)
            .ThenBy(e => e.DeclaredAt, StringComparer.Ordinal)
            .ToList();

    /// <summary>A <c>[PrincipalPermission]</c> demand declares
    /// authentication. Otherwise the endpoints decide: reachable with no
    /// client credential through any one of them is none declared; every one
    /// taking a credential is declared; anything else — no endpoint declared,
    /// or one whose credential could not be determined — is not assessed.</summary>
    private static bool? NoneDeclared(AuthorisationState attributes, IReadOnlyList<WcfEndpointDetail> endpoints)
    {
        if (attributes.AnyAuthorise)
        {
            return false;
        }

        if (endpoints.Count == 0)
        {
            return null;
        }

        if (endpoints.Any(e => e.Anonymous == true))
        {
            return true;
        }

        return endpoints.All(e => e.Anonymous == false) ? false : null;
    }
}

/// <summary><c>asmx_web_method</c>: <c>[WebMethod]</c> members in
/// <c>.asmx.cs</c> files.</summary>
public sealed class AsmxWebMethodDetector : IEntryPointDetector
{
    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        foreach (var type in project.Types.Where(t => t.File.RelativePath.EndsWith(".asmx.cs", StringComparison.OrdinalIgnoreCase)))
        {
            var servicePath = "/" + project.PathWithinProject(type.File.RelativePath)[..^".cs".Length];
            foreach (var method in type.Syntax.Members.OfType<MethodDeclarationSyntax>())
            {
                if (!SyntaxHelpers.HasAttribute(method.AttributeLists, "WebMethod"))
                {
                    continue;
                }

                var source = new AuthorisationState().AddAttributes(type.Syntax.AttributeLists).AddAttributes(method.AttributeLists);
                var (authorisation, authDeclared) = context.WebAuthorisation(source, servicePath);
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
                    Detected.Record(EntryPointKinds.AsmxWebMethod, project, handler, new Confidence(), authDeclared) with
                    {
                        Asmx = new AsmxDetail { ServicePath = servicePath, Method = method.Identifier.Text, Authorisation = authorisation },
                    },
                    Detected.Identity(type.Namespace, type.Name, method.Identifier.Text, SyntaxHelpers.ParameterSignature(method.ParameterList)),
                    servicePath,
                    null);
            }
        }
    }
}

/// <summary><c>webforms_page</c>: <c>.aspx</c> code-behind classes deriving
/// <c>Page</c>, directly or through an in-project base page.</summary>
public sealed class WebFormsPageDetector : IEntryPointDetector
{
    private static readonly IReadOnlySet<string> PageBase = new HashSet<string>(StringComparer.Ordinal) { "Page" };

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        foreach (var type in project.Types.Where(t => t.File.RelativePath.EndsWith(".aspx.cs", StringComparison.OrdinalIgnoreCase)))
        {
            if (type.Syntax is not ClassDeclarationSyntax || project.ResolveBase(type, PageBase) is not { } resolved)
            {
                continue;
            }

            var confidence = new Confidence();
            if (resolved.Via is not null)
            {
                confidence.Reduce(0.9, $"Page reached through in-project base page {resolved.Via}");
            }

            var pagePath = "/" + project.PathWithinProject(type.File.RelativePath)[..^".cs".Length];
            var (authorisation, authDeclared) = context.WebAuthorisation(new AuthorisationState().AddAttributes(type.Syntax.AttributeLists), pagePath);
            var (start, end) = SyntaxHelpers.MemberLines(type.Syntax);
            var handler = new HandlerLocation
            {
                Type = type.Name,
                Namespace = type.Namespace,
                Member = null,
                FilePath = type.File.RelativePath,
                LineStart = start,
                LineEnd = end,
            };
            yield return new DetectedEntryPoint(
                Detected.Record(EntryPointKinds.WebFormsPage, project, handler, confidence, authDeclared) with
                {
                    WebForms = new WebFormsDetail { PagePath = pagePath, CodeBehindClass = type.Name, Authorisation = authorisation },
                },
                Detected.Identity(type.Namespace, type.Name, null),
                pagePath,
                null);
        }
    }
}

/// <summary><c>grpc_service_method</c>: overrides on classes deriving from a
/// generated <c>Service.ServiceBase</c> type.</summary>
public sealed partial class GrpcServiceMethodDetector : IEntryPointDetector
{
    [GeneratedRegex(@"^\s*package\s+([\w.]+)\s*;", RegexOptions.Multiline)]
    private static partial Regex ProtoPackage();

    [GeneratedRegex(@"^\s*service\s+(\w+)\s*\{", RegexOptions.Multiline)]
    private static partial Regex ProtoService();

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        var protoServices = ProtoServices(project);
        var grpcEvidence = project.HasPackage("Grpc.AspNetCore", "Grpc.AspNetCore.Server", "Grpc.Core")
                           || project.AuxiliaryFiles.Any(a => a.RelativePath.EndsWith(".proto", StringComparison.OrdinalIgnoreCase));

        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax && !t.IsAbstract))
        {
            var service = GeneratedServiceName(type);
            if (service is null)
            {
                continue;
            }

            var classConfidence = new Confidence();
            if (!grpcEvidence)
            {
                classConfidence.Reduce(0.7, "no Grpc package or .proto file in the project to confirm the generated base");
            }

            var mapped = MappedServiceConventions(project, type.Name);
            protoServices.TryGetValue(service, out var proto);

            foreach (var method in type.Syntax.Members.OfType<MethodDeclarationSyntax>())
            {
                if (!SyntaxHelpers.HasModifier(method, "override") || !SyntaxHelpers.HasModifier(method, "public"))
                {
                    continue;
                }

                var authorisation = new AuthorisationState().AddAttributes(type.Syntax.AttributeLists).AddAttributes(method.AttributeLists);
                foreach (var call in mapped)
                {
                    authorisation.AddConventionCall(call);
                }

                authorisation.AddGlobal(context.Conventions.EndpointAuthorisation);

                var name = method.Identifier.Text;
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
                var fullMethod = proto.File is null ? null : $"/{(proto.Package is null ? "" : proto.Package + ".")}{service}/{name}";
                yield return new DetectedEntryPoint(
                    Detected.Record(EntryPointKinds.GrpcServiceMethod, project, handler, classConfidence, AuthDeclared.From(authorisation)) with
                    {
                        Grpc = new GrpcDetail
                        {
                            Service = service,
                            Method = name,
                            ProtoPackage = proto.Package,
                            ProtoFile = proto.File,
                            FullMethod = fullMethod,
                            Authorisation = authorisation.Text,
                        },
                    },
                    Detected.Identity(type.Namespace, type.Name, name, SyntaxHelpers.ParameterSignature(method.ParameterList)),
                    fullMethod ?? $"{service}/{name}",
                    null);
            }
        }
    }

    /// <summary><c>Billing.BillingBase</c> → <c>Billing</c>: the generated
    /// nested base named for its service.</summary>
    private static string? GeneratedServiceName(DeclaredType type)
    {
        foreach (var baseType in type.Syntax.BaseList?.Types ?? default)
        {
            if (baseType.Type is QualifiedNameSyntax qualified
                && SyntaxHelpers.RightmostTypeName(qualified.Left) is { } outer
                && qualified.Right.Identifier.Text == outer + "Base")
            {
                return outer;
            }
        }

        return null;
    }

    /// <summary>Conventions chained on <c>MapGrpcService&lt;T&gt;()</c>.</summary>
    private static List<InvocationExpressionSyntax> MappedServiceConventions(ProjectSource project, string className) =>
        project.Files
            .SelectMany(f => f.Root.DescendantNodes().OfType<InvocationExpressionSyntax>())
            .Where(i => i.Expression is MemberAccessExpressionSyntax { Name: GenericNameSyntax { Identifier.Text: "MapGrpcService" } generic }
                        && generic.TypeArgumentList.Arguments.Any(a => SyntaxHelpers.RightmostTypeName(a) == className))
            .SelectMany(SyntaxHelpers.ChainedCalls)
            .ToList();

    private static Dictionary<string, (string? Package, string? File)> ProtoServices(ProjectSource project)
    {
        var services = new Dictionary<string, (string?, string?)>(StringComparer.Ordinal);
        foreach (var (path, text) in project.AuxiliaryFiles.Where(a => a.RelativePath.EndsWith(".proto", StringComparison.OrdinalIgnoreCase)))
        {
            var package = ProtoPackage().Match(text) is { Success: true } p ? p.Groups[1].Value : null;
            foreach (Match service in ProtoService().Matches(text))
            {
                services.TryAdd(service.Groups[1].Value, (package, path));
            }
        }

        return services;
    }
}

/// <summary><c>signalr_hub_method</c>: public methods on <c>Hub</c> and
/// <c>Hub&lt;T&gt;</c> subclasses.</summary>
public sealed class SignalRHubMethodDetector : IEntryPointDetector
{
    private static readonly IReadOnlySet<string> HubBase = new HashSet<string>(StringComparer.Ordinal) { "Hub" };

    public IEnumerable<DetectedEntryPoint> Detect(DetectionContext context)
    {
        var project = context.Project;
        foreach (var type in project.Types.Where(t => t.Syntax is ClassDeclarationSyntax && !t.IsAbstract))
        {
            if (project.ResolveBase(type, HubBase) is not { } resolved)
            {
                continue;
            }

            var confidence = new Confidence();
            if (resolved.Via is not null)
            {
                confidence.Reduce(0.9, $"Hub reached through in-project base {resolved.Via}");
            }

            var (hubRoute, conventions) = HubMapping(project, type.Name);
            foreach (var method in type.Syntax.Members.OfType<MethodDeclarationSyntax>())
            {
                if (!SyntaxHelpers.HasModifier(method, "public") || SyntaxHelpers.HasModifier(method, "static")
                    || SyntaxHelpers.HasModifier(method, "override"))
                {
                    continue;
                }

                var authorisation = new AuthorisationState().AddAttributes(type.Syntax.AttributeLists).AddAttributes(method.AttributeLists);
                foreach (var call in conventions)
                {
                    authorisation.AddConventionCall(call);
                }

                authorisation.AddGlobal(context.Conventions.EndpointAuthorisation);

                var name = method.Identifier.Text;
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
                    Detected.Record(EntryPointKinds.SignalRHubMethod, project, handler, confidence, AuthDeclared.From(authorisation)) with
                    {
                        SignalR = new SignalRDetail { Hub = type.Name, Method = name, HubRoute = hubRoute, Authorisation = authorisation.Text },
                    },
                    Detected.Identity(type.Namespace, type.Name, name, SyntaxHelpers.ParameterSignature(method.ParameterList)),
                    hubRoute is null ? $"{type.Name}/{name}" : $"{hubRoute}/{name}",
                    null);
            }
        }
    }

    private static (string? Route, List<InvocationExpressionSyntax> Conventions) HubMapping(ProjectSource project, string hubName)
    {
        foreach (var invocation in project.Files.SelectMany(f => f.Root.DescendantNodes().OfType<InvocationExpressionSyntax>()))
        {
            if (invocation.Expression is MemberAccessExpressionSyntax { Name: GenericNameSyntax { Identifier.Text: "MapHub" } generic }
                && generic.TypeArgumentList.Arguments.Any(a => SyntaxHelpers.RightmostTypeName(a) == hubName))
            {
                var route = SyntaxHelpers.StringValue(invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression);
                return (route?.TrimStart('/'), SyntaxHelpers.ChainedCalls(invocation).ToList());
            }
        }

        return (null, []);
    }
}
