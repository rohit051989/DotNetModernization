using System.Xml.Linq;
using NuGet.Common;
using NuGet.Configuration;

namespace Fingerprinting.Dependencies;

/// <summary>One package source NuGet resolves for a project. <see cref="Source"/>
/// is what NuGet connects to and is held in memory only; <see cref="Url"/>
/// is what may be stored.</summary>
public sealed record Feed(string Name, PackageSource Source, string Url, string Role, string DeclaredIn)
{
    public const string RoleClient = "client_feed";
    public const string RoleNuGetOrg = "nuget_org";
    public const string RoleIgnored = "ignored";

    public FeedRecord ToRecord() => new() { Name = Name, Url = Url, Role = Role, DeclaredIn = DeclaredIn };
}

/// <summary>The sources for one project, as the assessment uses them.</summary>
/// <param name="Authorities">Client feeds in declared order, or — when there
/// are none — nuget.org alone, as the fallback.</param>
/// <param name="Public">nuget.org for the comparison of Part B3, when client
/// feeds are the authority and comparison is on; otherwise null.</param>
public sealed record FeedSet(IReadOnlyList<Feed> All, IReadOnlyList<Feed> Authorities, bool UsingClientFeeds, Feed? Public);

/// <summary>
/// Part B2: resolve NuGet.config the way the NuGet client does — the
/// repository's files from the project directory upwards, then the user's,
/// then the machine's, honouring <c>&lt;clear/&gt;</c> and disabled sources —
/// using NuGet's own <see cref="Settings"/> and <see cref="PackageSourceProvider"/>,
/// which also carry <c>packageSourceCredentials</c> and environment-variable
/// credentials into each <see cref="PackageSource"/>, in memory only.
///
/// Which resolved sources are <b>client feeds</b>: any source declared in a
/// NuGet.config inside the repository, and any http(s) feed declared at user
/// or machine level — other than nuget.org itself. A local folder declared
/// only at user or machine level is tooling, not an approved feed (Visual
/// Studio's machine-wide "Microsoft Visual Studio Offline Packages"), and is
/// ignored. When client feeds exist they are the authority and nuget.org is
/// never the answer; when none exist, nuget.org is the fallback.
/// </summary>
public static class FeedResolver
{
    public const string NuGetOrgV3 = "https://api.nuget.org/v3/index.json";

    public static bool IsNuGetOrg(string source)
    {
        if (!Uri.TryCreate(source, UriKind.Absolute, out var uri) || uri.IsFile) return false;
        return uri.Host.Equals("api.nuget.org", StringComparison.OrdinalIgnoreCase)
               || uri.Host.Equals("www.nuget.org", StringComparison.OrdinalIgnoreCase)
               || uri.Host.Equals("nuget.org", StringComparison.OrdinalIgnoreCase);
    }

    /// <param name="publicFeedSource">nuget.org, overridable so tests can stand a local folder in for it.</param>
    public static FeedSet Resolve(string repositoryRoot, string projectDirectory, bool comparePublicFeed, string publicFeedSource = NuGetOrgV3)
    {
        var settings = Settings.LoadDefaultSettings(projectDirectory);
        var provider = new PackageSourceProvider(settings);
        var root = Path.GetFullPath(repositoryRoot).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;

        // Which config file declares each source key: the repository's files
        // decide "client feed" for local folders.
        var configFiles = settings.GetConfigFilePaths().ToList();
        var repositoryKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var machineKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var machineRoot = NuGetEnvironment.GetFolderPath(NuGetFolderPath.MachineWideConfigDirectory);
        foreach (var file in configFiles)
        {
            var keys = DeclaredSourceKeys(file);
            if (Path.GetFullPath(file).StartsWith(root, StringComparison.OrdinalIgnoreCase)) repositoryKeys.UnionWith(keys);
            else if (Path.GetFullPath(file).StartsWith(machineRoot, StringComparison.OrdinalIgnoreCase)) machineKeys.UnionWith(keys);
        }

        var all = new List<Feed>();
        foreach (var source in provider.LoadPackageSources().Where(s => s.IsEnabled))
        {
            var declaredIn = repositoryKeys.Contains(source.Name) ? "repository" : machineKeys.Contains(source.Name) ? "machine" : "user";
            var role = IsNuGetOrg(source.Source)
                ? Feed.RoleNuGetOrg
                : declaredIn == "repository" || source.IsHttp
                    ? Feed.RoleClient
                    : Feed.RoleIgnored;
            all.Add(new Feed(source.Name, source, NormaliseUrl(source.Source, root), role, declaredIn));
        }

        var clients = all.Where(f => f.Role == Feed.RoleClient).ToList();
        if (clients.Count > 0)
        {
            var publicFeed = comparePublicFeed ? NuGetOrg(publicFeedSource, root, "public comparison") : null;
            return new FeedSet(all, clients, UsingClientFeeds: true, publicFeed);
        }

        // No client feed: nuget.org as the fallback — the declared nuget.org
        // source if there is one (it may carry credentials or a proxy), else the default.
        var nugetOrg = all.FirstOrDefault(f => f.Role == Feed.RoleNuGetOrg && publicFeedSource == NuGetOrgV3)
                       ?? NuGetOrg(publicFeedSource, root, "default");
        if (!all.Contains(nugetOrg)) all.Add(nugetOrg);
        return new FeedSet(all, [nugetOrg], UsingClientFeeds: false, Public: null);
    }

    private static Feed NuGetOrg(string source, string root, string declaredIn) =>
        new("nuget.org", new PackageSource(source, "nuget.org"), NormaliseUrl(source, root), Feed.RoleNuGetOrg, declaredIn);

    private static IEnumerable<string> DeclaredSourceKeys(string configFile)
    {
        try
        {
            var document = XDocument.Load(configFile);
            return document.Root?.Element("packageSources")?.Elements("add")
                       .Select(e => (string?)e.Attribute("key"))
                       .OfType<string>()
                       .ToList()
                   ?? [];
        }
        catch (Exception ex) when (ex is IOException or System.Xml.XmlException or UnauthorizedAccessException)
        {
            return [];
        }
    }

    /// <summary>A feed URL as it may be stored: scheme, host, port and path
    /// only — userinfo, query and fragment never kept (Part B4). A local
    /// folder inside the repository is recorded relative to it; one outside
    /// as an absolute path, which names a folder, never a credential.</summary>
    public static string NormaliseUrl(string source, string repositoryRoot)
    {
        if (Uri.TryCreate(source, UriKind.Absolute, out var uri) && !uri.IsFile)
        {
            var port = uri.IsDefaultPort ? "" : $":{uri.Port}";
            return $"{uri.Scheme.ToLowerInvariant()}://{uri.Host.ToLowerInvariant()}{port}{uri.AbsolutePath}";
        }

        var full = Path.GetFullPath(source);
        if (full.StartsWith(repositoryRoot, StringComparison.OrdinalIgnoreCase))
        {
            return "repo:" + full[repositoryRoot.Length..].Replace('\\', '/').TrimEnd('/');
        }

        return "file:" + full.Replace('\\', '/').TrimEnd('/');
    }
}
