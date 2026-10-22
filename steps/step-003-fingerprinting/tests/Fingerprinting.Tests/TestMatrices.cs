using Fingerprinting.Outbound;

namespace Fingerprinting.Tests;

/// <summary>The real WCF client matrices from schemas/, for tests that need
/// SOAP verdicts: both come from data, never from a rule in code.</summary>
public static class TestMatrices
{
    public static string Schemas(string file) =>
        Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "schemas", file));

    public static readonly WcfClientSupport Runtime = WcfClientSupport.Load(Schemas("wcf-client-support-1.1.0.json"));
    public static readonly WcfClientSupport Platform = WcfClientSupport.Load(Schemas("wcf-client-platform-1.2.1.json"));
    public static readonly SoapMatrices Soap = new("net10.0", Runtime, Platform);

    public static string PlatformPath => Schemas("wcf-client-platform-1.2.1.json");
}
