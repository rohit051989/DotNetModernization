using System.Text;
using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using static Fingerprinting.Outbound.DetectionSupport;

namespace Fingerprinting.Outbound;

/// <summary>
/// The operations a client invokes (outbound-invocation-inventory 1.2.0):
/// for SOAP the method called on the proxy or channel, for HTTP the verb and
/// path of each request, for gRPC the method called on the client stub —
/// each with its own call site, so step 11 can match a call to the entry
/// point it reaches. Syntax only: the client is followed from where it is
/// created to the variable or field holding it, through <c>CreateChannel()</c>
/// for a channel factory, to the members invoked on it. What cannot be
/// followed statically is recorded as one unresolved operation with the
/// reason — never guessed.
/// </summary>
public static class OperationTracer
{
    /// <summary>Members of the WCF communication object and client base,
    /// not service operations.</summary>
    private static readonly HashSet<string> SoapInfrastructure = new(StringComparer.Ordinal)
    {
        "Close", "CloseAsync", "Abort", "Open", "OpenAsync", "Dispose", "DisposeAsync", "BeginOpen", "EndOpen", "BeginClose", "EndClose",
        "GetProperty", "CreateChannel", "ToString", "GetType", "Equals", "GetHashCode", "DisplayInitializationUI", "BeginDisplayInitializationUI",
        "EndDisplayInitializationUI",
    };

    private static readonly HashSet<string> GrpcInfrastructure = new(StringComparer.Ordinal) { "WithHost", "ToString", "GetType", "Equals", "GetHashCode" };

    private static readonly Dictionary<string, string> HttpVerbs = new(StringComparer.Ordinal)
    {
        ["GetAsync"] = "GET", ["GetStringAsync"] = "GET", ["GetByteArrayAsync"] = "GET", ["GetStreamAsync"] = "GET", ["GetFromJsonAsync"] = "GET",
        ["PostAsync"] = "POST", ["PostAsJsonAsync"] = "POST", ["PutAsync"] = "PUT", ["PutAsJsonAsync"] = "PUT",
        ["PatchAsync"] = "PATCH", ["PatchAsJsonAsync"] = "PATCH", ["DeleteAsync"] = "DELETE", ["DeleteFromJsonAsync"] = "DELETE",
        ["DownloadString"] = "GET", ["DownloadData"] = "GET", ["DownloadFile"] = "GET", ["OpenRead"] = "GET",
        ["DownloadStringTaskAsync"] = "GET", ["DownloadDataTaskAsync"] = "GET", ["DownloadFileTaskAsync"] = "GET", ["DownloadStringAsync"] = "GET",
        ["DownloadDataAsync"] = "GET", ["UploadString"] = "POST", ["UploadData"] = "POST", ["UploadFile"] = "POST", ["UploadValues"] = "POST",
        ["UploadStringTaskAsync"] = "POST", ["UploadDataTaskAsync"] = "POST", ["UploadValuesTaskAsync"] = "POST", ["UploadStringAsync"] = "POST",
        ["OpenWrite"] = "POST",
    };

    // ---------- SOAP ----------

    /// <summary>The operations called on a WCF client created at
    /// <paramref name="site"/>: a <c>ChannelFactory&lt;T&gt;</c> (or a helper
    /// returning one) when <paramref name="isFactory"/>, else a
    /// <c>ClientBase&lt;T&gt;</c> client.</summary>
    public static IReadOnlyList<InvokedOperation> Soap(DetectionContext context, ParsedFile file, SyntaxNode site, string contract, string? clientType, bool isFactory)
    {
        var declared = ContractOperations(context, contract);
        bool IsOperation(string name) =>
            declared is null ? !SoapInfrastructure.Contains(name) : declared.Contains(name) || (name.EndsWith("Async", StringComparison.Ordinal) && declared.Contains(name[..^5]));

        var calls = Holder(site) is { } holder ? CallsOnClient(file, holder, isFactory, IsOperation) : [];
        if (calls.Count > 0)
        {
            return calls;
        }

        // The proxy leaves the method that creates it (handed to a form, a
        // presenter): every call made on a receiver declared with the
        // contract or client type, anywhere in the project.
        var typed = TypedReceiverCalls(context, [contract, .. clientType is null ? [] : new[] { clientType }], IsOperation)
            .Select(x => new InvokedOperation
            {
                Operation = x.Name, Member = x.Name, Resolution = Resolutions.Resolved, CallSite = CallSiteOf(x.File, x.Call),
                Reason = $"called on a receiver declared as {x.Type}; the proxy is passed on from where it is created",
            })
            .ToList();
        return typed.Count > 0 ? typed : [Unresolved(file, site, "no operation is called on the client where it is created, or on a receiver of its type")];
    }

    /// <summary>Operations called on the client in the scope holding it —
    /// through <c>CreateChannel()</c> for a factory.</summary>
    private static List<InvokedOperation> CallsOnClient(ParsedFile file, (string Name, SyntaxNode Scope) holder, bool isFactory, Func<string, bool> IsOperation)
    {
        var proxies = new HashSet<string>(StringComparer.Ordinal);
        if (isFactory)
        {
            foreach (var creation in holder.Scope.DescendantNodes().OfType<InvocationExpressionSyntax>()
                         .Where(i => SyntaxHelpers.InvokedName(i) == "CreateChannel" && ReceiverName(i) == holder.Name))
            {
                if (Holder(creation) is { } proxy)
                {
                    proxies.Add(proxy.Name);
                }
            }
        }
        else
        {
            proxies.Add(holder.Name);
        }

        return holder.Scope.DescendantNodes().OfType<InvocationExpressionSyntax>()
            .Where(i => SyntaxHelpers.InvokedName(i) is { } name && IsOperation(name)
                        && (proxies.Contains(ReceiverName(i) ?? "")
                            // factory.CreateChannel().Op(...)
                            || (isFactory && SyntaxHelpers.Receiver(i) is InvocationExpressionSyntax inner
                                && SyntaxHelpers.InvokedName(inner) == "CreateChannel" && ReceiverName(inner) == holder.Name)))
            .Select(i => new InvokedOperation
            {
                Operation = SyntaxHelpers.InvokedName(i), Member = SyntaxHelpers.InvokedName(i), Resolution = Resolutions.Resolved,
                CallSite = CallSiteOf(file, i),
            })
            .ToList();
    }

    /// <summary>The operations a contract interface declares, or null when
    /// the interface is not there to read (a contract from a package). A
    /// name can be declared more than once (a generated proxy's contract and
    /// an unrelated domain interface): the client's own project first, then
    /// a <c>[ServiceContract]</c> interface anywhere in the repository, then
    /// any interface of the name.</summary>
    private static HashSet<string>? ContractOperations(DetectionContext context, string contract)
    {
        bool Named(DeclaredType t) => t.IsInterface && t.Name == contract;
        var declaration = context.Project.Types.Where(Named).FirstOrDefault(IsServiceContract)
                          ?? context.Project.Types.FirstOrDefault(Named)
                          ?? context.Repository.SelectMany(p => p.Types).Where(Named).FirstOrDefault(IsServiceContract)
                          ?? context.Repository.SelectMany(p => p.Types).FirstOrDefault(Named);
        return declaration?.Syntax.Members.OfType<MethodDeclarationSyntax>().Select(m => m.Identifier.Text).ToHashSet(StringComparer.Ordinal);
    }

    private static bool IsServiceContract(DeclaredType type) =>
        type.Syntax.AttributeLists.SelectMany(l => l.Attributes)
            .Any(a => SyntaxHelpers.RightmostTypeName(a.Name) is "ServiceContract" or "ServiceContractAttribute");

    // ---------- HTTP ----------

    /// <summary>A request whose URL is absolute (step 5's request-shaped
    /// HTTP invocation): its verb and path. When the URL is built from the
    /// enclosing method's parameters (a wrapper like <c>HttpGet(uri)</c>),
    /// one operation per caller of the wrapper, with the path that caller passes.</summary>
    public static IReadOnlyList<InvokedOperation> HttpRequest(DetectionContext context, ParsedFile file, InvocationExpressionSyntax request, ExpressionSyntax url)
    {
        var verb = Verb(request);
        var method = request.Ancestors().OfType<MethodDeclarationSyntax>().FirstOrDefault();
        var parameters = method?.ParameterList.Parameters.Select(p => p.Identifier.Text).ToHashSet(StringComparer.Ordinal) ?? [];
        var usesParameter = url.DescendantNodesAndSelf().OfType<IdentifierNameSyntax>().Any(i => parameters.Contains(i.Identifier.Text));

        if (method is not null && usesParameter)
        {
            var callers = CallSiteEvaluator.CallSites(context.Project, method);
            if (callers.Count > 0)
            {
                return callers.Select(c =>
                {
                    var (path, resolution) = RequestPath(context.Resolver.Resolve(url, c.Env));
                    return new InvokedOperation
                    {
                        Verb = verb, Path = path, Member = $"{method.Identifier.Text} → {SyntaxHelpers.InvokedName(request)}",
                        Resolution = verb is null ? Resolutions.Partial : resolution, CallSite = CallSiteOf(c.File, c.Call),
                        Reason = verb is null ? "the HTTP method is not readable from the request" : null,
                    };
                }).ToList();
            }
        }

        var (ownPath, ownResolution) = RequestPath(context.Resolver.Resolve(url, CallSiteEvaluator.Empty));
        return
        [
            new InvokedOperation
            {
                Verb = verb, Path = ownPath, Member = SyntaxHelpers.InvokedName(request) ?? "request",
                Resolution = verb is null ? Resolutions.Partial : ownResolution, CallSite = CallSiteOf(file, request),
                Reason = verb is null ? "the HTTP method is not readable from the request" : null,
            },
        ];
    }

    /// <summary>A client configured with a base address: the relative
    /// requests made through it — on the variable or field it is assigned to,
    /// in a typed client's class, or through <c>CreateClient("name")</c> — each
    /// with the base address's path prefixed.</summary>
    public static IReadOnlyList<InvokedOperation> HttpClientRequests(
        DetectionContext context, ParsedFile file, SyntaxNode site, string? basePath, string? typedClient, string? clientName)
    {
        var requests = new List<(ParsedFile File, InvocationExpressionSyntax Call)>();
        if (typedClient is not null)
        {
            // AddHttpClient<TClient>: the HttpClient injected into TClient.
            foreach (var type in context.Project.Types.Where(t => t.Name == typedClient))
            {
                var fields = HttpClientMembers(type.Syntax);
                requests.AddRange(type.Syntax.DescendantNodes().OfType<InvocationExpressionSyntax>()
                    .Where(i => HttpVerbs.ContainsKey(SyntaxHelpers.InvokedName(i) ?? "") && fields.Contains(ReceiverName(i) ?? ""))
                    .Select(i => (type.File, i)));
            }
        }
        else if (clientName is not null)
        {
            // factory.CreateClient("name"): requests on what it is assigned to.
            foreach (var f in context.SourceFiles)
            {
                foreach (var create in f.Root.DescendantNodes().OfType<InvocationExpressionSyntax>()
                             .Where(i => SyntaxHelpers.InvokedName(i) == "CreateClient"
                                         && context.Symbols.Constant(i.ArgumentList.Arguments.FirstOrDefault()?.Expression) == clientName))
                {
                    if (Holder(create) is { } holder)
                    {
                        requests.AddRange(RequestsOn(holder).Select(i => (f, i)));
                    }
                }
            }
        }
        else if (Holder(site is AssignmentExpressionSyntax { Left: MemberAccessExpressionSyntax baseAddress } ? baseAddress.Expression : site) is { } holder)
        {
            requests.AddRange(RequestsOn(holder).Select(i => (file, i)));
        }

        var operations = requests.Select(r =>
        {
            var argument = r.Call.ArgumentList.Arguments.FirstOrDefault()?.Expression;
            var (path, resolution) = argument is null ? ("", Resolutions.Unresolved) : RequestPath(context.Resolver.Resolve(argument, CallSiteEvaluator.Empty));
            return new InvokedOperation
            {
                Verb = Verb(r.Call), Path = JoinPath(basePath, path), Member = SyntaxHelpers.InvokedName(r.Call) ?? "request",
                Resolution = resolution, CallSite = CallSiteOf(r.File, r.Call),
            };
        }).ToList();
        return operations.Count > 0 ? operations : [Unresolved(file, site, "no request through this client found where it is configured, in a typed client or a named client")];
    }

    private static IEnumerable<InvocationExpressionSyntax> RequestsOn((string Name, SyntaxNode Scope) holder) =>
        holder.Scope.DescendantNodes().OfType<InvocationExpressionSyntax>()
            .Where(i => HttpVerbs.ContainsKey(SyntaxHelpers.InvokedName(i) ?? "") && ReceiverName(i) == holder.Name);

    private static HashSet<string> HttpClientMembers(TypeDeclarationSyntax type)
    {
        var names = type.Members.OfType<FieldDeclarationSyntax>()
            .Where(f => SyntaxHelpers.RightmostTypeName(f.Declaration.Type) == "HttpClient")
            .SelectMany(f => f.Declaration.Variables.Select(v => v.Identifier.Text))
            .Concat(type.Members.OfType<PropertyDeclarationSyntax>().Where(p => SyntaxHelpers.RightmostTypeName(p.Type) == "HttpClient").Select(p => p.Identifier.Text))
            .ToHashSet(StringComparer.Ordinal);
        // A primary-constructor or constructor parameter of type HttpClient used directly.
        foreach (var parameter in type.DescendantNodes().OfType<ParameterSyntax>().Where(p => p.Type is not null && SyntaxHelpers.RightmostTypeName(p.Type) == "HttpClient"))
        {
            names.Add(parameter.Identifier.Text);
        }

        return names;
    }

    private static string? Verb(InvocationExpressionSyntax request)
    {
        var name = SyntaxHelpers.InvokedName(request) ?? "";
        if (HttpVerbs.TryGetValue(name, out var verb))
        {
            // UploadString(url, "PUT", data): an explicit method argument.
            if (name.StartsWith("Upload", StringComparison.Ordinal) && request.ArgumentList.Arguments.Count >= 3
                && request.ArgumentList.Arguments[1].Expression is LiteralExpressionSyntax literal && literal.Token.ValueText is { Length: > 0 } explicitVerb)
            {
                return explicitVerb.ToUpperInvariant();
            }

            return verb;
        }

        return null;   // SendAsync, WebRequest.Create: the method is set elsewhere
    }

    /// <summary>The request's path, holes written <c>{…}</c>: the part after
    /// scheme and host for an absolute URL, the text as written for a
    /// relative one.</summary>
    public static (string Path, string Resolution) RequestPath(ResolvedValue value)
    {
        var text = new StringBuilder();
        var holes = false;
        foreach (var part in value.Parts)
        {
            if (part is TextPart t)
            {
                text.Append(t.Value);
            }
            else
            {
                text.Append("{…}");
                holes = true;
            }
        }

        var written = text.ToString().Trim();
        var scheme = written.IndexOf("://", StringComparison.Ordinal);
        if (scheme >= 0)
        {
            var slash = written.IndexOf('/', scheme + 3);
            written = slash < 0 ? "/" : written[slash..];
        }

        var query = written.IndexOfAny(['?', '#']);
        if (query >= 0)
        {
            written = written[..query];
        }

        if (written.Length == 0)
        {
            return ("", Resolutions.Unresolved);
        }

        return ("/" + written.TrimStart('/'), holes ? Resolutions.Partial : Resolutions.Resolved);
    }

    private static string JoinPath(string? basePath, string path)
    {
        if (string.IsNullOrEmpty(basePath) || basePath == "/")
        {
            return path;
        }

        return basePath.TrimEnd('/') + "/" + path.TrimStart('/');
    }

    // ---------- gRPC ----------

    /// <summary>The methods called on a generated gRPC client
    /// (<c>Greeter.GreeterClient</c>) — the one constructed over the channel
    /// created at <paramref name="site"/>, or for <c>AddGrpcClient&lt;T&gt;</c>
    /// any receiver declared as <c>T</c>. Recorded as the service declares
    /// them: a generated <c>…Async</c> method is the <c>…</c> RPC.</summary>
    public static IReadOnlyList<InvokedOperation> Grpc(DetectionContext context, ParsedFile file, SyntaxNode site, string? contract, bool registration)
    {
        bool IsMethod(string name) => !GrpcInfrastructure.Contains(name);
        var clientType = contract is null ? null : contract + "Client";
        var calls = new List<(ParsedFile File, InvocationExpressionSyntax Call)>();

        if (!registration && Holder(site) is { } channel)
        {
            foreach (var creation in channel.Scope.DescendantNodes().OfType<ObjectCreationExpressionSyntax>()
                         .Where(c => c.ArgumentList?.Arguments.FirstOrDefault()?.Expression is IdentifierNameSyntax a && a.Identifier.Text == channel.Name))
            {
                if (Holder(creation) is { } client)
                {
                    calls.AddRange(client.Scope.DescendantNodes().OfType<InvocationExpressionSyntax>()
                        .Where(i => ReceiverName(i) == client.Name && IsMethod(SyntaxHelpers.InvokedName(i) ?? "")).Select(i => (file, i)));
                }
            }
        }

        if (calls.Count == 0 && clientType is not null)
        {
            calls.AddRange(TypedReceiverCalls(context, [clientType], IsMethod).Select(x => (x.File, x.Call)));
        }

        var operations = calls.Select(c =>
        {
            var name = SyntaxHelpers.InvokedName(c.Call)!;
            return new InvokedOperation
            {
                Operation = name.EndsWith("Async", StringComparison.Ordinal) ? name[..^5] : name, Member = name,
                Resolution = Resolutions.Resolved, CallSite = CallSiteOf(c.File, c.Call),
            };
        }).ToList();
        return operations.Count > 0 ? operations : [Unresolved(file, site, "no method is called on a client of this channel or service")];
    }

    // ---------- shared ----------

    private static InvokedOperation Unresolved(ParsedFile file, SyntaxNode site, string reason) => UnresolvedAt(CallSiteOf(file, site), reason);

    public static InvokedOperation UnresolvedAt(CallSite site, string reason) => new()
    {
        Resolution = Resolutions.Unresolved, Reason = reason, CallSite = site,
    };

    /// <summary>Where a value created at <paramref name="node"/> is kept:
    /// a local (scope: its method) or a field or property (scope: its
    /// class), through <c>await</c>, a cast or <c>using</c>.</summary>
    private static (string Name, SyntaxNode Scope)? Holder(SyntaxNode node)
    {
        var value = node;
        while (value.Parent is AwaitExpressionSyntax or ParenthesizedExpressionSyntax or CastExpressionSyntax or EqualsValueClauseSyntax
               || (value.Parent is BinaryExpressionSyntax binary && binary.IsKind(Microsoft.CodeAnalysis.CSharp.SyntaxKind.AsExpression)))
        {
            if (value.Parent is EqualsValueClauseSyntax { Parent: VariableDeclaratorSyntax declarator })
            {
                var isField = declarator.Ancestors().Any(a => a is FieldDeclarationSyntax);
                var scope = isField ? (SyntaxNode?)declarator.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault() : CallSiteEvaluator.Scope(declarator);
                return scope is null ? null : (declarator.Identifier.Text, scope);
            }

            value = value.Parent;
        }

        if (value.Parent is AssignmentExpressionSyntax assignment && assignment.Right == value)
        {
            var name = assignment.Left switch
            {
                IdentifierNameSyntax identifier => identifier.Identifier.Text,
                MemberAccessExpressionSyntax { Expression: ThisExpressionSyntax } member => member.Name.Identifier.Text,
                _ => null,
            };
            if (name is null)
            {
                return null;
            }

            // A field assigned in a constructor or method: the whole class.
            var type = assignment.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault();
            var local = CallSiteEvaluator.Scope(assignment).DescendantNodes().OfType<VariableDeclaratorSyntax>().Any(v => v.Identifier.Text == name);
            return (name, local ? CallSiteEvaluator.Scope(assignment) : (SyntaxNode?)type ?? CallSiteEvaluator.Scope(assignment));
        }

        // A bare identifier: the base-address assignment's receiver.
        if (node is IdentifierNameSyntax receiver)
        {
            var declaredHere = CallSiteEvaluator.Scope(receiver).DescendantNodes().OfType<VariableDeclaratorSyntax>().Any(v => v.Identifier.Text == receiver.Identifier.Text);
            var scope = declaredHere ? CallSiteEvaluator.Scope(receiver) : (SyntaxNode?)receiver.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault();
            return scope is null ? null : (receiver.Identifier.Text, scope);
        }

        if (node is MemberAccessExpressionSyntax { Expression: ThisExpressionSyntax } thisMember)
        {
            var type = thisMember.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault();
            return type is null ? null : (thisMember.Name.Identifier.Text, type);
        }

        return null;
    }

    /// <summary><c>x.M()</c> or <c>this.x.M()</c> → <c>x</c>.</summary>
    private static string? ReceiverName(InvocationExpressionSyntax invocation) => SyntaxHelpers.Receiver(invocation) switch
    {
        IdentifierNameSyntax identifier => identifier.Identifier.Text,
        MemberAccessExpressionSyntax { Expression: ThisExpressionSyntax } member => member.Name.Identifier.Text,
        _ => null,
    };

    /// <summary>Calls on any receiver declared — as a field, property,
    /// parameter or local — with one of <paramref name="types"/>.</summary>
    private static IEnumerable<(ParsedFile File, InvocationExpressionSyntax Call, string Name, string Type)> TypedReceiverCalls(
        DetectionContext context, IReadOnlyList<string> types, Func<string, bool> include)
    {
        var wanted = types.ToHashSet(StringComparer.Ordinal);
        foreach (var file in context.SourceFiles)
        {
            var declared = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var declaration in file.Root.DescendantNodes().OfType<VariableDeclarationSyntax>())
            {
                if (SyntaxHelpers.RightmostTypeName(declaration.Type) is { } t && wanted.Contains(t))
                {
                    foreach (var variable in declaration.Variables)
                    {
                        declared[variable.Identifier.Text] = t;
                    }
                }
            }

            foreach (var parameter in file.Root.DescendantNodes().OfType<ParameterSyntax>())
            {
                if (parameter.Type is not null && SyntaxHelpers.RightmostTypeName(parameter.Type) is { } t && wanted.Contains(t))
                {
                    declared[parameter.Identifier.Text] = t;
                }
            }

            foreach (var property in file.Root.DescendantNodes().OfType<PropertyDeclarationSyntax>())
            {
                if (SyntaxHelpers.RightmostTypeName(property.Type) is { } t && wanted.Contains(t))
                {
                    declared[property.Identifier.Text] = t;
                }
            }

            if (declared.Count == 0)
            {
                continue;
            }

            foreach (var call in file.Root.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                if (ReceiverName(call) is { } receiver && declared.TryGetValue(receiver, out var type)
                    && SyntaxHelpers.InvokedName(call) is { } name && include(name))
                {
                    yield return (file, call, name, type);
                }
            }
        }
    }
}
