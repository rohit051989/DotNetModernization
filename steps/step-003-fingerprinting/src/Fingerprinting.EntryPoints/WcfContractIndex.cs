using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

/// <summary>
/// Every <c>[ServiceContract]</c> in the repository and the classes that
/// implement it. Repository-wide because a contract often lives in one
/// project and its implementation in another. Built once, before any
/// project is detected.
/// </summary>
public sealed class WcfContractIndex
{
    private static readonly IReadOnlySet<string> ClientBases =
        new HashSet<string>(StringComparer.Ordinal) { "ClientBase", "DuplexClientBase" };

    public sealed record Operation(MethodDeclarationSyntax Method, string Name, bool IsOneWay);

    public sealed record Contract(DeclaredType Type, ProjectSource Project, IReadOnlyList<Operation> Operations);

    /// <summary>One way a contract is served: an implementing class, or the
    /// contract alone when nothing in the repository implements it.</summary>
    public sealed record Service(
        Contract Contract,
        ProjectSource Project,
        DeclaredType? Implementation,
        IReadOnlyList<WcfHost> Hosts,
        Confidence Confidence);

    public IReadOnlyList<Service> Services { get; }

    private WcfContractIndex(IReadOnlyList<Service> services)
    {
        Services = services;
    }

    public static WcfContractIndex Empty { get; } = new([]);

    public static WcfContractIndex Build(IReadOnlyList<ProjectSource> projects, RepositoryFiles? repository = null)
    {
        var contracts = new List<Contract>();
        foreach (var project in projects)
        {
            foreach (var type in project.Types.Where(t => SyntaxHelpers.HasAttribute(t.Syntax.AttributeLists, "ServiceContract")))
            {
                var operations = type.Syntax.Members.OfType<MethodDeclarationSyntax>()
                    .Select(m => (Method: m, Attribute: SyntaxHelpers.Attributes(m.AttributeLists).FirstOrDefault(a => a.Name == "OperationContract").Attribute))
                    .Where(x => x.Attribute is not null)
                    .Select(x => new Operation(x.Method, x.Method.Identifier.Text, IsOneWay(x.Attribute!)))
                    .ToList();
                if (operations.Count > 0)
                {
                    contracts.Add(new Contract(type, project, operations));
                }
            }
        }

        var hosting = WcfHostIndex.Build(projects, repository ?? RepositoryFiles.Empty);
        var services = new List<Service>();
        foreach (var contract in contracts)
        {
            // [ServiceContract] on a class: contract and implementation at once.
            if (!contract.Type.IsInterface)
            {
                services.Add(new Service(contract, contract.Project, contract.Type, hosting.HostsOf(contract.Type, contract.Project), new Confidence()));
                continue;
            }

            var implementers = projects
                .SelectMany(p => p.Types.Select(t => (Project: p, Type: t)))
                .Where(x => !x.Type.IsInterface && !x.Type.IsAbstract
                            && x.Type.BaseNames.Contains(contract.Type.Name)
                            && Sees(x.Type, contract.Type))
                .ToList();
            var clients = implementers.Where(x => x.Project.ResolveBase(x.Type, ClientBases) is not null).ToList();
            var candidates = implementers.Except(clients).ToList();

            // An implementation beside its contract is that contract's. Only
            // when there is none does a match in another project count —
            // otherwise two copies of one service (a legacy and a
            // modernised solution in the same repository) each claim the
            // other's implementation.
            var local = candidates.Where(c => c.Project.ProjectPath == contract.Project.ProjectPath).ToList();
            if (local.Count > 0)
            {
                candidates = local;
            }

            if (candidates.Count == 0)
            {
                if (clients.Count > 0)
                {
                    // Only proxies implement it: a client-side contract, an
                    // outbound dependency (step 5), not an entry point.
                    continue;
                }

                services.Add(new Service(contract, contract.Project, null, [], new Confidence().Reduce(0.5,
                    $"no class in the repository implements {contract.Type.Name}; it may be a client-side contract")));
                continue;
            }

            var named = candidates.Select(c => (c.Project, c.Type, Hosts: hosting.HostsOf(c.Type, c.Project))).Where(c => c.Hosts.Count > 0).ToList();
            if (named.Count > 0)
            {
                // A .svc file, ServiceHost or CoreWCF builder names what is
                // served; the other implementations (mocks, test doubles)
                // are not hosted.
                foreach (var (project, type, hosts) in named)
                {
                    services.Add(new Service(contract, project, type, hosts, new Confidence()));
                }

                continue;
            }

            foreach (var (project, type) in candidates)
            {
                var confidence = new Confidence();
                confidence.Reduce(candidates.Count == 1 ? 0.9 : 0.6, candidates.Count == 1
                    ? $"implementation matched to {contract.Type.Name} by interface name; no .svc file, ServiceHost or CoreWCF builder hosts it"
                    : $"one of {candidates.Count} classes implementing {contract.Type.Name}; none is hosted by a .svc file, ServiceHost or CoreWCF builder");
                services.Add(new Service(contract, project, type, [], confidence));
            }
        }

        return new WcfContractIndex(services);
    }

    private static bool IsOneWay(AttributeSyntax attribute) =>
        attribute.ArgumentList?.Arguments.Any(a =>
            a.NameEquals?.Name.Identifier.Text == "IsOneWay" && a.Expression.ToString() == "true") ?? false;

    /// <summary>Whether the implementing file can see the contract's
    /// namespace — same namespace, a nested one, a using, or a qualified
    /// base name. Keeps an unrelated interface that merely shares the name
    /// (a web app's own ICatalogService) from matching.</summary>
    private static bool Sees(DeclaredType implementation, DeclaredType contract)
    {
        var ns = contract.Namespace;
        if (ns is null || implementation.Namespace == ns
            || (implementation.Namespace?.StartsWith(ns + ".", StringComparison.Ordinal) ?? false))
        {
            return true;
        }

        var usings = implementation.File.Root.DescendantNodes().OfType<UsingDirectiveSyntax>().Select(u => u.Name?.ToString());
        if (usings.Contains(ns))
        {
            return true;
        }

        return implementation.Syntax.BaseList?.Types.Any(b => b.Type.ToString() == $"{ns}.{contract.Name}") ?? false;
    }
}
