using System.Xml;
using System.Xml.Linq;

namespace Fingerprinting.EntryPoints;

/// <summary>A web.config or app.config, parsed once. Unparseable XML yields
/// an empty file — config that cannot be read declares nothing, and the
/// entry points it would have governed stay "not assessed".</summary>
public sealed class ConfigFile
{
    public required string RelativePath { get; init; }
    public XDocument? Document { get; init; }

    /// <summary>The directory the file governs, repository-relative, "" for
    /// the root.</summary>
    public string Directory => RelativePath.Contains('/') ? RelativePath[..RelativePath.LastIndexOf('/')] : "";

    public static ConfigFile Parse(string relativePath, string text)
    {
        try
        {
            return new ConfigFile { RelativePath = relativePath, Document = XDocument.Parse(text, LoadOptions.SetLineInfo) };
        }
        catch (XmlException)
        {
            return new ConfigFile { RelativePath = relativePath };
        }
    }

    public static bool IsConfigFileName(string path)
    {
        var name = Path.GetFileName(path);
        return name.Equals("web.config", StringComparison.OrdinalIgnoreCase) || name.Equals("app.config", StringComparison.OrdinalIgnoreCase);
    }

    public string Where(XObject node) => $"{RelativePath}:{((IXmlLineInfo)node).LineNumber}";
}

/// <summary>One <c>&lt;endpoint&gt;</c> of a <c>&lt;service&gt;</c> in
/// <c>&lt;system.serviceModel&gt;</c>, with its binding configuration's
/// security already looked up.</summary>
public sealed record ConfigEndpoint(
    string ServiceName,
    string? Address,
    string Binding,
    string? Contract,
    string? SecurityMode,
    string? TransportClientCredentialType,
    string? MessageClientCredentialType,
    string Where);

/// <summary><c>&lt;system.serviceModel&gt;</c>: services, their endpoints,
/// and the binding configurations endpoints name.</summary>
public static class ServiceModelConfig
{
    public static IReadOnlyList<ConfigEndpoint> Endpoints(ConfigFile file)
    {
        var serviceModel = file.Document?.Root?.Element("system.serviceModel");
        if (serviceModel is null)
        {
            return [];
        }

        var endpoints = new List<ConfigEndpoint>();
        foreach (var service in serviceModel.Element("services")?.Elements("service") ?? [])
        {
            var serviceName = (string?)service.Attribute("name");
            if (serviceName is null)
            {
                continue;
            }

            foreach (var endpoint in service.Elements("endpoint"))
            {
                var binding = (string?)endpoint.Attribute("binding");
                if (binding is null || binding == "mexHttpBinding" || binding == "mexHttpsBinding" || binding == "mexTcpBinding")
                {
                    continue;
                }

                var contract = (string?)endpoint.Attribute("contract");
                if (contract is "IMetadataExchange")
                {
                    continue;
                }

                // A named bindingConfiguration, or the unnamed default binding
                // configuration of that binding type when there is one.
                var configurationName = (string?)endpoint.Attribute("bindingConfiguration") ?? "";
                var bindingElement = serviceModel.Element("bindings")?.Element(binding)?.Elements("binding")
                    .FirstOrDefault(b => ((string?)b.Attribute("name") ?? "") == configurationName);
                var security = bindingElement?.Element("security");

                endpoints.Add(new ConfigEndpoint(
                    serviceName,
                    (string?)endpoint.Attribute("address"),
                    binding,
                    contract,
                    (string?)security?.Attribute("mode"),
                    (string?)security?.Element("transport")?.Attribute("clientCredentialType"),
                    (string?)security?.Element("message")?.Attribute("clientCredentialType"),
                    file.Where(endpoint)));
            }
        }

        return endpoints;
    }
}

/// <summary>
/// ASP.NET <c>&lt;authorization&gt;</c> for a URL path — for ASMX and
/// WebForms. Rules come from <c>&lt;location path&gt;</c> blocks and from
/// web.config files in the path's folders, nearest first, then the root's
/// own <c>&lt;system.web&gt;</c>; the first rule matching an anonymous user
/// decides. When no rule anywhere matches one, machine.config's
/// <c>&lt;allow users="*"&gt;</c> lets them in. When no web.config on the
/// path declares <c>&lt;authorization&gt;</c> at all, nothing is assessed.
/// </summary>
public static class WebAuthorization
{
    public sealed record Result(bool NoneDeclared, string Written);

    /// <param name="configs">The project's web.config files.</param>
    /// <param name="projectDirectory">Repository-relative, "" for the root.</param>
    /// <param name="urlPath">Path within the application, no leading slash:
    /// <c>Catalog/Create.aspx</c>.</param>
    public static Result? Evaluate(IReadOnlyList<ConfigFile> configs, string projectDirectory, string urlPath)
    {
        var rules = new List<(XElement Rule, ConfigFile File)>();

        // Folder web.config files, nearest the page first, each contributing
        // its matching <location> blocks before its own <system.web>.
        var webConfigs = configs
            .Where(c => Path.GetFileName(c.RelativePath).Equals("web.config", StringComparison.OrdinalIgnoreCase))
            .Select(c => (File: c, Folder: Relative(projectDirectory, c.Directory)))
            .Where(c => c.Folder is not null && (c.Folder.Length == 0 || urlPath.StartsWith(c.Folder + "/", StringComparison.OrdinalIgnoreCase)))
            .OrderByDescending(c => c.Folder!.Length)
            .ToList();

        foreach (var (file, folder) in webConfigs)
        {
            var root = file.Document?.Root;
            if (root is null)
            {
                continue;
            }

            var pathInFolder = folder!.Length == 0 ? urlPath : urlPath[(folder.Length + 1)..];
            var locations = root.Elements("location")
                .Select(l => (Element: l, Path: ((string?)l.Attribute("path") ?? "").Trim('/', '~')))
                .Where(l => l.Path.Length == 0 || pathInFolder.Equals(l.Path, StringComparison.OrdinalIgnoreCase)
                            || pathInFolder.StartsWith(l.Path + "/", StringComparison.OrdinalIgnoreCase))
                .OrderByDescending(l => l.Path.Length);
            foreach (var location in locations)
            {
                rules.AddRange(RulesOf(location.Element.Element("system.web")).Select(r => (r, file)));
            }

            rules.AddRange(RulesOf(root.Element("system.web")).Select(r => (r, file)));
        }

        if (rules.Count == 0)
        {
            return null;
        }

        foreach (var (rule, file) in rules)
        {
            var users = ((string?)rule.Attribute("users") ?? "").Split(',', StringSplitOptions.TrimEntries);
            if (users.Contains("?") || users.Contains("*"))
            {
                var written = $"web.config: <{rule.Name.LocalName} users=\"{(string?)rule.Attribute("users")}\" /> at {file.Where(rule)}";
                return new Result(rule.Name.LocalName == "allow", written);
            }
        }

        var first = rules[0];
        return new Result(true,
            $"web.config: <authorization> rules at {first.File.Where(first.Rule)} name no anonymous user; machine.config's allow users=\"*\" applies");
    }

    private static IEnumerable<XElement> RulesOf(XElement? systemWeb) =>
        systemWeb?.Element("authorization")?.Elements().Where(e => e.Name.LocalName is "allow" or "deny") ?? [];

    /// <summary><paramref name="directory"/> relative to the project
    /// directory, or null when it lies outside it.</summary>
    private static string? Relative(string projectDirectory, string directory)
    {
        if (projectDirectory.Length == 0)
        {
            return directory;
        }

        if (directory.Equals(projectDirectory, StringComparison.OrdinalIgnoreCase))
        {
            return "";
        }

        return directory.StartsWith(projectDirectory + "/", StringComparison.OrdinalIgnoreCase)
            ? directory[(projectDirectory.Length + 1)..]
            : null;
    }
}
