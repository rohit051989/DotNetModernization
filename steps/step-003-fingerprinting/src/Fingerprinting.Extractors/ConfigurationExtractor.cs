using System.Text.Json;
using System.Xml;
using System.Xml.Linq;
using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Level 2 (structured-file) extraction — step-3-application-fingerprinting.md
/// section 8: web.config, app.config and appsettings*.json. Merges what
/// section 30 called WcfConfigurationExtractor and AspNetConfigurationExtractor
/// (they parse the same files) plus the section 8.4 database indicators.
///
/// The secrets rule (Part G) is mechanically enforced: <b>nothing derived
/// from a connection string is ever persisted</b>, and a sensitive key's
/// value is never read. The one read of a connection string is
/// <see cref="Secrets.UsesWindowsAuthentication"/>, which returns a bool;
/// every signal from a connection string carries only its name. See
/// Fingerprinting.Tests/ConfigurationExtractorSecretsTests.cs for the
/// mechanical proof.
/// </summary>
public sealed class ConfigurationExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "ConfigurationExtractor";

    public string Name => ExtractorName;

    // Name-based heuristics for integration settings. The key path is
    // recorded, never the value (hosts, passwords and tokens live there).
    private const decimal HeuristicConfidence = 0.80m;

    public bool CanProcess(ProjectContext context) => Directory.Exists(context.ProjectDirectory);

    public Task<ExtractorResult> ExtractAsync(ProjectContext context, CancellationToken cancellationToken)
    {
        var accumulator = new SignalAccumulator();
        var warnings = new List<Warning>();

        foreach (var filePath in FileSystemWalk.EnumerateFiles(context.ProjectDirectory, cancellationToken))
        {
            var fileName = Path.GetFileName(filePath);
            var isAppSettings = ConfigFileNames.IsAppSettings(fileName);
            var isXmlConfig = ConfigFileNames.IsXmlConfig(fileName);

            if (!isAppSettings && !isXmlConfig)
            {
                continue;
            }

            var relativePath = FileSystemWalk.ToRepositoryRelativePath(context.RepositoryRoot, filePath);

            try
            {
                if (isAppSettings)
                {
                    ExtractFromAppSettings(filePath, relativePath, accumulator);
                }
                else
                {
                    ExtractFromXmlConfig(filePath, relativePath, accumulator);
                }
            }
            catch (Exception ex) when (ex is IOException or XmlException or JsonException)
            {
                warnings.Add(new Warning
                {
                    Code = WarningCodes.ConfigurationParseFailed,
                    Message = $"Could not parse configuration file '{relativePath}': {ex.Message}",
                    Severity = WarningSeverities.Warning,
                });
            }
        }

        // Web Deploy SetParameters (registry 1.7.0): they mix properties,
        // configuration and secrets. A parameter named like a secret is
        // recorded by name only; a connection string by name, with the one
        // permitted bool read — the same rules as web.config.
        foreach (var file in context.DeployParameterFiles)
        {
            foreach (var parameter in file.Parameters)
            {
                var evidence = new Evidence
                {
                    LineStart = parameter.Line,
                    LineEnd = parameter.Line,
                    SnippetHash = Hashing.Sha256Hex(parameter.Name),
                };
                switch (Fingerprinting.Analysis.DeployParameterFiles.Classify(parameter))
                {
                    case "sensitive":
                        accumulator.Add(
                            "SENSITIVE_CONFIG_KEY", SignalCategories.ConfigurationIndicator, SignalTypes.ConfigElement,
                            parameter.Name, EvidenceSourceTypes.Configuration, file.RelativePath, ExtractorName, evidence: evidence);
                        break;
                    case "connection_string":
                        accumulator.Add(
                            "CONNECTION_STRING_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                            parameter.Name, EvidenceSourceTypes.Configuration, file.RelativePath, ExtractorName, evidence: evidence);
                        if (Secrets.UsesWindowsAuthentication(parameter.RawValue))
                        {
                            accumulator.Add(
                                "WINDOWS_AUTH_CONNECTION_STRING_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                                parameter.Name, EvidenceSourceTypes.Configuration, file.RelativePath, ExtractorName, evidence: evidence);
                        }

                        break;
                }
            }
        }

        return Task.FromResult(new ExtractorResult { Signals = accumulator.Build(), Warnings = warnings });
    }

    // ---- XML: web.config / app.config -------------------------------------

    private static void ExtractFromXmlConfig(string filePath, string relativePath, SignalAccumulator accumulator)
    {
        var xml = File.ReadAllText(filePath);
        var doc = XDocument.Parse(xml, LoadOptions.SetLineInfo);
        var root = doc.Root;
        if (root is null)
        {
            return;
        }

        // 8.1 Hosting indicators — presence-only.
        AddPresenceSignals(root, "system.web", "SYSTEM_WEB_CONFIG", relativePath, accumulator);
        AddPresenceSignals(root, "system.webServer", "SYSTEM_WEBSERVER_CONFIG", relativePath, accumulator);
        AddPresenceSignals(root, "system.serviceModel", "SYSTEM_SERVICE_MODEL_CONFIG", relativePath, accumulator);
        AddPresenceSignals(root, "aspNetCore", "ASPNETCORE_CONFIG", relativePath, accumulator);
        AddPresenceSignals(root, "serviceHostingEnvironment", "SERVICE_HOSTING_ENVIRONMENT_CONFIG", relativePath, accumulator);

        // 8.2 Endpoint indicators. A service endpoint lives under
        // <services>, a client endpoint under <client>; the binding type is
        // recorded for both. Before 1.4.0 every <endpoint> counted as a
        // service endpoint, contradicting the signal's registry description.
        // WCF_BINDING_CONFIG does not say which kind of endpoint a binding
        // belongs to, so a client endpoint's binding is also recorded on its
        // own (WCF_CLIENT_BINDING_CONFIG, registry 1.5.0) — "a client calling
        // over netTcpBinding" is then one condition, and a NetTcp *service*
        // beside an HTTP client no longer looks like a NetTcp client.
        foreach (var endpoint in root.Descendants().Where(e => e.Name.LocalName == "endpoint"))
        {
            var contract = (string?)endpoint.Attribute("contract");
            var binding = (string?)endpoint.Attribute("binding");
            var lineInfo = (IXmlLineInfo)endpoint;
            var ancestors = endpoint.Ancestors().Select(a => a.Name.LocalName).ToList();

            if (!string.IsNullOrEmpty(binding) && ancestors.Contains("client"))
            {
                accumulator.Add(
                    "WCF_CLIENT_BINDING_CONFIG", SignalCategories.EndpointIndicator, SignalTypes.ConfigElement,
                    binding, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                    evidence: LineEvidence(lineInfo, endpoint));
            }

            if (!string.IsNullOrEmpty(contract))
            {
                if (ancestors.Contains("services"))
                {
                    accumulator.Add(
                        "WCF_SERVICE_ENDPOINT_CONFIG", SignalCategories.EndpointIndicator, SignalTypes.ConfigElement,
                        contract, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                        evidence: LineEvidence(lineInfo, endpoint));
                }
                else if (ancestors.Contains("client"))
                {
                    accumulator.Add(
                        "WCF_CLIENT_ENDPOINT_CONFIG", SignalCategories.EndpointIndicator, SignalTypes.ConfigElement,
                        contract, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                        evidence: LineEvidence(lineInfo, endpoint));
                }
            }

            if (!string.IsNullOrEmpty(binding))
            {
                accumulator.Add(
                    "WCF_BINDING_CONFIG", SignalCategories.EndpointIndicator, SignalTypes.ConfigElement,
                    binding, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                    evidence: LineEvidence(lineInfo, endpoint));
            }
        }

        // 8.4 Database indicators — connection string NAME and PROVIDER only.
        foreach (var add in root.Descendants().Where(e => e.Name.LocalName == "connectionStrings")
                     .SelectMany(cs => cs.Elements().Where(e => e.Name.LocalName == "add")))
        {
            var name = (string?)add.Attribute("name");
            var provider = (string?)add.Attribute("providerName");
            var lineInfo = (IXmlLineInfo)add;

            if (!string.IsNullOrEmpty(name))
            {
                accumulator.Add(
                    "CONNECTION_STRING_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                    name, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                    evidence: LineEvidence(lineInfo, add));

                // The one permitted read: a bool comes back, the string is
                // not kept, and the signal carries only the name.
                var connectionString = (string?)add.Attribute("connectionString");
                if (connectionString is not null && Secrets.UsesWindowsAuthentication(connectionString))
                {
                    accumulator.Add(
                        "WINDOWS_AUTH_CONNECTION_STRING_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                        name, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                        evidence: LineEvidence(lineInfo, add));
                }

                if (name.Contains("redis", StringComparison.OrdinalIgnoreCase))
                {
                    accumulator.Add(
                        "REDIS_CONNECTION_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                        $"connectionStrings:{name}", EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                        HeuristicConfidence, LineEvidence(lineInfo, add));
                }
            }

            if (!string.IsNullOrEmpty(provider))
            {
                accumulator.Add(
                    "CONNECTION_STRING_PROVIDER_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                    provider, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                    evidence: LineEvidence(lineInfo, add));
            }
        }

        // Secrets rule (Part G), universally: any XML attribute whose NAME
        // matches the sensitive-key pattern is recorded by presence only.
        foreach (var element in root.DescendantsAndSelf())
        {
            foreach (var attribute in element.Attributes())
            {
                if (Secrets.IsSensitiveKey(attribute.Name.LocalName))
                {
                    accumulator.Add(
                        "SENSITIVE_CONFIG_KEY", SignalCategories.ConfigurationIndicator, SignalTypes.ConfigElement,
                        attribute.Name.LocalName, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                        evidence: LineEvidence((IXmlLineInfo)element, element));
                }
            }
        }

        // appSettings shape <add key="X" value="Y"/> — X may name a sensitive
        // or integration setting. Y is never read.
        foreach (var add in root.Descendants().Where(e => e.Name.LocalName == "add"))
        {
            var key = (string?)add.Attribute("key");
            if (key is null)
            {
                continue;
            }

            var evidence = LineEvidence((IXmlLineInfo)add, add);
            if (Secrets.IsSensitiveKey(key))
            {
                accumulator.Add(
                    "SENSITIVE_CONFIG_KEY", SignalCategories.ConfigurationIndicator, SignalTypes.ConfigElement,
                    key, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                    evidence: evidence);
            }

            var segments = key.Split([':', '.'], StringSplitOptions.RemoveEmptyEntries);
            AddIntegrationSignals(segments, key, relativePath, evidence, accumulator, alreadyInRedis: false, alreadyInVault: false);
        }
    }

    private static void AddPresenceSignals(XElement root, string localName, string signalName, string relativePath, SignalAccumulator accumulator)
    {
        foreach (var element in root.DescendantsAndSelf().Where(e => e.Name.LocalName == localName))
        {
            accumulator.Add(
                signalName, SignalCategories.HostingIndicator, SignalTypes.ConfigElement,
                value: null, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                evidence: LineEvidence((IXmlLineInfo)element, element));
        }
    }

    private static Evidence LineEvidence(IXmlLineInfo lineInfo, XElement element) => new()
    {
        LineStart = lineInfo.HasLineInfo() ? lineInfo.LineNumber : null,
        LineEnd = lineInfo.HasLineInfo() ? lineInfo.LineNumber : null,
        SnippetHash = Hashing.Sha256Hex(element.Name.LocalName),
    };

    // ---- JSON: appsettings*.json -------------------------------------------

    private static void ExtractFromAppSettings(string filePath, string relativePath, SignalAccumulator accumulator)
    {
        var nodes = JsonConfigWalker.Walk(filePath);
        var byPath = nodes
            .GroupBy(n => PathKey(n.Path))
            .ToDictionary(g => g.Key, g => g.First(), StringComparer.Ordinal);

        foreach (var node in nodes)
        {
            var evidence = JsonEvidence(node);

            if (node.IsConnectionString)
            {
                accumulator.Add(
                    "CONNECTION_STRING_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                    node.Name, EvidenceSourceTypes.Configuration, relativePath, ExtractorName, evidence: evidence);

                if (node.UsesWindowsAuthentication)
                {
                    accumulator.Add(
                        "WINDOWS_AUTH_CONNECTION_STRING_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                        node.Name, EvidenceSourceTypes.Configuration, relativePath, ExtractorName, evidence: evidence);
                }

                if (node.Name.Contains("redis", StringComparison.OrdinalIgnoreCase))
                {
                    accumulator.Add(
                        "REDIS_CONNECTION_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                        node.KeyPath, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                        HeuristicConfidence, evidence);
                }

                continue;
            }

            if (node.IsSensitiveKey)
            {
                accumulator.Add(
                    "SENSITIVE_CONFIG_KEY", SignalCategories.ConfigurationIndicator, SignalTypes.ConfigElement,
                    node.Name, EvidenceSourceTypes.Configuration, relativePath, ExtractorName, evidence: evidence);
            }

            if (node.Path.Count == 0)
            {
                continue;
            }

            if (IsSerilogFileSinkName(node))
            {
                // Args.path beside the Name — a location, never secret.
                var sinkPath = node.Path.Take(node.Path.Count - 1).Append("Args").Append("path").ToList();
                var pathValue = byPath.GetValueOrDefault(PathKey(sinkPath))?.StringValue;
                accumulator.Add(
                    "SERILOG_FILE_SINK_CONFIG", SignalCategories.ConfigurationIndicator, SignalTypes.ConfigElement,
                    pathValue, EvidenceSourceTypes.Configuration, relativePath, ExtractorName, evidence: evidence);
            }

            var parents = node.Path.Take(node.Path.Count - 1).ToList();
            AddIntegrationSignals(
                node.Path, node.KeyPath, relativePath, evidence, accumulator,
                alreadyInRedis: parents.Any(IsRedisSegment),
                alreadyInVault: parents.Any(IsVaultSegment),
                isInConnectionStrings: parents.Any(p => p.Equals("ConnectionStrings", StringComparison.OrdinalIgnoreCase)));
        }
    }

    // A Serilog sink entry: "Name": "File" (or the legacy "RollingFile")
    // anywhere under the root "Serilog" section — WriteTo[n], an object-form
    // WriteTo, or a sink nested in WriteTo[n].Args.configure (Async).
    private static bool IsSerilogFileSinkName(JsonConfigNode node) =>
        node.Path.Count >= 2
        && node.Path[0].Equals("Serilog", StringComparison.OrdinalIgnoreCase)
        && node.Name.Equals("Name", StringComparison.OrdinalIgnoreCase)
        && node.StringValue is { } sink
        && (sink.Equals("File", StringComparison.OrdinalIgnoreCase) || sink.Equals("RollingFile", StringComparison.OrdinalIgnoreCase));

    private static Evidence JsonEvidence(JsonConfigNode node) => new()
    {
        LineStart = node.Line,
        LineEnd = node.Line,
        SnippetHash = Hashing.Sha256Hex(node.KeyPath),
    };

    private static string PathKey(IEnumerable<string> path) =>
        string.Join('\u001f', path.Select(p => p.ToLowerInvariant()));

    // ---- integration settings (both formats) -------------------------------

    private static bool IsRedisSegment(string segment) => segment.Contains("redis", StringComparison.OrdinalIgnoreCase);

    // HashiCorp Vault only. Azure Key Vault settings (KeyVaultName,
    // AzureKeyVault) also contain "vault" and are a different product.
    private static bool IsVaultSegment(string segment) =>
        segment.Contains("vault", StringComparison.OrdinalIgnoreCase)
        && !segment.Contains("keyvault", StringComparison.OrdinalIgnoreCase);

    private static bool IsKafkaBootstrapSegment(string segment) =>
        segment.Replace(".", string.Empty).Replace("_", string.Empty)
            .Equals("bootstrapservers", StringComparison.OrdinalIgnoreCase);

    /// <summary>Kafka bootstrap servers, and the topmost Redis or Vault key —
    /// by name only. <paramref name="keyPath"/> is what gets recorded.</summary>
    private static void AddIntegrationSignals(
        IReadOnlyList<string> segments, string keyPath, string relativePath, Evidence evidence,
        SignalAccumulator accumulator, bool alreadyInRedis, bool alreadyInVault, bool isInConnectionStrings = false)
    {
        if (segments.Count == 0)
        {
            return;
        }

        var last = segments[^1];

        if (IsKafkaBootstrapSegment(last))
        {
            accumulator.Add(
                "KAFKA_BOOTSTRAP_CONFIG", SignalCategories.MessagingIndicator, SignalTypes.ConfigElement,
                keyPath, EvidenceSourceTypes.Configuration, relativePath, ExtractorName, HeuristicConfidence, evidence);
        }

        // Topmost matching key only, so a Redis section with six settings is
        // one row, not seven. ConnectionStrings entries are handled above.
        var redisMatch = segments.Take(segments.Count - 1).Any(IsRedisSegment);
        if (!isInConnectionStrings && IsRedisSegment(last) && !alreadyInRedis && !redisMatch)
        {
            accumulator.Add(
                "REDIS_CONNECTION_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                keyPath, EvidenceSourceTypes.Configuration, relativePath, ExtractorName, HeuristicConfidence, evidence);
        }

        var vaultMatch = segments.Take(segments.Count - 1).Any(IsVaultSegment);
        if (!isInConnectionStrings && IsVaultSegment(last) && !alreadyInVault && !vaultMatch)
        {
            accumulator.Add(
                "VAULT_CONFIG", SignalCategories.ConfigurationIndicator, SignalTypes.ConfigElement,
                keyPath, EvidenceSourceTypes.Configuration, relativePath, ExtractorName, HeuristicConfidence, evidence);
        }
    }
}
