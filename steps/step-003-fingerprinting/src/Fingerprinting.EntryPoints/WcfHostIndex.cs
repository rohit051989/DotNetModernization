using System.Text.RegularExpressions;

namespace Fingerprinting.EntryPoints;

/// <summary>A repository's .svc and config files — read once for the whole
/// repository, since an IIS hosting folder is often no project at all (a
/// folder of .svc files and a Web.config).</summary>
public sealed record RepositoryFiles(IReadOnlyList<(string RelativePath, string Text)> SvcFiles, IReadOnlyList<ConfigFile> Configs)
{
    public static RepositoryFiles Empty { get; } = new([], []);
}

/// <summary>
/// Every place each service class is hosted, with its endpoints:
/// <list type="bullet">
/// <item>.svc files, anywhere in the repository, with the endpoints the
/// web.config in the same folder declares for the service;</item>
/// <item><c>ServiceHost</c> and CoreWCF hosting in code (<see cref="WcfCodeHosts"/>),
/// plus the endpoints the hosting project's app.config or web.config declares
/// for the service — a ServiceHost with no AddServiceEndpoint takes its
/// endpoints from there.</item>
/// </list>
/// </summary>
public sealed partial class WcfHostIndex
{
    [GeneratedRegex(@"Service\s*=\s*""([^""]+)""", RegexOptions.IgnoreCase)]
    private static partial Regex SvcServiceAttribute();

    private readonly List<WcfHost> _hosts;

    private WcfHostIndex(List<WcfHost> hosts)
    {
        _hosts = hosts;
    }

    public static WcfHostIndex Build(IReadOnlyList<ProjectSource> projects, RepositoryFiles repository)
    {
        var hosts = new List<WcfHost>();

        foreach (var (path, text) in repository.SvcFiles)
        {
            var match = SvcServiceAttribute().Match(text);
            if (!match.Success)
            {
                continue;
            }

            var fullName = match.Groups[1].Value.Trim();
            var directory = path.Contains('/') ? path[..path.LastIndexOf('/')] : "";
            var config = repository.Configs.FirstOrDefault(c =>
                c.Directory.Equals(directory, StringComparison.OrdinalIgnoreCase)
                && Path.GetFileName(c.RelativePath).Equals("web.config", StringComparison.OrdinalIgnoreCase));
            var endpoints = config is null ? [] : FromConfig(config, fullName);
            var (ns, name) = Split(fullName);
            hosts.Add(new WcfHost("svc", name, ns, $"{path}:1", endpoints));
        }

        foreach (var project in projects)
        {
            var projectConfigs = repository.Configs
                .Where(c => c.Directory.Equals(project.ProjectDirectory, StringComparison.OrdinalIgnoreCase))
                .ToList();
            foreach (var host in WcfCodeHosts.Read(project))
            {
                // Declarative endpoints for a code-created host.
                var configured = projectConfigs
                    .SelectMany(c => ServiceModelConfig.Endpoints(c)
                        .Where(e => Split(e.ServiceName).Name == host.ServiceType)
                        .Select(e => ToSource(e)))
                    .ToList();
                hosts.Add(host with { Endpoints = host.Endpoints.Concat(configured).ToList() });
            }
        }

        return new WcfHostIndex(hosts);
    }

    public static WcfHostIndex Empty { get; } = new([]);

    /// <summary>Hosts of <paramref name="implementation"/>, declared in
    /// <paramref name="project"/>. A code host names the class as written
    /// (simple name); a .svc names it in full, so its namespace must match
    /// too. Hosts inside the implementation's own project win: two copies of
    /// one service in a repository (a legacy and a modernised solution)
    /// share a full name, and would otherwise each claim the other's .svc.
    /// Hosts elsewhere — a separate host project, an IIS folder that is no
    /// project — count only when none are local.</summary>
    public IReadOnlyList<WcfHost> HostsOf(DeclaredType implementation, ProjectSource project)
    {
        var matching = _hosts
            .Where(h => h.ServiceType == implementation.Name && (h.ServiceNamespace is null || h.ServiceNamespace == implementation.Namespace))
            .ToList();
        var local = matching
            .Where(h => project.ProjectDirectory.Length == 0 || h.Where.StartsWith(project.ProjectDirectory + "/", StringComparison.OrdinalIgnoreCase))
            .ToList();
        return local.Count > 0 ? local : matching;
    }

    private static IReadOnlyList<WcfEndpointSource> FromConfig(ConfigFile config, string serviceFullName) =>
        ServiceModelConfig.Endpoints(config)
            .Where(e => e.ServiceName == serviceFullName)
            .Select(ToSource)
            .ToList();

    private static WcfEndpointSource ToSource(ConfigEndpoint e) =>
        new(e.Contract is null ? null : Split(e.Contract).Name, e.Binding, e.SecurityMode, e.TransportClientCredentialType,
            e.MessageClientCredentialType, e.Address, "config", e.Where, null);

    private static (string? Namespace, string Name) Split(string fullName)
    {
        var dot = fullName.LastIndexOf('.');
        return dot < 0 ? (null, fullName) : (fullName[..dot], fullName[(dot + 1)..]);
    }
}
