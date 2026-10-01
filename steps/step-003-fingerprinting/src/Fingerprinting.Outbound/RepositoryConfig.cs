using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using Fingerprinting.Analysis;

namespace Fingerprinting.Outbound;

/// <summary>One configuration value, with the file, environment and line
/// it came from. <see cref="Value"/> is never populated for a connection
/// string (only <see cref="Facts"/>) or for a sensitive key (only its
/// presence) — Part C5.</summary>
public sealed record ConfigEntry(
    string File,
    string Directory,
    string Environment,
    string KeyPath,
    string Kind,
    string? Value,
    ConnectionFacts? Facts,
    bool Sensitive,
    int Line,
    string? ConfigBuilders = null);

/// <summary>A WCF <c>&lt;client&gt;&lt;endpoint&gt;</c>, with its binding
/// configuration's security looked up and its address already normalised.</summary>
public sealed record ClientEndpointEntry(
    string File,
    string Directory,
    string Environment,
    string? Name,
    string Contract,
    string Binding,
    string? SecurityMode,
    string? TransportCredential,
    string? MessageCredential,
    Endpoint Endpoint,
    int Line);

/// <summary>SMTP from <c>&lt;system.net&gt;&lt;mailSettings&gt;</c> — host, port
/// and whether credentials are configured, never their values.</summary>
public sealed record MailSettingsEntry(string File, string Directory, string Environment, string? Host, int? Port, bool DefaultCredentials, bool HasCredentials, int Line);

/// <summary>A .NET Framework configuration builder that reads Azure Key
/// Vault (<c>&lt;configBuilders&gt;&lt;builders&gt;&lt;add vaultName=…&gt;</c>) — the
/// vault name only, often itself a placeholder.</summary>
public sealed record KeyVaultBuilderEntry(string File, string Directory, string Environment, string Name, string? VaultName, string? Uri, int Line);

/// <summary>
/// Every configuration file in the repository, read once — Part C4.
/// appsettings*.json through step 3's walker (which never materialises a
/// connection string or a sensitive key's value), web.config / app.config and
/// their environment transforms (Web.Release.config). Each file is an
/// environment: appsettings.json and web.config are <c>default</c>;
/// appsettings.Docker.json is <c>Docker</c>; Web.Release.config is <c>Release</c>.
/// </summary>
public sealed partial class RepositoryConfig
{
    [GeneratedRegex(@"^(web|app)(\.(?<env>[^.]+))?\.config$", RegexOptions.IgnoreCase)]
    private static partial Regex XmlConfigName();

    [GeneratedRegex(@"^appsettings(\.(?<env>.+))?\.json$", RegexOptions.IgnoreCase)]
    private static partial Regex AppSettingsName();

    public IReadOnlyList<ConfigEntry> Entries { get; }
    public IReadOnlyList<ClientEndpointEntry> ClientEndpoints { get; }
    public IReadOnlyList<MailSettingsEntry> MailSettings { get; }
    public IReadOnlyList<KeyVaultBuilderEntry> KeyVaultBuilders { get; }

    public RepositoryConfig(
        IReadOnlyList<ConfigEntry> entries, IReadOnlyList<ClientEndpointEntry> clientEndpoints, IReadOnlyList<MailSettingsEntry> mailSettings,
        IReadOnlyList<KeyVaultBuilderEntry>? keyVaultBuilders = null)
    {
        Entries = entries;
        ClientEndpoints = clientEndpoints;
        MailSettings = mailSettings;
        KeyVaultBuilders = keyVaultBuilders ?? [];
    }

    public static RepositoryConfig Empty { get; } = new([], [], []);

    public static RepositoryConfig Build(string repositoryRoot, CancellationToken cancellationToken)
    {
        var files = new List<(string Relative, string Absolute)>();
        foreach (var path in FileSystemWalk.EnumerateFiles(repositoryRoot, cancellationToken))
        {
            var name = Path.GetFileName(path);
            if (AppSettingsName().IsMatch(name) || XmlConfigName().IsMatch(name))
            {
                files.Add((FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, path), path));
            }
        }

        return FromFiles(files.OrderBy(f => f.Relative, StringComparer.Ordinal)
            .Select(f => (f.Relative, (Func<string>)(() => File.ReadAllText(f.Absolute)), (string?)f.Absolute)).ToList());
    }

    /// <summary>For tests: files given as text.</summary>
    public static RepositoryConfig FromText(IReadOnlyList<(string RelativePath, string Text)> files) =>
        FromFiles(files.Select(f => (f.RelativePath, (Func<string>)(() => f.Text), (string?)null)).ToList());

    private static RepositoryConfig FromFiles(IReadOnlyList<(string Relative, Func<string> Read, string? Absolute)> files)
    {
        var entries = new List<ConfigEntry>();
        var clients = new List<ClientEndpointEntry>();
        var mail = new List<MailSettingsEntry>();
        var vaults = new List<KeyVaultBuilderEntry>();

        foreach (var (relative, read, absolute) in files)
        {
            var name = Path.GetFileName(relative);
            var directory = relative.Contains('/') ? relative[..relative.LastIndexOf('/')] : "";
            if (AppSettingsName().Match(name) is { Success: true } json)
            {
                var environment = json.Groups["env"].Success ? json.Groups["env"].Value : "default";
                IReadOnlyList<JsonConfigNode> nodes;
                try
                {
                    nodes = absolute is not null ? JsonConfigWalker.Walk(absolute) : JsonConfigWalker.WalkText(read());
                }
                catch (Exception ex) when (ex is System.Text.Json.JsonException or IOException)
                {
                    continue;
                }

                foreach (var node in nodes)
                {
                    if (node.IsConnectionString)
                    {
                        entries.Add(new ConfigEntry(relative, directory, environment, node.KeyPath, "connection_string", null, node.ConnectionFacts, false, node.Line));
                    }
                    else if (node.IsSensitiveKey)
                    {
                        entries.Add(new ConfigEntry(relative, directory, environment, node.KeyPath, "json", null, null, true, node.Line));
                    }
                    else if (node.StringValue is not null)
                    {
                        entries.Add(new ConfigEntry(relative, directory, environment, node.KeyPath, "json", node.StringValue, null, false, node.Line));
                    }
                }
            }
            else if (XmlConfigName().Match(name) is { Success: true } xml)
            {
                var environment = xml.Groups["env"].Success ? xml.Groups["env"].Value : "default";
                XDocument document;
                try
                {
                    document = XDocument.Parse(read(), LoadOptions.SetLineInfo);
                }
                catch (XmlException)
                {
                    continue;
                }

                ReadXml(document, relative, directory, environment, entries, clients, mail, vaults);
            }
        }

        return new RepositoryConfig(entries, clients, mail, vaults);
    }

    private static int Line(XObject node) => ((IXmlLineInfo)node).LineNumber;

    private static void ReadXml(
        XDocument document, string file, string directory, string environment,
        List<ConfigEntry> entries, List<ClientEndpointEntry> clients, List<MailSettingsEntry> mail, List<KeyVaultBuilderEntry> vaults)
    {
        var root = document.Root;
        if (root is null)
        {
            return;
        }

        foreach (var builder in root.Element("configBuilders")?.Element("builders")?.Elements("add") ?? [])
        {
            var type = (string?)builder.Attribute("type") ?? "";
            if (type.Contains("KeyVault", StringComparison.OrdinalIgnoreCase))
            {
                vaults.Add(new KeyVaultBuilderEntry(file, directory, environment, (string?)builder.Attribute("name") ?? "",
                    (string?)builder.Attribute("vaultName"), (string?)builder.Attribute("uri"), Line(builder)));
            }
        }

        foreach (var add in root.Element("appSettings")?.Elements("add") ?? [])
        {
            var key = (string?)add.Attribute("key");
            if (key is null)
            {
                continue;
            }

            var sensitive = Secrets.IsSensitiveKey(key);
            var value = sensitive ? null : (string?)add.Attribute("value");
            // An appSettings value shaped like a connection string is kept
            // as facts only, like a connection string.
            if (value is not null && Secrets.LooksLikeConnectionString(value))
            {
                entries.Add(new ConfigEntry(file, directory, environment, key, "app_setting", null, Secrets.ReadConnectionFacts(value), false, Line(add)));
                continue;
            }

            entries.Add(new ConfigEntry(file, directory, environment, key, "app_setting", value, null, sensitive, Line(add)));
        }

        var connectionBuilders = (string?)root.Element("connectionStrings")?.Attribute("configBuilders");
        foreach (var add in root.Element("connectionStrings")?.Elements("add") ?? [])
        {
            var name = (string?)add.Attribute("name");
            var connectionString = (string?)add.Attribute("connectionString");
            if (name is null || connectionString is null)
            {
                continue;
            }

            entries.Add(new ConfigEntry(file, directory, environment, $"ConnectionStrings:{name}", "connection_string", null,
                Secrets.ReadConnectionFacts(connectionString, (string?)add.Attribute("providerName")), false, Line(add), connectionBuilders));
        }

        var serviceModel = root.Element("system.serviceModel");
        foreach (var endpoint in serviceModel?.Element("client")?.Elements("endpoint") ?? [])
        {
            var binding = (string?)endpoint.Attribute("binding");
            var contract = (string?)endpoint.Attribute("contract");
            if (binding is null || contract is null || contract == "IMetadataExchange")
            {
                continue;
            }

            var configurationName = (string?)endpoint.Attribute("bindingConfiguration") ?? "";
            var security = serviceModel!.Element("bindings")?.Element(binding)?.Elements("binding")
                .FirstOrDefault(b => ((string?)b.Attribute("name") ?? "") == configurationName)?.Element("security");
            var address = (string?)endpoint.Attribute("address") ?? "";
            var normalised = Endpoints.FromUrl(address) ?? new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = address.Length == 0 ? "no address" : null };
            clients.Add(new ClientEndpointEntry(file, directory, environment, (string?)endpoint.Attribute("name"), contract.Split('.')[^1], binding,
                (string?)security?.Attribute("mode"),
                (string?)security?.Element("transport")?.Attribute("clientCredentialType"),
                (string?)security?.Element("message")?.Attribute("clientCredentialType"),
                normalised with { Source = new ConfigSource { SourceFile = file, KeyPath = $"system.serviceModel/client/endpoint[{(string?)endpoint.Attribute("name") ?? contract}]" } },
                Line(endpoint)));
        }

        var smtp = root.Element("system.net")?.Element("mailSettings")?.Element("smtp");
        var network = smtp?.Element("network");
        if (network is not null)
        {
            mail.Add(new MailSettingsEntry(file, directory, environment,
                ((string?)network.Attribute("host"))?.ToLowerInvariant(),
                int.TryParse((string?)network.Attribute("port"), out var port) ? port : null,
                string.Equals((string?)network.Attribute("defaultCredentials"), "true", StringComparison.OrdinalIgnoreCase),
                network.Attribute("userName") is not null || network.Attribute("password") is not null,
                Line(network)));
        }
    }

    /// <summary>The configuration an application in
    /// <paramref name="projectDirectory"/> loads: files in that directory and
    /// in its wwwroot (Blazor WebAssembly), not those of nested folders such
    /// as Views/web.config.</summary>
    public bool Governs(string projectDirectory, string directory) =>
        directory.Equals(projectDirectory, StringComparison.OrdinalIgnoreCase)
        || directory.Equals(projectDirectory.Length == 0 ? "wwwroot" : projectDirectory + "/wwwroot", StringComparison.OrdinalIgnoreCase);

    /// <summary>Every environment's entry for a key in a project's
    /// configuration. .NET configuration keys are case-insensitive.</summary>
    public IReadOnlyList<ConfigEntry> Lookup(string projectDirectory, ConfigKey key) =>
        Entries
            .Where(e => Governs(projectDirectory, e.Directory)
                        && e.KeyPath.Equals(key.KeyPath, StringComparison.OrdinalIgnoreCase)
                        && KindMatches(e.Kind, key.Kind))
            .OrderBy(e => e.Environment == "default" ? 0 : 1)
            .ThenBy(e => e.Environment, StringComparer.Ordinal)
            .ThenBy(e => e.File, StringComparer.Ordinal)
            .ToList();

    /// <summary>
    /// The entry that supplies <paramref name="key"/> in
    /// <paramref name="environment"/>: that environment's file if it sets
    /// the key, else the default file — how appsettings.{Environment}.json
    /// and a Web.{Configuration}.config transform layer over their base.
    /// </summary>
    public ConfigEntry? Effective(string projectDirectory, ConfigKey key, string environment)
    {
        var entries = Lookup(projectDirectory, key);
        return entries.FirstOrDefault(e => e.Environment == environment) ?? entries.FirstOrDefault(e => e.Environment == "default");
    }

    /// <summary>The environments whose files set any of <paramref name="keys"/>.</summary>
    public IReadOnlyList<string> EnvironmentsFor(string projectDirectory, IEnumerable<ConfigKey> keys) =>
        keys.SelectMany(k => Lookup(projectDirectory, k)).Select(e => e.Environment)
            .Distinct(StringComparer.Ordinal)
            .OrderBy(e => e == "default" ? 0 : 1).ThenBy(e => e, StringComparer.Ordinal)
            .ToList();

    private static bool KindMatches(string entryKind, string keyKind) => keyKind switch
    {
        "connection_string" => entryKind == "connection_string",
        "app_setting" => entryKind == "app_setting",
        _ => entryKind is "json" or "connection_string",
    };

    /// <summary>Sensitive keys beside <paramref name="keyPath"/> — in the
    /// same section — for Part C5's "record that one is configured and its
    /// key path".</summary>
    public IReadOnlyList<ConfigEntry> SensitiveSiblings(string projectDirectory, string keyPath)
    {
        var colon = keyPath.LastIndexOf(':');
        if (colon <= 0)
        {
            return [];
        }

        var section = keyPath[..(colon + 1)];
        return Entries
            .Where(e => e.Sensitive && Governs(projectDirectory, e.Directory)
                        && e.KeyPath.StartsWith(section, StringComparison.OrdinalIgnoreCase)
                        && e.KeyPath.IndexOf(':', section.Length) < 0)
            .GroupBy(e => e.KeyPath, StringComparer.OrdinalIgnoreCase)
            .Select(g => g.First())
            .ToList();
    }
}
