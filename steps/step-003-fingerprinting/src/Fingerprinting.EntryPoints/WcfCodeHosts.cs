using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

/// <summary>An endpoint as the code or config builds it, before the
/// binding's defaults are applied.</summary>
public sealed record WcfEndpointSource(
    string? Contract,
    string Binding,
    string? SecurityMode,
    string? TransportClientCredentialType,
    string? MessageClientCredentialType,
    string? Address,
    string Source,
    string Where,
    string? Condition);

/// <summary>One place a service class is hosted: a .svc file, a
/// <c>ServiceHost</c> in code, or a CoreWCF service builder.</summary>
public sealed record WcfHost(string Kind, string ServiceType, string? ServiceNamespace, string Where, IReadOnlyList<WcfEndpointSource> Endpoints);

/// <summary>
/// Self-hosting written in code — classic <c>new ServiceHost(typeof(X))</c>
/// with <c>AddServiceEndpoint(typeof(C), binding, address)</c>, and CoreWCF's
/// <c>AddServiceEndpoint&lt;TService, TContract&gt;(binding, address)</c>. Syntax
/// only, but a generic hosting helper — <c>BuildHost&lt;TService, TContract&gt;(...)</c>
/// with <c>typeof(TService)</c> inside — is followed to its call sites, where
/// the type arguments and literal arguments are bound, so each call yields
/// its own host with the service, contract and credential type it passes.
/// </summary>
public static class WcfCodeHosts
{
    public static IReadOnlyList<WcfHost> Read(ProjectSource project)
    {
        var hosts = new List<WcfHost>();
        foreach (var file in project.Files)
        {
            foreach (var node in file.Root.DescendantNodes())
            {
                if (node is ObjectCreationExpressionSyntax creation && SyntaxHelpers.RightmostTypeName(creation.Type) == "ServiceHost")
                {
                    hosts.AddRange(ClassicHosts(project, file, creation));
                }
                else if (node is InvocationExpressionSyntax { Expression: MemberAccessExpressionSyntax { Name: GenericNameSyntax { Identifier.Text: "AddServiceEndpoint" } generic } } invocation
                         && generic.TypeArgumentList.Arguments.Count == 2)
                {
                    hosts.Add(CoreWcfHost(project, file, invocation, generic));
                }
            }
        }

        return hosts;
    }

    // ---------- classic System.ServiceModel ----------

    private static IEnumerable<WcfHost> ClassicHosts(ProjectSource project, ParsedFile file, ObjectCreationExpressionSyntax creation)
    {
        var serviceArgument = creation.ArgumentList?.Arguments.FirstOrDefault()?.Expression;
        var serviceTypeSyntax = serviceArgument switch
        {
            TypeOfExpressionSyntax typeOf => typeOf.Type,
            ObjectCreationExpressionSyntax singleton => singleton.Type,
            _ => null,
        };
        if (serviceTypeSyntax is null)
        {
            yield break;
        }

        var scope = CallSiteEvaluator.Scope(creation);
        var method = scope as MethodDeclarationSyntax;
        var typeParameters = method?.TypeParameterList?.Parameters.Select(p => p.Identifier.Text).ToHashSet(StringComparer.Ordinal) ?? [];
        var endpoints = scope.DescendantNodes().OfType<InvocationExpressionSyntax>()
            .Where(i => SyntaxHelpers.InvokedName(i) == "AddServiceEndpoint" && i.ArgumentList.Arguments.Count >= 2)
            .ToList();
        var serviceName = SyntaxHelpers.RightmostTypeName(serviceTypeSyntax) ?? serviceTypeSyntax.ToString();

        var needsCallSites = method is not null && (typeParameters.Contains(serviceName)
                                                    || method.ParameterList.Parameters.Count > 0 && endpoints.Count > 0);
        var callSites = needsCallSites ? CallSiteEvaluator.CallSites(project, method!) : [];

        if (callSites.Count == 0)
        {
            if (typeParameters.Contains(serviceName))
            {
                // A generic helper nobody calls: nothing is hosted.
                yield break;
            }

            yield return new WcfHost("service_host", serviceName, null, CallSiteEvaluator.Where(file, creation),
                endpoints.Select(e => ClassicEndpoint(file, e, scope, CallSiteEvaluator.Empty, CallSiteEvaluator.Condition(creation))).ToList());
            yield break;
        }

        foreach (var (callFile, call, env) in callSites)
        {
            var service = env.TypeArguments.GetValueOrDefault(serviceName) ?? serviceName;
            yield return new WcfHost("service_host", service, null, $"{CallSiteEvaluator.Where(callFile, call)} via {method!.Identifier.Text}",
                endpoints.Select(e => ClassicEndpoint(file, e, scope, env, CallSiteEvaluator.Condition(call))).ToList());
        }
    }

    private static WcfEndpointSource ClassicEndpoint(ParsedFile file, InvocationExpressionSyntax invocation, SyntaxNode scope, CallSiteEvaluator.Env env, string? condition)
    {
        var arguments = invocation.ArgumentList.Arguments;
        var contract = arguments[0].Expression switch
        {
            TypeOfExpressionSyntax typeOf => CallSiteEvaluator.Bound(SyntaxHelpers.RightmostTypeName(typeOf.Type), env),
            var other => SyntaxHelpers.StringValue(other) ?? SyntaxHelpers.Collapse(other.ToString()),
        };
        var binding = CallSiteEvaluator.EvaluateBinding(arguments[1].Expression, scope, env, depth: 0);
        var address = arguments.Count > 2 ? CallSiteEvaluator.EvaluateAddress(arguments[2].Expression, scope, env) : null;
        return new WcfEndpointSource(contract, binding.Binding, binding.Mode, binding.Transport, binding.Message, address, "code",
            env.Via is null ? CallSiteEvaluator.Where(file, invocation) : $"{CallSiteEvaluator.Where(file, invocation)} via {env.Via}", condition);
    }

    // ---------- CoreWCF ----------

    private static WcfHost CoreWcfHost(ProjectSource project, ParsedFile file, InvocationExpressionSyntax invocation, GenericNameSyntax generic)
    {
        var service = SyntaxHelpers.RightmostTypeName(generic.TypeArgumentList.Arguments[0]) ?? generic.TypeArgumentList.Arguments[0].ToString();
        var contract = SyntaxHelpers.RightmostTypeName(generic.TypeArgumentList.Arguments[1]);
        var scope = CallSiteEvaluator.Scope(invocation);
        var arguments = invocation.ArgumentList.Arguments;
        var binding = arguments.Count > 0 ? CallSiteEvaluator.EvaluateBinding(arguments[0].Expression, scope, CallSiteEvaluator.Empty, depth: 0) : new CallSiteEvaluator.BindingValue("unknown", null, null, null);
        var address = arguments.Count > 1 ? CallSiteEvaluator.EvaluateAddress(arguments[1].Expression, scope, CallSiteEvaluator.Empty) : null;
        var endpoint = new WcfEndpointSource(contract, binding.Binding, binding.Mode, binding.Transport, binding.Message, address, "code",
            CallSiteEvaluator.Where(file, invocation), CallSiteEvaluator.Condition(invocation));
        return new WcfHost("corewcf", service, null, CallSiteEvaluator.Where(file, invocation), [endpoint]);
    }
}
