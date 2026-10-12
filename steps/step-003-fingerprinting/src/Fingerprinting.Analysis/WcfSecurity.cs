namespace Fingerprinting.Analysis;

/// <summary>
/// An endpoint's effective security: the binding, its security mode and the
/// client credential type that mode uses. Declared values win; a value left
/// out falls back to WCF's documented default for that binding — recorded as
/// <c>binding_default</c>, never passed off as declared. Where no default is
/// certain, the value stays null and so does <see cref="Anonymous"/>.
/// </summary>
public sealed record WcfEndpointSecurity(string Binding, string? SecurityMode, string? ClientCredentialType, string SecuritySource, bool? Anonymous);

public static class WcfSecurity
{
    /// <summary>Code class name → config element name.</summary>
    public static readonly IReadOnlyDictionary<string, string> BindingNames = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["BasicHttpBinding"] = "basicHttpBinding",
        ["BasicHttpsBinding"] = "basicHttpsBinding",
        ["WSHttpBinding"] = "wsHttpBinding",
        ["WS2007HttpBinding"] = "ws2007HttpBinding",
        ["WSDualHttpBinding"] = "wsDualHttpBinding",
        ["WSFederationHttpBinding"] = "wsFederationHttpBinding",
        ["NetTcpBinding"] = "netTcpBinding",
        ["NetNamedPipeBinding"] = "netNamedPipeBinding",
        ["NetMsmqBinding"] = "netMsmqBinding",
        ["NetHttpBinding"] = "netHttpBinding",
        ["NetHttpsBinding"] = "netHttpsBinding",
        ["WebHttpBinding"] = "webHttpBinding",
        ["CustomBinding"] = "customBinding",
    };

    /// <summary>Defaults this step is certain of (mode, transport credential,
    /// message credential). A null is "not certain", not "none". The same
    /// table, with its sources (Microsoft Learn: System-provided bindings, and
    /// each binding's &lt;security&gt; element), is in
    /// schemas/wcf-client-support-*.json; a test holds the two together.</summary>
    public static readonly IReadOnlyDictionary<string, (string Mode, string? Transport, string? Message)> Defaults =
        new Dictionary<string, (string, string?, string?)>(StringComparer.Ordinal)
        {
            ["basicHttpBinding"] = ("None", "None", "UserName"),
            ["basicHttpsBinding"] = ("Transport", "None", "UserName"),
            ["netHttpBinding"] = ("None", "None", "UserName"),
            ["netHttpsBinding"] = ("Transport", "None", "UserName"),
            ["netTcpBinding"] = ("Transport", "Windows", "Windows"),
            ["netNamedPipeBinding"] = ("Transport", "Windows", null),
            ["wsHttpBinding"] = ("Message", null, "Windows"),
            ["ws2007HttpBinding"] = ("Message", null, "Windows"),
            ["wsDualHttpBinding"] = ("Message", null, "Windows"),
            ["webHttpBinding"] = ("None", "None", null),
        };

    public static WcfEndpointSecurity Resolve(string binding, string? mode, string? transportCredential, string? messageCredential)
    {
        var hasDefaults = Defaults.TryGetValue(binding, out var defaults);
        var usedDefault = false;

        var effectiveMode = mode;
        if (effectiveMode is null && hasDefaults)
        {
            effectiveMode = defaults.Mode;
            usedDefault = true;
        }

        if (effectiveMode is null)
        {
            return new WcfEndpointSecurity(binding, null, null, "unresolved", null);
        }

        if (effectiveMode.Contains('|'))
        {
            // Two possible modes from code; decided at run time.
            return new WcfEndpointSecurity(binding, effectiveMode, null, "unresolved", null);
        }

        if (effectiveMode == "None")
        {
            return new WcfEndpointSecurity(binding, "None", "None", usedDefault ? "binding_default" : "declared", true);
        }

        var usesTransport = effectiveMode is "Transport" or "TransportCredentialOnly";
        var credential = usesTransport ? transportCredential : messageCredential;
        if (credential is null && hasDefaults)
        {
            credential = usesTransport ? defaults.Transport : defaults.Message;
            usedDefault |= credential is not null;
        }

        if (credential is null || credential.Contains('|'))
        {
            return new WcfEndpointSecurity(binding, effectiveMode, credential, "unresolved", null);
        }

        return new WcfEndpointSecurity(binding, effectiveMode, credential, usedDefault ? "binding_default" : "declared", credential == "None");
    }
}
