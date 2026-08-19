using System.Text.Json;
using System.Xml;
using System.Xml.Linq;
using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Level 2 (structured-file) extraction — step-3-application-fingerprinting.md
/// section 8: web.config, app.config and appsettings.json. Merges what
/// section 30 called WcfConfigurationExtractor and AspNetConfigurationExtractor
/// (they parse the same files) plus the section 8.4 database indicators.
///
/// The secrets rule (Part G) is mechanically enforced, not a convention: this
/// extractor never calls <c>.Value</c> on a <c>connectionString</c> attribute,
/// never reads a JSON leaf whose key matched the sensitive-key pattern, and
/// never stores a source snippet — only a hash. See
/// Fingerprinting.Tests/ConfigurationExtractorSecretsTests.cs for the
/// mechanical proof.
/// </summary>
public sealed class ConfigurationExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "ConfigurationExtractor";

    public string Name => ExtractorName;

    private static readonly string[] SensitiveKeyPatterns =
        ["password", "pwd", "secret", "token", "apikey", "api_key", "connectionstring", "accountkey", "sharedaccesskey", "credential"];

    public bool CanProcess(ProjectContext context) => Directory.Exists(context.ProjectDirectory);

    public Task<ExtractorResult> ExtractAsync(ProjectContext context, CancellationToken cancellationToken)
    {
        var accumulator = new SignalAccumulator();
        var warnings = new List<Warning>();

        foreach (var filePath in FileSystemWalk.EnumerateFiles(context.ProjectDirectory, cancellationToken))
        {
            var fileName = Path.GetFileName(filePath);
            var isAppSettings = string.Equals(fileName, "appsettings.json", StringComparison.OrdinalIgnoreCase);
            var isXmlConfig = string.Equals(fileName, "web.config", StringComparison.OrdinalIgnoreCase)
                || string.Equals(fileName, "app.config", StringComparison.OrdinalIgnoreCase);

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

        // 8.2 Endpoint indicators — service endpoints and binding types.
        foreach (var endpoint in root.Descendants().Where(e => e.Name.LocalName == "endpoint"))
        {
            var contract = (string?)endpoint.Attribute("contract");
            var binding = (string?)endpoint.Attribute("binding");
            var lineInfo = (IXmlLineInfo)endpoint;

            if (!string.IsNullOrEmpty(contract))
            {
                accumulator.Add(
                    "WCF_SERVICE_ENDPOINT_CONFIG", SignalCategories.EndpointIndicator, SignalTypes.ConfigElement,
                    contract, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                    evidence: LineEvidence(lineInfo, endpoint));
            }

            if (!string.IsNullOrEmpty(binding))
            {
                accumulator.Add(
                    "WCF_BINDING_CONFIG", SignalCategories.EndpointIndicator, SignalTypes.ConfigElement,
                    binding, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                    evidence: LineEvidence(lineInfo, endpoint));
            }
        }

        // 8.4 Database indicators — connection string NAME and PROVIDER only,
        // never the connectionString attribute's value (Part G).
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
            }

            if (!string.IsNullOrEmpty(provider))
            {
                accumulator.Add(
                    "CONNECTION_STRING_PROVIDER_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                    provider, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                    evidence: LineEvidence(lineInfo, add));
            }
            // add.Attribute("connectionString") is deliberately never read.
        }

        // Secrets rule (Part G), mechanically enforced, universally: any XML
        // attribute whose NAME matches the sensitive-key pattern is recorded
        // by presence only — its value is never read here.
        foreach (var element in root.DescendantsAndSelf())
        {
            foreach (var attribute in element.Attributes())
            {
                if (IsSensitiveKey(attribute.Name.LocalName))
                {
                    accumulator.Add(
                        "SENSITIVE_CONFIG_KEY", SignalCategories.ConfigurationIndicator, SignalTypes.ConfigElement,
                        attribute.Name.LocalName, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                        evidence: LineEvidence((IXmlLineInfo)element, element));
                }
            }
        }

        // appSettings shape <add key="X" value="Y"/> — X itself may name a
        // sensitive setting even though the XML attribute is literally called
        // "key", not "password". Y is never read.
        foreach (var add in root.Descendants().Where(e => e.Name.LocalName == "add"))
        {
            var key = (string?)add.Attribute("key");
            if (key is not null && IsSensitiveKey(key))
            {
                accumulator.Add(
                    "SENSITIVE_CONFIG_KEY", SignalCategories.ConfigurationIndicator, SignalTypes.ConfigElement,
                    key, EvidenceSourceTypes.Configuration, relativePath, ExtractorName,
                    evidence: LineEvidence((IXmlLineInfo)add, add));
            }
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

    // ---- JSON: appsettings.json --------------------------------------------

    private static void ExtractFromAppSettings(string filePath, string relativePath, SignalAccumulator accumulator)
    {
        var json = File.ReadAllText(filePath);
        using var doc = JsonDocument.Parse(json);
        WalkAppSettings(doc.RootElement, relativePath, accumulator);
    }

    private static void WalkAppSettings(JsonElement element, string relativePath, SignalAccumulator accumulator)
    {
        if (element.ValueKind != JsonValueKind.Object)
        {
            return;
        }

        foreach (var property in element.EnumerateObject())
        {
            if (string.Equals(property.Name, "ConnectionStrings", StringComparison.OrdinalIgnoreCase)
                && property.Value.ValueKind == JsonValueKind.Object)
            {
                foreach (var connectionString in property.Value.EnumerateObject())
                {
                    // The name is the JSON key; the value is the full
                    // connection string and is never read (Part G).
                    accumulator.Add(
                        "CONNECTION_STRING_CONFIG", SignalCategories.DataAccessIndicator, SignalTypes.ConfigElement,
                        connectionString.Name, EvidenceSourceTypes.Configuration, relativePath, ExtractorName);
                }

                continue;
            }

            if (IsSensitiveKey(property.Name))
            {
                // Presence only — never descend into or read a sensitive
                // key's value, whether it is a leaf or a nested object.
                accumulator.Add(
                    "SENSITIVE_CONFIG_KEY", SignalCategories.ConfigurationIndicator, SignalTypes.ConfigElement,
                    property.Name, EvidenceSourceTypes.Configuration, relativePath, ExtractorName);
                continue;
            }

            if (property.Value.ValueKind == JsonValueKind.Object)
            {
                WalkAppSettings(property.Value, relativePath, accumulator);
            }
        }
    }

    private static bool IsSensitiveKey(string key) =>
        SensitiveKeyPatterns.Any(pattern => key.Contains(pattern, StringComparison.OrdinalIgnoreCase));
}
