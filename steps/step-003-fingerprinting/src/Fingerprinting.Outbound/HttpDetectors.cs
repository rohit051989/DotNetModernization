using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using static Fingerprinting.Outbound.DetectionSupport;

namespace Fingerprinting.Outbound;

/// <summary>
/// <c>http_client</c> — Part C1. A client's base address where it is
/// configured (<c>new HttpClient { BaseAddress = … }</c>, <c>client.BaseAddress = …</c>,
/// <c>AddHttpClient(…, c =&gt; c.BaseAddress = …)</c>), and a request whose URL
/// is absolute (<c>GetAsync("https://…")</c>, <c>$"{_apiUrl}{uri}"</c> with
/// <c>_apiUrl</c> from configuration). A relative URL goes to a base address
/// already recorded, so it adds nothing. WebClient, WebRequest and RestSharp too.
/// </summary>
public static class HttpClientDetector
{
    private static readonly HashSet<string> RequestMethods = new(StringComparer.Ordinal)
    {
        "GetAsync", "PostAsync", "PutAsync", "PatchAsync", "DeleteAsync", "GetStringAsync", "GetByteArrayAsync", "GetStreamAsync",
        "GetFromJsonAsync", "PostAsJsonAsync", "PutAsJsonAsync", "PatchAsJsonAsync", "DeleteFromJsonAsync",
    };

    private static readonly HashSet<string> WebClientMethods = new(StringComparer.Ordinal)
    {
        "DownloadString", "DownloadData", "DownloadFile", "OpenRead", "OpenWrite", "UploadString", "UploadData", "UploadFile", "UploadValues",
        "DownloadStringTaskAsync", "DownloadDataTaskAsync", "DownloadFileTaskAsync", "UploadStringTaskAsync", "UploadDataTaskAsync",
        "UploadValuesTaskAsync", "DownloadStringAsync", "DownloadDataAsync", "UploadStringAsync",
    };

    public static IEnumerable<Detected> Detect(DetectionContext context)
    {
        foreach (var file in context.SourceFiles)
        {
            foreach (var node in file.Root.DescendantNodes())
            {
                var detected = node switch
                {
                    ObjectCreationExpressionSyntax creation => FromCreation(context, file, creation),
                    AssignmentExpressionSyntax assignment => FromBaseAddressAssignment(context, file, assignment),
                    InvocationExpressionSyntax invocation => FromInvocation(context, file, invocation),
                    _ => null,
                };
                if (detected is not null)
                {
                    yield return detected;
                }
            }
        }
    }

    private static Detected? FromCreation(DetectionContext context, ParsedFile file, ObjectCreationExpressionSyntax creation)
    {
        var type = SyntaxHelpers.RightmostTypeName(creation.Type);
        switch (type)
        {
            case "HttpClient" or "WebClient" when BaseAddressIn(creation.Initializer) is { } baseAddress:
                return Make(context, file, creation, baseAddress, type, clientName: null, typedClient: null, 1.0, [],
                    endpoint => OperationTracer.HttpClientRequests(context, file, creation, endpoint, null, null));
            case "RestClient" when creation.ArgumentList?.Arguments.FirstOrDefault()?.Expression is { } argument:
            {
                // new RestClient("https://…") or new RestClient(new RestClientOptions("https://…"))
                var url = argument is ObjectCreationExpressionSyntax { ArgumentList.Arguments: [var inner, ..] } options
                          && SyntaxHelpers.RightmostTypeName(options.Type) == "RestClientOptions"
                    ? inner.Expression
                    : argument;
                return Make(context, file, creation, url, "RestSharp", null, null, 1.0, [],
                    _ => [OperationTracer.UnresolvedAt(CallSiteOf(file, creation), "RestSharp requests are not traced")]);
            }

            default:
                return null;
        }
    }

    private static ExpressionSyntax? BaseAddressIn(InitializerExpressionSyntax? initializer) =>
        initializer?.Expressions.OfType<AssignmentExpressionSyntax>()
            .FirstOrDefault(a => a.Left is IdentifierNameSyntax { Identifier.Text: "BaseAddress" })?.Right;

    /// <summary><c>client.BaseAddress = …</c> on an HttpClient outside an
    /// <c>AddHttpClient</c> registration (which records its own).</summary>
    private static Detected? FromBaseAddressAssignment(DetectionContext context, ParsedFile file, AssignmentExpressionSyntax assignment)
    {
        if (assignment.Left is not MemberAccessExpressionSyntax { Name.Identifier.Text: "BaseAddress" } member
            || assignment.Parent is InitializerExpressionSyntax
            || assignment.Ancestors().OfType<InvocationExpressionSyntax>().Any(i => SyntaxHelpers.InvokedName(i) is "AddHttpClient" or "ConfigureHttpClient"))
        {
            return null;
        }

        var receiverType = ReceiverType(member.Expression);
        var inLambda = assignment.Ancestors().Any(a => a is LambdaExpressionSyntax);
        if (receiverType is not ("HttpClient" or "WebClient") && !inLambda)
        {
            return null;
        }

        return Make(context, file, assignment, assignment.Right, receiverType ?? "HttpClient", null, null, receiverType is null ? 0.8 : 1.0,
            receiverType is null ? ["BaseAddress set on a lambda parameter taken to be an HttpClient"] : [],
            endpoint => OperationTracer.HttpClientRequests(context, file, assignment, endpoint, null, null));
    }

    private static Detected? FromInvocation(DetectionContext context, ParsedFile file, InvocationExpressionSyntax invocation)
    {
        var name = SyntaxHelpers.InvokedName(invocation);
        var receiver = SyntaxHelpers.Receiver(invocation);
        var firstArgument = invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression;

        if (name is "AddHttpClient" or "ConfigureHttpClient")
        {
            return FromRegistration(context, file, invocation);
        }

        if (firstArgument is null || receiver is null)
        {
            return null;
        }

        if (name is "Create" or "CreateHttp" && receiver.ToString() is "WebRequest" or "HttpWebRequest" or "System.Net.WebRequest")
        {
            return Request(context, file, invocation, firstArgument, "WebRequest", receiverHasNoBaseAddress: true);
        }

        var receiverType = ReceiverType(receiver);
        if (receiverType == "HttpClient" && RequestMethods.Contains(name!))
        {
            return Request(context, file, invocation, firstArgument, "HttpClient", ReceiverHasNoBaseAddress(receiver));
        }

        if (receiverType == "WebClient" && WebClientMethods.Contains(name!))
        {
            return Request(context, file, invocation, firstArgument, "WebClient", ReceiverHasNoBaseAddress(receiver));
        }

        return null;
    }

    /// <summary><c>AddHttpClient("name", c =&gt; c.BaseAddress = …)</c>,
    /// <c>AddHttpClient&lt;TClient&gt;(…)</c>, <c>AddHttpClient&lt;TInterface, TImpl&gt;(…)</c>.
    /// A registration with no base address records nothing: its requests
    /// carry absolute URLs, which are recorded where they are made.</summary>
    private static Detected? FromRegistration(DetectionContext context, ParsedFile file, InvocationExpressionSyntax invocation)
    {
        var baseAddress = invocation.ArgumentList.Arguments
            .SelectMany(a => a.Expression.DescendantNodesAndSelf().OfType<AssignmentExpressionSyntax>())
            .FirstOrDefault(a => a.Left is MemberAccessExpressionSyntax { Name.Identifier.Text: "BaseAddress" })?.Right;
        if (baseAddress is null)
        {
            return null;
        }

        var clientName = context.Symbols.Constant(invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression);
        var typed = invocation.Expression switch
        {
            MemberAccessExpressionSyntax { Name: GenericNameSyntax generic } => SyntaxHelpers.RightmostTypeName(generic.TypeArgumentList.Arguments[^1]),
            GenericNameSyntax generic => SyntaxHelpers.RightmostTypeName(generic.TypeArgumentList.Arguments[^1]),
            _ => null,
        };
        return Make(context, file, invocation, baseAddress, "IHttpClientFactory", clientName, typed, 1.0, [],
            endpoint => OperationTracer.HttpClientRequests(context, file, invocation, endpoint, typed, clientName));
    }

    private static Detected? Request(
        DetectionContext context, ParsedFile file, InvocationExpressionSyntax invocation, ExpressionSyntax url, string library, bool receiverHasNoBaseAddress)
    {
        var value = context.Resolver.Resolve(url, CallSiteEvaluator.Empty);
        var first = value.Parts.FirstOrDefault();
        switch (first)
        {
            case TextPart text when !text.Value.Contains("://", StringComparison.Ordinal) && value.Facts is null:
                return null;   // relative: goes to a base address already recorded
            case HolePart when value.Parts.Count > 0 && !receiverHasNoBaseAddress:
                // A runtime URL on a client whose base address this step
                // cannot see: relative or absolute is unknowable.
                return null;
        }

        return Make(context, file, invocation, url, library, null, null, first is HolePart ? 0.8 : 1.0,
            first is HolePart ? ["URL supplied at run time"] : [],
            _ => OperationTracer.HttpRequest(context, file, invocation, url));
    }

    /// <summary>The receiver is a local or field initialized with
    /// <c>new HttpClient(…)</c> that sets no base address — so a runtime URL
    /// it is given is absolute.</summary>
    private static bool ReceiverHasNoBaseAddress(ExpressionSyntax receiver)
    {
        if (receiver is not IdentifierNameSyntax identifier)
        {
            return false;
        }

        var name = identifier.Identifier.Text;
        var initializer = CallSiteEvaluator.Scope(identifier).DescendantNodes().OfType<VariableDeclaratorSyntax>()
                              .LastOrDefault(v => v.Identifier.Text == name && v.SpanStart < identifier.SpanStart)?.Initializer?.Value
                          ?? identifier.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault()?.Members.OfType<FieldDeclarationSyntax>()
                              .SelectMany(f => f.Declaration.Variables).FirstOrDefault(v => v.Identifier.Text == name)?.Initializer?.Value;
        return initializer is ObjectCreationExpressionSyntax creation && BaseAddressIn(creation.Initializer) is null;
    }

    private static Detected Make(
        DetectionContext context, ParsedFile file, SyntaxNode site, ExpressionSyntax url, string library, string? clientName, string? typedClient,
        double confidence, IReadOnlyList<string> reasons, Func<Endpoint, IReadOnlyList<InvokedOperation>> operations)
    {
        var (endpoint, bindings, _) = Evaluate(context.Resolver, r => r.Resolve(url, CallSiteEvaluator.Empty), Endpoints.FromValue);
        var credentials = HttpCredentials.Find(context, file, site);
        var allReasons = reasons.ToList();
        if (endpoint.Resolution != Resolutions.Resolved)
        {
            confidence -= 0.1;
            allReasons.Add($"endpoint {endpoint.Resolution}");
        }

        var record = new Invocation
        {
            InvocationId = "",
            Mechanism = Mechanisms.HttpClient,
            ProjectPath = "",
            Endpoint = endpoint,
            EnvironmentBindings = bindings,
            AuthDeclared = credentials.Count > 0 ? AuthDeclared.Declared : AuthDeclared.NotAssessed,
            Credentials = credentials,
            Http = new HttpDetail { Library = library, ClientName = clientName, TypedClient = typedClient },
            CallSites = [CallSiteOf(file, site)],
            Operations = operations(endpoint),
            LinuxCompatibility = Pending,
            Confidence = Math.Round(confidence, 2),
            ConfidenceReasons = allReasons,
        };
        return new Detected(record, clientName ?? typedClient ?? "");
    }
}

/// <summary>
/// Credentials an HTTP or gRPC client is configured with, in the class that
/// configures or calls it: an <c>Authorization</c> header, an API-key header,
/// handler credentials. Kind and key path only (Part C5) — the key path when
/// the value is read from configuration, else where in code it is set.
/// </summary>
public static class HttpCredentials
{
    public static IReadOnlyList<CredentialReference> Find(DetectionContext context, ParsedFile file, SyntaxNode site)
    {
        var scope = site.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault() ?? (SyntaxNode)file.Root;
        var found = new SortedDictionary<string, CredentialReference>(StringComparer.Ordinal);

        foreach (var node in scope.DescendantNodes())
        {
            switch (node)
            {
                // client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token)
                case AssignmentExpressionSyntax { Left: MemberAccessExpressionSyntax { Name.Identifier.Text: "Authorization" } } assignment:
                {
                    var scheme = (assignment.Right as ObjectCreationExpressionSyntax)?.ArgumentList?.Arguments.FirstOrDefault()?.Expression;
                    var value = (assignment.Right as ObjectCreationExpressionSyntax)?.ArgumentList?.Arguments.ElementAtOrDefault(1)?.Expression;
                    var kind = context.Symbols.Constant(scheme) is { } s && s.Equals("Basic", StringComparison.OrdinalIgnoreCase) ? "password" : "token";
                    Add(found, context, file, node, kind, value);
                    break;
                }

                // headers.Add("X-Api-Key", key), TryAddWithoutValidation("Authorization", …)
                case InvocationExpressionSyntax invocation when SyntaxHelpers.InvokedName(invocation) is "Add" or "TryAddWithoutValidation"
                                                                && invocation.Expression.ToString().Contains("Headers", StringComparison.Ordinal):
                {
                    var header = context.Symbols.Constant(invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression);
                    var kind = header switch
                    {
                        null => null,
                        _ when header.Equals("Authorization", StringComparison.OrdinalIgnoreCase) => "token",
                        _ when header.Contains("key", StringComparison.OrdinalIgnoreCase) || header.Contains("subscription", StringComparison.OrdinalIgnoreCase) => "api_key",
                        _ when header.Contains("token", StringComparison.OrdinalIgnoreCase) => "token",
                        _ => null,
                    };
                    if (kind is not null)
                    {
                        Add(found, context, file, node, kind, invocation.ArgumentList.Arguments.ElementAtOrDefault(1)?.Expression);
                    }

                    break;
                }

                // handler.UseDefaultCredentials = true; handler.Credentials = CredentialCache.DefaultCredentials
                case AssignmentExpressionSyntax { Left: MemberAccessExpressionSyntax { Name.Identifier.Text: "UseDefaultCredentials" } } useDefault
                    when useDefault.Right.IsKind(SyntaxKind.TrueLiteralExpression):
                    Add(found, context, file, node, "windows", null);
                    break;
                case AssignmentExpressionSyntax { Left: MemberAccessExpressionSyntax { Name.Identifier.Text: "Credentials" } } credentials:
                    Add(found, context, file, node, credentials.Right.ToString().Contains("Default", StringComparison.Ordinal) ? "windows" : "password", null);
                    break;
                case InvocationExpressionSyntax certificate when SyntaxHelpers.InvokedName(certificate) == "Add"
                                                                 && certificate.Expression.ToString().Contains("ClientCertificates", StringComparison.Ordinal):
                    Add(found, context, file, node, "certificate", null);
                    break;
            }
        }

        return found.Values.ToList();
    }

    private static void Add(
        SortedDictionary<string, CredentialReference> found, DetectionContext context, ParsedFile file, SyntaxNode node, string kind, ExpressionSyntax? value)
    {
        if (found.ContainsKey(kind))
        {
            return;
        }

        // The key path it is read from, when configuration; never the value.
        var key = value is null ? null : context.Resolver.Resolve(value, CallSiteEvaluator.Empty).Keys.FirstOrDefault();
        var entry = key is null ? null : context.Config.Lookup(context.Project.ProjectDirectory, key).FirstOrDefault();
        found[kind] = new CredentialReference
        {
            Kind = kind,
            KeyPath = key?.KeyPath,
            SourceFile = entry?.File,
            DeclaredAt = CallSiteEvaluator.Where(file, node),
        };
    }
}

/// <summary>
/// <c>grpc_client</c> — <c>GrpcChannel.ForAddress(…)</c>,
/// <c>AddGrpcClient&lt;T&gt;(o =&gt; o.Address = …)</c> and Grpc.Core's
/// <c>new Channel("host:port", credentials)</c>. The contract is the
/// generated client constructed over the channel, when one is.
/// </summary>
public static class GrpcClientDetector
{
    public static IEnumerable<Detected> Detect(DetectionContext context)
    {
        foreach (var file in context.SourceFiles)
        {
            foreach (var node in file.Root.DescendantNodes())
            {
                switch (node)
                {
                    case InvocationExpressionSyntax invocation when SyntaxHelpers.InvokedName(invocation) == "ForAddress"
                                                                    && SyntaxHelpers.Receiver(invocation)?.ToString() is "GrpcChannel" or "Grpc.Net.Client.GrpcChannel"
                                                                    && invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression is { } address:
                        yield return Make(context, file, invocation, address, ContractOverChannel(invocation), url: true, registration: false);
                        break;

                    case InvocationExpressionSyntax invocation when SyntaxHelpers.InvokedName(invocation) == "AddGrpcClient":
                    {
                        var configured = invocation.ArgumentList.Arguments
                            .SelectMany(a => a.Expression.DescendantNodesAndSelf().OfType<AssignmentExpressionSyntax>())
                            .FirstOrDefault(a => a.Left is MemberAccessExpressionSyntax { Name.Identifier.Text: "Address" })?.Right;
                        var contract = invocation.Expression is MemberAccessExpressionSyntax { Name: GenericNameSyntax generic }
                            ? ContractName(generic.TypeArgumentList.Arguments[0])
                            : null;
                        if (configured is not null)
                        {
                            yield return Make(context, file, invocation, configured, contract, url: true, registration: true);
                        }

                        break;
                    }

                    case ObjectCreationExpressionSyntax creation when SyntaxHelpers.RightmostTypeName(creation.Type) == "Channel"
                                                                      && creation.ArgumentList?.Arguments.Count >= 2
                                                                      && creation.ArgumentList.Arguments.Any(a => a.Expression.ToString().Contains("Credentials", StringComparison.Ordinal)):
                        yield return Make(context, file, creation, creation.ArgumentList.Arguments[0].Expression, ContractOverChannel(creation), url: false, registration: false);
                        break;
                }
            }
        }
    }

    /// <summary><c>new Greeter.GreeterClient(channel)</c> in the same scope
    /// as the channel → <c>Greeter</c>.</summary>
    private static string? ContractOverChannel(ExpressionSyntax channelCreation)
    {
        var variable = channelCreation.Ancestors().OfType<VariableDeclaratorSyntax>().FirstOrDefault()?.Identifier.Text;
        if (variable is null)
        {
            return null;
        }

        return CallSiteEvaluator.Scope(channelCreation).DescendantNodes().OfType<ObjectCreationExpressionSyntax>()
            .Where(c => c.ArgumentList?.Arguments.FirstOrDefault()?.Expression is IdentifierNameSyntax { } argument && argument.Identifier.Text == variable)
            .Select(c => ContractName(c.Type))
            .FirstOrDefault(n => n is not null);
    }

    private static string? ContractName(TypeSyntax type)
    {
        if (type is QualifiedNameSyntax qualified && qualified.Right.Identifier.Text.EndsWith("Client", StringComparison.Ordinal))
        {
            return SyntaxHelpers.RightmostTypeName(qualified.Left);
        }

        var name = SyntaxHelpers.RightmostTypeName(type);
        return name is not null && name.EndsWith("Client", StringComparison.Ordinal) && name.Length > "Client".Length ? name[..^"Client".Length] : name;
    }

    private static Detected Make(DetectionContext context, ParsedFile file, SyntaxNode site, ExpressionSyntax address, string? contract, bool url, bool registration)
    {
        var (endpoint, bindings, _) = Evaluate(context.Resolver, r => r.Resolve(address, CallSiteEvaluator.Empty),
            value => url ? Endpoints.FromValue(value)
                : value.TextValue is { } text ? Endpoints.FromHostPort("grpc", text, value.Parts.OfType<TextPart>().FirstOrDefault()?.Source)
                : new Endpoint { Scheme = "grpc", Resolution = Resolutions.Unresolved, Placeholder = value.Placeholder ?? Label(value) });
        var credentials = HttpCredentials.Find(context, file, site);
        var record = new Invocation
        {
            InvocationId = "",
            Mechanism = Mechanisms.GrpcClient,
            ProjectPath = "",
            Endpoint = endpoint,
            EnvironmentBindings = bindings,
            AuthDeclared = credentials.Count > 0 ? AuthDeclared.Declared : AuthDeclared.NotAssessed,
            Credentials = credentials,
            Grpc = new GrpcDetail { Contract = contract },
            CallSites = [CallSiteOf(file, site)],
            Operations = OperationTracer.Grpc(context, file, site, contract, registration),
            LinuxCompatibility = Pending,
            Confidence = endpoint.Resolution == Resolutions.Resolved ? 1.0 : 0.9,
            ConfidenceReasons = endpoint.Resolution == Resolutions.Resolved ? [] : [$"endpoint {endpoint.Resolution}"],
        };
        return new Detected(record, contract ?? "");
    }
}
