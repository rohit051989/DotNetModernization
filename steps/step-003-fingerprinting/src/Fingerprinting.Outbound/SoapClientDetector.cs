using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using static Fingerprinting.Outbound.DetectionSupport;

namespace Fingerprinting.Outbound;

/// <summary>
/// <c>soap_client</c> — Part C1 and C2. Four sources:
/// <list type="bullet">
/// <item><c>new ChannelFactory&lt;T&gt;(binding, address)</c> and
/// <c>DuplexChannelFactory&lt;T&gt;</c>, including inside a generic helper
/// (<c>CreateTcpFactory&lt;T&gt;(name, port, requireClientCertificate, cert)</c>):
/// each call to the helper is its own client, with the helper's type and
/// value arguments bound — step 4's <see cref="CallSiteEvaluator"/>, the same
/// resolution that handled <c>BuildTcpHost&lt;TService, TContract&gt;</c>.</item>
/// <item><c>new XClient(...)</c> where XClient derives from
/// <c>ClientBase&lt;T&gt;</c>, hand-written or generated.</item>
/// <item><c>&lt;client&gt;&lt;endpoint&gt;</c> in configuration — preferred for the
/// binding whenever a client uses one.</item>
/// <item>a generated <c>Reference.cs</c>'s <c>GetBindingForEndpoint</c> /
/// <c>GetEndpointAddress</c> (dotnet-svcutil) — read for this purpose only.</item>
/// </list>
/// </summary>
public static class SoapClientDetector
{
    private sealed record Found(
        string Contract,
        string ClientType,
        string ClientSource,
        string BindingSource,
        string Binding,
        string? Mode,
        string? TransportCredential,
        string? MessageCredential,
        Endpoint Endpoint,
        IReadOnlyList<EnvironmentBinding> Bindings,
        string? EndpointName,
        string? Condition,
        string? Via,
        IReadOnlyList<CredentialReference> Credentials,
        IReadOnlyList<CallSite> CallSites,
        double Confidence,
        IReadOnlyList<string> Reasons,
        string Usage = Usages.Used)
    {
        /// <summary>What the client invokes (1.2.0), set where the client is found.</summary>
        public IReadOnlyList<InvokedOperation> Operations { get; init; } = [];
    }

    /// <summary>Clients found in code. Run for every project before
    /// <see cref="DetectConfigOnly"/>: a library's client claims its host's
    /// endpoint configuration (1.3.0), so the host must not then report that
    /// entry as configured but never constructed.</summary>
    public static IEnumerable<Detected> Detect(DetectionContext context)
    {
        var found = new List<Found>();
        found.AddRange(ChannelFactories(context, context.ClaimedEndpoints));
        found.AddRange(ClientBaseClients(context, context.ClaimedEndpoints));
        return found.Select(Build).ToList();
    }

    /// <summary>Client endpoints in this project's own configuration that no
    /// client anywhere in the repository claimed.</summary>
    public static IEnumerable<Detected> DetectConfigOnly(DetectionContext context) =>
        ConfigOnly(context, context.ClaimedEndpoints).Select(Build).ToList();

    // ---------- ChannelFactory<T> ----------

    private static IEnumerable<Found> ChannelFactories(DetectionContext context, HashSet<string> claimed)
    {
        foreach (var file in context.SourceFiles)
        {
            foreach (var creation in file.Root.DescendantNodes().OfType<ObjectCreationExpressionSyntax>())
            {
                var factoryType = SyntaxHelpers.RightmostTypeName(creation.Type);
                if (factoryType is not ("ChannelFactory" or "DuplexChannelFactory") || SingleTypeArgument(creation.Type) is not { } contractSyntax)
                {
                    continue;
                }

                var contractName = SyntaxHelpers.RightmostTypeName(contractSyntax) ?? contractSyntax.ToString();
                var scope = CallSiteEvaluator.Scope(creation);
                var method = scope as MethodDeclarationSyntax;
                var typeParameters = method?.TypeParameterList?.Parameters.Select(p => p.Identifier.Text).ToHashSet(StringComparer.Ordinal) ?? [];
                var generic = typeParameters.Contains(contractName);

                var sites = method is not null && (generic || method.ParameterList.Parameters.Count > 0)
                    ? CallSiteEvaluator.CallSites(context.Project, method)
                    : [];
                if (sites.Count == 0)
                {
                    if (generic)
                    {
                        continue;   // a generic helper nobody calls creates nothing
                    }

                    var single = FromChannelFactory(context, claimed, file, creation, scope, factoryType, contractName, file, creation, CallSiteEvaluator.Empty, via: null);
                    yield return single with { Operations = OperationTracer.Soap(context, file, creation, single.Contract, null, isFactory: true) };
                    continue;
                }

                foreach (var (siteFile, call, env) in sites)
                {
                    var found = FromChannelFactory(context, claimed, file, creation, scope, factoryType, contractName, siteFile, call, env,
                        via: $"{method!.Identifier.Text} ({CallSiteEvaluator.Where(file, creation)})");
                    // Each call to the helper is its own client: the operations
                    // are the ones called on what that call returns.
                    yield return found with { Operations = OperationTracer.Soap(context, siteFile, call, found.Contract, null, isFactory: true) };
                }
            }
        }
    }

    private static Found FromChannelFactory(
        DetectionContext context, HashSet<string> claimed, ParsedFile file, ObjectCreationExpressionSyntax creation, SyntaxNode scope,
        string factoryType, string contractName, ParsedFile siteFile, SyntaxNode site, CallSiteEvaluator.Env env, string? via)
    {
        var contract = CallSiteEvaluator.Bound(contractName, env) ?? contractName;
        var arguments = creation.ArgumentList?.Arguments.Select(a => a.Expression).ToList() ?? [];
        if (factoryType == "DuplexChannelFactory" && arguments.Count > 0)
        {
            arguments.RemoveAt(0);   // the callback instance
        }

        var reasons = new List<string>();
        var confidence = via is null ? 1.0 : 0.95;
        if (via is not null)
        {
            reasons.Add("binding and address evaluated at the helper's call site, syntactically");
        }

        CallSiteEvaluator.BindingValue? binding = null;
        string? endpointName = null;
        ExpressionSyntax? address = null;
        if (arguments.Count > 0)
        {
            var evaluated = CallSiteEvaluator.EvaluateBinding(arguments[0], scope, env, depth: 0);
            if (evaluated.Binding != "unknown")
            {
                binding = evaluated;
                address = arguments.ElementAtOrDefault(1);
            }
            else if (context.Resolver.Resolve(arguments[0], env).TextValue is { } name)
            {
                endpointName = name;
                address = arguments.ElementAtOrDefault(1);
            }
            else
            {
                binding = evaluated;
                address = arguments.ElementAtOrDefault(1);
            }
        }

        var credentials = CodeCredentials(file, scope, env, via);
        var condition = ConditionChain(context, site);
        var callSites = new[] { CallSiteOf(siteFile, site) };

        if (binding is null)
        {
            // new ChannelFactory<T>("endpointName") or (): configuration.
            var configured = ConfigEndpointFor(context, contract, endpointName);
            if (configured is not null)
            {
                claimed.Add(ClaimKey(configured));
                return FromConfigEntry(context, configured, contract, factoryType, "hand_written", endpointName, condition, via, credentials, callSites,
                    Math.Min(confidence, 0.95), [.. reasons, "binding from configuration"]);
            }

            return new Found(contract, factoryType, "hand_written", "code", "unknown", null, null, null,
                new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = endpointName is null ? "no binding or endpoint configuration found" : $"endpoint configuration '{endpointName}' not found" },
                [], endpointName, condition, via, credentials, callSites, 0.5, [.. reasons, "no binding found in code or configuration"]);
        }

        var (endpoint, bindings) = AddressOf(context, address, env);
        if (binding.Binding == "unknown")
        {
            confidence -= 0.3;
            reasons.Add("binding could not be evaluated syntactically");
        }

        if (endpoint.Resolution != Resolutions.Resolved)
        {
            confidence -= 0.1;
            reasons.Add($"address {endpoint.Resolution}");
        }

        return new Found(contract, factoryType, "hand_written", "code", binding.Binding, binding.Mode, binding.Transport, binding.Message,
            endpoint, bindings, endpointName, condition, via, credentials, callSites, Math.Round(confidence, 2), reasons);
    }

    private static (Endpoint, IReadOnlyList<EnvironmentBinding>) AddressOf(DetectionContext context, ExpressionSyntax? address, CallSiteEvaluator.Env env)
    {
        if (address is null)
        {
            return (new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = "no address" }, []);
        }

        var (endpoint, bindings, _) = Evaluate(context.Resolver, r => r.Resolve(address, env), Endpoints.FromValue);
        return (endpoint, bindings);
    }

    /// <summary>
    /// Credentials attached to a client in code: <c>Credentials.ClientCertificate</c>,
    /// <c>ClientCredentials.UserName</c>, <c>ClientCredentials.Windows</c>. An
    /// assignment under an <c>if</c> on a bound argument counts only when the
    /// argument makes it true — the per-call certificate switch.
    /// </summary>
    private static IReadOnlyList<CredentialReference> CodeCredentials(ParsedFile file, SyntaxNode scope, CallSiteEvaluator.Env env, string? via)
    {
        var found = new SortedDictionary<string, CredentialReference>(StringComparer.Ordinal);
        foreach (var node in scope.DescendantNodes())
        {
            var text = node switch
            {
                AssignmentExpressionSyntax assignment => assignment.Left.ToString(),
                InvocationExpressionSyntax invocation => invocation.Expression.ToString(),
                _ => null,
            };
            if (text is null)
            {
                continue;
            }

            text = text.Replace(" ", "");
            var kind = text switch
            {
                _ when text.Contains("Credentials.ClientCertificate.", StringComparison.Ordinal) => "certificate",
                _ when text.Contains("Credentials.UserName.", StringComparison.Ordinal) => "password",
                _ when text.Contains("Credentials.Windows.", StringComparison.Ordinal) => "windows",
                _ => null,
            };
            if (kind is null || found.ContainsKey(kind))
            {
                continue;
            }

            var gate = node.Ancestors().TakeWhile(a => a != scope).OfType<IfStatementSyntax>()
                .FirstOrDefault(i => i.Statement.Span.Contains(node.Span));
            if (gate is not null && CallSiteEvaluator.Truth(gate.Condition, env) == false)
            {
                continue;
            }

            var where = CallSiteEvaluator.Where(file, node);
            found[kind] = new CredentialReference { Kind = kind, DeclaredAt = via is null ? where : $"{where} (in {via.Split(' ')[0]})" };
        }

        return found.Values.ToList();
    }

    // ---------- ClientBase<T> ----------

    private sealed record ClientClass(DeclaredType Type, ProjectSource Project, string Contract, bool Generated);

    private static IEnumerable<Found> ClientBaseClients(DetectionContext context, HashSet<string> claimed)
    {
        var classes = context.Repository
            .SelectMany(p => p.Types.Select(t => (Project: p, Type: t)))
            .Select(x => AsClientClass(x.Project, x.Type))
            .OfType<ClientClass>()
            .ToList();
        if (classes.Count == 0)
        {
            yield break;
        }

        var byName = classes.ToLookup(c => c.Type.Name, StringComparer.Ordinal);
        var constructed = new HashSet<ClientClass>();

        foreach (var file in context.SourceFiles)
        {
            foreach (var creation in file.Root.DescendantNodes().OfType<ObjectCreationExpressionSyntax>())
            {
                var name = SyntaxHelpers.RightmostTypeName(creation.Type);
                if (name is null || !byName.Contains(name))
                {
                    continue;
                }

                // Prefer the class declared in this project (legacy and
                // modernised copies of one client often coexist).
                var client = byName[name].FirstOrDefault(c => c.Project == context.Project) ?? byName[name].First();
                constructed.Add(client);
                yield return FromClientBase(context, claimed, client, file, creation) with
                {
                    Operations = OperationTracer.Soap(context, file, creation, client.Contract, client.Type.Name, isFactory: false),
                };
            }
        }

        // A client class declared here and constructed nowhere in the
        // repository is still a client the code carries.
        foreach (var client in classes.Where(c => c.Project == context.Project && !c.Generated))
        {
            if (constructed.Contains(client) || IsConstructedAnywhere(context, client, byName))
            {
                continue;
            }

            var configured = ConfigEndpointFor(context, client.Contract, null);
            var site = CallSiteOf(client.Type.File, client.Type.Syntax.Identifier.Parent!);
            if (configured is not null)
            {
                claimed.Add(ClaimKey(configured));
                yield return FromConfigEntry(context, configured, client.Contract, client.Type.Name, "hand_written", null, null, null, [], [site],
                    0.6, ["ClientBase subclass not constructed anywhere in the repository", "binding from configuration"]) with
                {
                    Operations = [OperationTracer.UnresolvedAt(site, "the client class is never constructed, so no call through it can be followed")],
                };
                continue;
            }

            // Constructed nowhere and configured nowhere: dead code that
            // makes no outbound call. Kept, and marked so it is not counted
            // or registered as a dependency.
            yield return new Found(client.Contract, client.Type.Name, "hand_written", "code", "unknown", null, null, null,
                new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = "no endpoint configuration found" },
                [], null, null, null, [], [site], 0.4,
                ["ClientBase subclass not constructed anywhere in the repository", "no binding in code or configuration"], Usages.Unused);
        }
    }

    /// <summary>Constructed in some project, where a construction resolves
    /// to the same-named class declared in that project first — a
    /// hand-written client and a generated proxy often share a name.</summary>
    private static bool IsConstructedAnywhere(DetectionContext context, ClientClass client, ILookup<string, ClientClass> byName) =>
        context.Repository.Any(project => project.Files.Where(f => !f.IsGenerated)
            .SelectMany(f => f.Root.DescendantNodes().OfType<ObjectCreationExpressionSyntax>())
            .Any(c => SyntaxHelpers.RightmostTypeName(c.Type) == client.Type.Name
                      && (byName[client.Type.Name].FirstOrDefault(x => x.Project == project) ?? byName[client.Type.Name].First()) == client));

    private static ClientClass? AsClientClass(ProjectSource project, DeclaredType type)
    {
        var baseType = type.Syntax.BaseList?.Types.Select(b => b.Type)
            .FirstOrDefault(t => SyntaxHelpers.RightmostTypeName(t) is "ClientBase" or "DuplexClientBase");
        if (baseType is null || SingleTypeArgument(baseType) is not { } contract)
        {
            return null;
        }

        var generated = type.File.IsGenerated || SyntaxHelpers.HasAttribute(type.Syntax.AttributeLists, "GeneratedCode");
        return new ClientClass(type, project, SyntaxHelpers.RightmostTypeName(contract) ?? contract.ToString(), generated);
    }

    private static Found FromClientBase(DetectionContext context, HashSet<string> claimed, ClientClass client, ParsedFile file, ObjectCreationExpressionSyntax creation)
    {
        var clientSource = client.Generated ? "generated" : "hand_written";
        var arguments = creation.ArgumentList?.Arguments.Select(a => a.Expression).ToList() ?? [];
        var condition = ConditionChain(context, creation);
        var callSites = new[] { CallSiteOf(file, creation) };
        var scope = CallSiteEvaluator.Scope(creation);
        var credentials = CodeCredentials(file, scope, CallSiteEvaluator.Empty, null);

        // (binding, address) in code.
        if (arguments.Count >= 2)
        {
            var binding = CallSiteEvaluator.EvaluateBinding(arguments[0], scope, CallSiteEvaluator.Empty, depth: 0);
            if (binding.Binding != "unknown")
            {
                var (endpoint, bindings) = AddressOf(context, arguments[1], CallSiteEvaluator.Empty);
                return new Found(client.Contract, client.Type.Name, clientSource, "code", binding.Binding, binding.Mode, binding.Transport, binding.Message,
                    endpoint, bindings, null, condition, null, credentials, callSites, endpoint.Resolution == Resolutions.Resolved ? 1.0 : 0.9,
                    endpoint.Resolution == Resolutions.Resolved ? [] : [$"address {endpoint.Resolution}"]);
            }
        }

        // An endpoint configuration name, or an svcutil EndpointConfiguration value.
        string? endpointName = null;
        string? generatedMember = null;
        if (arguments.Count >= 1)
        {
            if (arguments[0] is MemberAccessExpressionSyntax { Expression: var owner } member && owner.ToString().EndsWith("EndpointConfiguration", StringComparison.Ordinal))
            {
                generatedMember = member.Name.Identifier.Text;
            }
            else
            {
                endpointName = context.Resolver.Resolve(arguments[0], CallSiteEvaluator.Empty).TextValue;
            }
        }

        if (generatedMember is null)
        {
            var configured = ConfigEndpointFor(context, client.Contract, endpointName);
            if (configured is not null)
            {
                claimed.Add(ClaimKey(configured));
                return FromConfigEntry(context, configured, client.Contract, client.Type.Name, clientSource, endpointName, condition, null, credentials, callSites, 1.0, []);
            }
        }

        if (GeneratedReference(client, generatedMember) is { } generated)
        {
            var (endpoint, bindings) = generated.Address is null
                ? (new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = "no address in the generated reference" }, (IReadOnlyList<EnvironmentBinding>)[])
                : AddressOf(context, generated.Address, CallSiteEvaluator.Empty);
            return new Found(client.Contract, client.Type.Name, clientSource, "generated_reference", generated.Binding.Binding, generated.Binding.Mode,
                generated.Binding.Transport, generated.Binding.Message, endpoint, bindings, generatedMember, condition, null, credentials, callSites, 0.9,
                ["binding read from the generated service reference"]);
        }

        return new Found(client.Contract, client.Type.Name, clientSource, "config", "unknown", null, null, null,
            new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = endpointName is null ? "no endpoint configuration found" : $"endpoint configuration '{endpointName}' not found" },
            [], endpointName, condition, null, credentials, callSites, 0.5, ["no binding found in configuration or a generated reference"]);
    }

    /// <summary>
    /// dotnet-svcutil's generated client: <c>GetBindingForEndpoint</c> builds
    /// the binding in an <c>if</c> per <c>EndpointConfiguration</c> value, and
    /// <c>GetEndpointAddress</c> returns its address. Read only for the
    /// binding, its security and the address — nothing else in generated code
    /// is evidence.
    /// </summary>
    private static (CallSiteEvaluator.BindingValue Binding, ExpressionSyntax? Address)? GeneratedReference(ClientClass client, string? member)
    {
        var methods = client.Type.Syntax.Members.OfType<MethodDeclarationSyntax>().ToList();
        var bindingMethod = methods.FirstOrDefault(m => m.Identifier.Text == "GetBindingForEndpoint");
        if (bindingMethod?.Body is null)
        {
            return null;
        }

        if (member is null)
        {
            // GetDefaultBinding() => GetBindingForEndpoint(EndpointConfiguration.X)
            member = methods.FirstOrDefault(m => m.Identifier.Text == "GetDefaultBinding")?
                .DescendantNodes().OfType<MemberAccessExpressionSyntax>()
                .FirstOrDefault(m => m.Expression.ToString().EndsWith("EndpointConfiguration", StringComparison.Ordinal))?.Name.Identifier.Text;
        }

        var block = Branch(bindingMethod, member);
        var declarator = block?.DescendantNodes().OfType<VariableDeclaratorSyntax>().FirstOrDefault(v => v.Initializer?.Value is BaseObjectCreationExpressionSyntax);
        if (block is null || declarator is null)
        {
            return null;
        }

        var binding = CallSiteEvaluator.EvaluateBinding(declarator.Initializer!.Value, block, CallSiteEvaluator.Empty, depth: 0);
        binding = CallSiteEvaluator.ApplyAssignments(binding, declarator.Identifier.Text, block, CallSiteEvaluator.Empty);

        var addressMethod = methods.FirstOrDefault(m => m.Identifier.Text == "GetEndpointAddress");
        var address = addressMethod is null ? null : Branch(addressMethod, member)?.DescendantNodes().OfType<ReturnStatementSyntax>().FirstOrDefault()?.Expression;
        return (binding, address);
    }

    private static SyntaxNode? Branch(MethodDeclarationSyntax method, string? member) =>
        method.DescendantNodes().OfType<IfStatementSyntax>()
            .FirstOrDefault(i => member is null || i.Condition.ToString().EndsWith("." + member + ")", StringComparison.Ordinal)
                                               || i.Condition.ToString().EndsWith("." + member, StringComparison.Ordinal))?.Statement;

    // ---------- configuration ----------

    private static string ClaimKey(ClientEndpointEntry entry) => $"{entry.Directory}|{entry.Name ?? entry.Contract}";

    /// <summary>The <c>&lt;client&gt;&lt;endpoint&gt;</c> a client uses: by name when
    /// it names one (<c>"*"</c> meaning any), else the one for its contract —
    /// in the project's own configuration, default environment first.</summary>
    private static ClientEndpointEntry? ConfigEndpointFor(DetectionContext context, string contract, string? endpointName)
    {
        // Its own configuration, or for a class library its hosts' (1.3.0);
        // a SetParameters value is never the primary entry.
        var directory = context.Project.ProjectDirectory;
        var governed = context.Config.ClientEndpoints
            .Where(e => context.Config.InScope(directory, e.Directory) && e.Link is null)
            .OrderBy(e => context.Config.ScopeRank(directory, e.Directory))
            .ThenBy(e => e.Environment == "default" ? 0 : 1).ThenBy(e => e.File, StringComparer.Ordinal).ThenBy(e => e.Line)
            .ToList();
        return endpointName is not null and not "*"
            ? governed.FirstOrDefault(e => string.Equals(e.Name, endpointName, StringComparison.Ordinal))
            : governed.FirstOrDefault(e => e.Contract == contract);
    }

    private static Found FromConfigEntry(
        DetectionContext context, ClientEndpointEntry entry, string contract, string clientType, string clientSource, string? endpointName,
        string? condition, string? via, IReadOnlyList<CredentialReference> credentials, IReadOnlyList<CallSite> callSites, double confidence,
        IReadOnlyList<string> reasons)
    {
        // The same endpoint in each environment's file — and each
        // SetParameters file — is one invocation with a binding per
        // environment. For a class library, every host that configures it
        // contributes its own bindings (1.3.0).
        var directory = context.Project.ProjectDirectory;
        var hosted = context.Config.HostFor(directory, entry.Directory) is not null;
        var siblings = context.Config.ClientEndpoints
            .Where(e => (hosted ? context.Config.InScope(directory, e.Directory) : e.Directory == entry.Directory)
                        && (e.Name ?? e.Contract) == (entry.Name ?? entry.Contract))
            .OrderBy(e => context.Config.ScopeRank(directory, e.Directory))
            .ThenBy(e => e.Environment == "default" ? 0 : 1).ThenBy(e => e.Environment, StringComparer.Ordinal).ThenBy(e => e.File, StringComparer.Ordinal)
            .ToList();
        foreach (var sibling in siblings.Where(s => s.Link is null))
        {
            context.ClaimedEndpoints.Add(ClaimKey(sibling));
        }

        var bindings = siblings.Select(e => new EnvironmentBinding
        {
            // 1.4.0: each environment file's own security for this endpoint.
            Soap = EnvironmentSecurity(e),
            Environment = e.Environment,
            SourceFile = e.File,
            KeyPath = e.Endpoint.Source?.KeyPath ?? "system.serviceModel/client/endpoint",
            Scheme = e.Endpoint.Scheme,
            Host = e.Endpoint.Host,
            Port = e.Endpoint.Port,
            Path = e.Endpoint.Path,
            Resolution = e.Endpoint.Resolution,
            Placeholder = e.Endpoint.Placeholder,
            HostProject = context.Config.HostFor(directory, e.Directory),
            DeployParameter = e.Link?.Parameter,
            LinkMethod = e.Link?.Method,
            LinkConfidence = e.Link?.Confidence,
        }).ToList();

        if (hosted)
        {
            var hosts = siblings.Select(s => context.Config.HostFor(directory, s.Directory)).OfType<string>().Distinct().Order(StringComparer.Ordinal);
            reasons = [.. reasons, $"configuration from the host project(s) {string.Join(", ", hosts)}: the class library has none of its own"];
        }

        return new Found(contract, clientType, clientSource, "config", entry.Binding, entry.SecurityMode, entry.TransportCredential, entry.MessageCredential,
            entry.Endpoint, bindings, endpointName ?? entry.Name, condition, via, credentials, callSites, confidence, reasons);
    }

    /// <summary>One configuration entry's effective security: declared, or else the binding's default.</summary>
    private static EnvironmentSoapSecurity EnvironmentSecurity(ClientEndpointEntry entry)
    {
        var security = WcfSecurity.Resolve(entry.Binding, entry.SecurityMode, entry.TransportCredential, entry.MessageCredential);
        return new EnvironmentSoapSecurity
        {
            Binding = entry.Binding,
            SecurityMode = security.SecurityMode,
            ClientCredentialType = security.ClientCredentialType,
            SecuritySource = security.SecuritySource,
        };
    }

    private static IEnumerable<Found> ConfigOnly(DetectionContext context, HashSet<string> claimed)
    {
        var entries = context.Config.ClientEndpoints
            .Where(e => context.Config.Governs(context.Project.ProjectDirectory, e.Directory) && e.Link is null && !claimed.Contains(ClaimKey(e)))
            .OrderBy(e => e.Environment == "default" ? 0 : 1).ThenBy(e => e.File, StringComparer.Ordinal).ThenBy(e => e.Line)
            .ToList();
        foreach (var entry in entries)
        {
            if (!claimed.Add(ClaimKey(entry)))
            {
                continue;
            }

            var at = CallSiteAt(entry.File, entry.Line);
            yield return FromConfigEntry(context, entry, entry.Contract, "config_endpoint", "config_only", entry.Name, null, null, [],
                [at], 0.7, ["declared in configuration; no client construction found in code"]) with
            {
                Operations = [OperationTracer.UnresolvedAt(at, "declared in configuration only; no client construction to follow")],
            };
        }
    }

    // ---------- record ----------

    private static Detected Build(Found found)
    {
        var security = WcfSecurity.Resolve(found.Binding, found.Mode, found.TransportCredential, found.MessageCredential);
        var credentialType = security.ClientCredentialType;
        var authDeclared = credentialType switch
        {
            null => AuthDeclared.NotAssessed,
            _ when credentialType.Contains('|') => AuthDeclared.NotAssessed,
            "None" => AuthDeclared.NoneDeclared,
            _ => AuthDeclared.Declared,
        };

        // The binding asks for a credential the code does not visibly attach:
        // still declared — the binding is the declaration.
        var credentials = found.Credentials.ToList();
        if (credentialType is "Certificate" && credentials.All(c => c.Kind != "certificate"))
        {
            credentials.Add(new CredentialReference { Kind = "certificate", DeclaredAt = "binding clientCredentialType" });
        }
        else if (credentialType is "Windows" or "Ntlm" && credentials.All(c => c.Kind != "windows"))
        {
            credentials.Add(new CredentialReference { Kind = "windows", DeclaredAt = "binding clientCredentialType" });
        }
        else if (credentialType is "UserName" or "Basic" or "Digest" && credentials.All(c => c.Kind != "password"))
        {
            credentials.Add(new CredentialReference { Kind = "password", DeclaredAt = "binding clientCredentialType" });
        }

        var reasons = found.Reasons.ToList();
        if (security.SecuritySource == "binding_default")
        {
            reasons.Add($"security from {found.Binding}'s documented defaults");
        }

        var record = new Invocation
        {
            InvocationId = "",
            Mechanism = Mechanisms.SoapClient,
            ProjectPath = "",
            Endpoint = found.Endpoint,
            Usage = found.Usage,
            // A binding built in code applies in every environment; a
            // configured one already carries its environment's own security.
            EnvironmentBindings = found.Bindings.Select(b => b.Soap is not null ? b : b with
            {
                Soap = new EnvironmentSoapSecurity
                {
                    Binding = found.Binding, SecurityMode = security.SecurityMode,
                    ClientCredentialType = credentialType, SecuritySource = security.SecuritySource,
                },
            }).ToList(),
            AuthDeclared = authDeclared,
            Credentials = credentials.OrderBy(c => c.Kind, StringComparer.Ordinal).ToList(),
            Soap = new SoapDetail
            {
                Contract = found.Contract,
                Binding = found.Binding,
                SecurityMode = security.SecurityMode,
                ClientCredentialType = credentialType,
                SecuritySource = security.SecuritySource,
                BindingSource = found.BindingSource,
                ClientSource = found.ClientSource,
                ClientType = found.ClientType,
                EndpointName = found.EndpointName,
                Condition = found.Condition,
                Via = found.Via,
            },
            CallSites = found.CallSites,
            Operations = found.Operations,
            LinuxCompatibility = Pending,
            Confidence = found.Confidence,
            ConfidenceReasons = reasons,
        };
        return new Detected(record, found.Contract);
    }
}
