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
    string? ConfigBuilders = null)
{
    /// <summary>Set when the value comes from a SetParameters file (1.3.0):
    /// the parameter, and how it was linked to this key.</summary>
    public DeployLink? Link { get; init; }
}

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
    int Line)
{
    /// <summary>Set when the address comes from a SetParameters file (1.3.0).</summary>
    public DeployLink? Link { get; init; }
}

/// <summary>How a SetParameters value was tied to a configuration value:
/// <c>parameters_xml</c> (the repository's parameters.xml declares the XPath
/// it replaces — exact) or <c>name_and_path</c> (the parameter's name and the
/// URL's path match the endpoint — lower confidence).</summary>
public sealed record DeployLink(string Parameter, string Method, double Confidence);

/// <summary>A host a class library runs in: an executable or web project
/// that references it (directly or through other libraries). The library has
/// no configuration of its own; at run time it reads its host's.</summary>
public sealed record HostRef(string ProjectPath, string Directory);

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

    /// <summary>Directories holding a configuration file, whether or not it
    /// set anything: a project with one has configuration of its own.</summary>
    public IReadOnlySet<string> ConfigDirectories { get; }

    /// <summary>By project directory: the hosts of a class library with no
    /// configuration of its own (1.3.0). Empty for every other project.</summary>
    public IReadOnlyDictionary<string, IReadOnlyList<HostRef>> Hosts { get; private init; } =
        new Dictionary<string, IReadOnlyList<HostRef>>(StringComparer.OrdinalIgnoreCase);

    /// <summary>Every SetParameters parameter read (1.3.0), with how it was
    /// linked — never a value: see <see cref="DeployParameterFiles.MayStore"/>.</summary>
    public IReadOnlyList<DeployParameterRecord> DeployParameters { get; private init; } = [];

    public RepositoryConfig(
        IReadOnlyList<ConfigEntry> entries, IReadOnlyList<ClientEndpointEntry> clientEndpoints, IReadOnlyList<MailSettingsEntry> mailSettings,
        IReadOnlyList<KeyVaultBuilderEntry>? keyVaultBuilders = null, IReadOnlySet<string>? configDirectories = null)
    {
        Entries = entries;
        ClientEndpoints = clientEndpoints;
        MailSettings = mailSettings;
        KeyVaultBuilders = keyVaultBuilders ?? [];
        ConfigDirectories = configDirectories ?? new HashSet<string>(StringComparer.OrdinalIgnoreCase);
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

    /// <summary>This configuration with each class library's hosts recorded.</summary>
    public RepositoryConfig WithHosts(IReadOnlyDictionary<string, IReadOnlyList<HostRef>> hosts) =>
        new(Entries, ClientEndpoints, MailSettings, KeyVaultBuilders, ConfigDirectories) { Hosts = hosts, DeployParameters = DeployParameters };

    /// <summary>For tests: files given as text.</summary>
    public static RepositoryConfig FromText(IReadOnlyList<(string RelativePath, string Text)> files) =>
        FromFiles(files.Select(f => (f.RelativePath, (Func<string>)(() => f.Text), (string?)null)).ToList());

    private static RepositoryConfig FromFiles(IReadOnlyList<(string Relative, Func<string> Read, string? Absolute)> files)
    {
        var entries = new List<ConfigEntry>();
        var clients = new List<ClientEndpointEntry>();
        var mail = new List<MailSettingsEntry>();
        var vaults = new List<KeyVaultBuilderEntry>();
        var directories = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var (relative, read, absolute) in files)
        {
            var name = Path.GetFileName(relative);
            var directory = relative.Contains('/') ? relative[..relative.LastIndexOf('/')] : "";
            directories.Add(directory);
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

        return new RepositoryConfig(entries, clients, mail, vaults, directories);
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

    /// <summary>The configuration a project reads at run time: its own, or —
    /// for a class library with none — its hosts' (1.3.0). Used where a value
    /// is read by key or a client endpoint by name; not for the
    /// "configured but never referenced" sweeps, which stay per project.</summary>
    public bool InScope(string projectDirectory, string directory) =>
        Governs(projectDirectory, directory)
        || (Hosts.TryGetValue(projectDirectory, out var hosts) && hosts.Any(h => Governs(h.Directory, directory)));

    /// <summary>The host project whose configuration
    /// <paramref name="directory"/> is, for a library; null for the
    /// project's own configuration.</summary>
    public string? HostFor(string projectDirectory, string directory) =>
        Governs(projectDirectory, directory) || !Hosts.TryGetValue(projectDirectory, out var hosts)
            ? null
            : hosts.FirstOrDefault(h => Governs(h.Directory, directory))?.ProjectPath;

    /// <summary>Own configuration first, then the hosts in order.</summary>
    public int ScopeRank(string projectDirectory, string directory)
    {
        if (Governs(projectDirectory, directory) || !Hosts.TryGetValue(projectDirectory, out var hosts))
        {
            return 0;
        }

        var index = hosts.ToList().FindIndex(h => Governs(h.Directory, directory));
        return index < 0 ? int.MaxValue : index + 1;
    }

    /// <summary>The entry a value came from, by file and key — for the host
    /// and SetParameters link a binding carries.</summary>
    public ConfigEntry? EntryFor(string file, string keyPath) =>
        Entries.FirstOrDefault(e => e.File == file && e.KeyPath.Equals(keyPath, StringComparison.OrdinalIgnoreCase));

    /// <summary>Every environment's entry for a key in a project's
    /// configuration. .NET configuration keys are case-insensitive.</summary>
    public IReadOnlyList<ConfigEntry> Lookup(string projectDirectory, ConfigKey key) =>
        Entries
            .Where(e => InScope(projectDirectory, e.Directory)
                        && e.KeyPath.Equals(key.KeyPath, StringComparison.OrdinalIgnoreCase)
                        && KindMatches(e.Kind, key.Kind))
            .OrderBy(e => ScopeRank(projectDirectory, e.Directory))
            .ThenBy(e => e.Environment == "default" ? 0 : 1)
            .ThenBy(e => e.Environment, StringComparer.Ordinal)
            .ThenBy(e => e.File, StringComparer.Ordinal)
            .ToList();

    // ---------- SetParameters (1.3.0) ----------

    /// <summary>
    /// This configuration with every SetParameters file applied: each
    /// parameter linked to a configuration value becomes that value in the
    /// file's environment — a client endpoint's address, an appSettings key, a
    /// connection string — so it is evaluated like any environment file.
    /// <paramref name="declarations"/> is each project directory's
    /// parameters.xml text. Linking: the declaration's XPath when there is one
    /// (exact); otherwise a URL parameter whose name and path match one client
    /// endpoint, or whose name is an appSettings key (lower confidence).
    /// </summary>
    public RepositoryConfig WithDeployParameters(
        IReadOnlyList<DeployParameterFile> files, IReadOnlyDictionary<string, string> declarations)
    {
        var entries = Entries.ToList();
        var clients = ClientEndpoints.ToList();
        var records = new List<DeployParameterRecord>();

        foreach (var file in files)
        {
            var directory = file.ProjectPath is null ? null : (file.ProjectPath.Contains('/') ? file.ProjectPath[..file.ProjectPath.LastIndexOf('/')] : "");
            var declared = directory is not null && declarations.TryGetValue(directory, out var text)
                ? DeployParameterFiles.Declarations(text)
                : new Dictionary<string, DeployParameterTarget>();

            foreach (var parameter in file.Parameters)
            {
                var kind = DeployParameterFiles.Classify(parameter);
                var record = new DeployParameterRecord
                {
                    ProjectPath = file.ProjectPath, SourceFile = file.RelativePath, Environment = file.Environment,
                    Name = parameter.Name, Kind = kind, Line = parameter.Line,
                };

                if (directory is not null)
                {
                    record = declared.TryGetValue(parameter.Name, out var target)
                        ? Declared(record, parameter, kind, target, directory, file, entries, clients)
                        : Inferred(record, parameter, kind, directory, file, entries, clients);
                }

                // Paths are kept; a URL only once something proves it is used.
                records.Add(record with { Value = kind == "path" ? parameter.RawValue : null });
            }
        }

        return new RepositoryConfig(entries, clients, MailSettings, KeyVaultBuilders, ConfigDirectories) { Hosts = Hosts, DeployParameters = records };
    }

    private static DeployParameterRecord Declared(
        DeployParameterRecord record, DeployParameter parameter, string kind, DeployParameterTarget target, string directory,
        DeployParameterFile file, List<ConfigEntry> entries, List<ClientEndpointEntry> clients)
    {
        var link = new DeployLink(parameter.Name, "parameters_xml", 1.0);
        record = record with { LinkedKind = target.Kind, LinkedName = target.Name, LinkMethod = link.Method, LinkConfidence = link.Confidence };
        switch (target.Kind)
        {
            case "client_endpoint" when kind == "url":
                var basis = clients.FirstOrDefault(e => e.Directory.Equals(directory, StringComparison.OrdinalIgnoreCase) && e.Name == target.Name && e.Link is null);
                if (basis is null)
                {
                    return record with { LinkedKind = null, LinkedName = null, LinkNote = $"parameters.xml names endpoint '{target.Name}', which the project's configuration does not declare" };
                }

                clients.Add(FromParameter(basis, parameter, file, link));
                return record;
            case "app_setting":
                // Read the way the key it replaces is read (an appsettings.json key or an appSettings entry).
                var replaced = entries.FirstOrDefault(e => e.Directory.Equals(directory, StringComparison.OrdinalIgnoreCase) && e.Link is null
                                                           && e.KeyPath.Equals(target.Name, StringComparison.OrdinalIgnoreCase));
                entries.Add(new ConfigEntry(file.RelativePath, directory, file.Environment, target.Name, replaced?.Kind ?? "app_setting",
                    kind is "url" or "path" ? parameter.RawValue : null, null, kind == "sensitive" || Secrets.IsSensitiveKey(target.Name), parameter.Line) { Link = link });
                return record;
            case "connection_string":
                // Facts only (host, port, provider, authentication), as for any connection string.
                entries.Add(new ConfigEntry(file.RelativePath, directory, file.Environment, $"ConnectionStrings:{target.Name}", "connection_string", null,
                    Secrets.ReadConnectionFacts(parameter.RawValue), false, parameter.Line) { Link = link });
                return record;
            default:
                return record;
        }
    }

    private static DeployParameterRecord Inferred(
        DeployParameterRecord record, DeployParameter parameter, string kind, string directory,
        DeployParameterFile file, List<ConfigEntry> entries, List<ClientEndpointEntry> clients)
    {
        if (kind != "url")
        {
            return record;
        }

        var value = Endpoints.FromUrl(parameter.RawValue);
        var name = Normalise(parameter.Name);
        var scored = clients
            .Where(e => e.Directory.Equals(directory, StringComparison.OrdinalIgnoreCase) && e.Link is null)
            .GroupBy(e => e.Name ?? e.Contract, StringComparer.Ordinal)
            .Select(g => g.OrderBy(e => e.Environment == "default" ? 0 : 1).First())
            .Select(e =>
            {
                var endpointName = Normalise(e.Name ?? e.Contract);
                var nameMatch = name.Length >= 4 && (endpointName.Contains(name) || name.Contains(endpointName) || name.Contains(Normalise(e.Contract)));
                var pathMatch = value?.Path is { } path && e.Endpoint.Path is { } own
                                && LastSegment(path).Equals(LastSegment(own), StringComparison.OrdinalIgnoreCase) && LastSegment(own).Length > 0;
                return (Entry: e, Score: (nameMatch ? 1 : 0) + (pathMatch ? 1 : 0));
            })
            .Where(x => x.Score > 0)
            .OrderByDescending(x => x.Score)
            .ToList();
        if (scored.Count > 0 && (scored.Count == 1 || scored[0].Score > scored[1].Score))
        {
            var link = new DeployLink(parameter.Name, "name_and_path", scored[0].Score == 2 ? 0.8 : 0.6);
            clients.Add(FromParameter(scored[0].Entry, parameter, file, link));
            return record with
            {
                LinkedKind = "client_endpoint", LinkedName = scored[0].Entry.Name ?? scored[0].Entry.Contract,
                LinkMethod = link.Method, LinkConfidence = link.Confidence,
            };
        }

        // An appSettings key of the same name, already holding a URL.
        var setting = entries.FirstOrDefault(e => e.Directory.Equals(directory, StringComparison.OrdinalIgnoreCase) && e.Kind is "app_setting" or "json"
                                                  && e.KeyPath.Equals(parameter.Name, StringComparison.OrdinalIgnoreCase) && e.Link is null);
        if (setting is not null)
        {
            var link = new DeployLink(parameter.Name, "name_and_path", 0.7);
            entries.Add(new ConfigEntry(file.RelativePath, directory, file.Environment, setting.KeyPath, setting.Kind, parameter.RawValue, null, false, parameter.Line) { Link = link });
            return record with { LinkedKind = "app_setting", LinkedName = setting.KeyPath, LinkMethod = link.Method, LinkConfidence = link.Confidence };
        }

        return record;
    }

    private static ClientEndpointEntry FromParameter(ClientEndpointEntry basis, DeployParameter parameter, DeployParameterFile file, DeployLink link)
    {
        var endpoint = Endpoints.FromUrl(parameter.RawValue) ?? new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = $"setParameter[{parameter.Name}]" };
        return basis with
        {
            File = file.RelativePath,
            Environment = file.Environment,
            Endpoint = endpoint with { Source = new ConfigSource { SourceFile = file.RelativePath, KeyPath = $"setParameter[{parameter.Name}]" } },
            Line = parameter.Line,
            Link = link,
        };
    }

    private static string Normalise(string name)
    {
        var letters = new string(name.Where(char.IsLetterOrDigit).ToArray()).ToLowerInvariant();
        foreach (var suffix in new[] { "url", "uri", "address", "endpoint" })
        {
            if (letters.EndsWith(suffix, StringComparison.Ordinal) && letters.Length > suffix.Length)
            {
                letters = letters[..^suffix.Length];
            }
        }

        return letters;
    }

    private static string LastSegment(string path) => path.TrimEnd('/').Split('/')[^1];

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
