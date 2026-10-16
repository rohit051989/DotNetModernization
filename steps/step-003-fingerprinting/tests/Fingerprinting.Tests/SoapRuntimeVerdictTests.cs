using System.Text.Json;
using Fingerprinting.Analysis;
using Fingerprinting.Outbound;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>outbound-invocation-inventory — two verdicts on every SOAP environment
/// binding: platform (Linux, from the WCF client platform matrix) and runtime (the
/// target .NET's WCF client, from the WCF client support matrix), both data,
/// matrices 1.1.0. 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C10, C11.</summary>
public class SoapRuntimeVerdictTests
{
    private static readonly string MatrixPath = Path.GetFullPath(Path.Combine(
        AppContext.BaseDirectory, "..", "..", "..", "..", "..", "schemas", "wcf-client-support-1.1.0.json"));

    private static readonly WcfClientSupport Matrix = WcfClientSupport.Load(MatrixPath);

    private static IReadOnlyList<Invocation> Detect(string code, params (string Path, string Text)[] config)
    {
        var project = new OutboundInputProject("src/App/App.csproj", Guid.Empty, null, [], []);
        var source = ProjectSource.FromText("src/App/App.csproj", new Dictionary<string, string> { ["src/App/Use.cs"] = code });
        return OutboundPipeline.Detect(Guid.Empty, [(project, source)], RepositoryConfig.FromText(config), soapMatrices: TestMatrices.Soap)
            .Single().Invocations;
    }

    private static string Config(string bindings, string endpoint) => $"""
        <configuration>
          <system.serviceModel>
            <bindings>{bindings}</bindings>
            <client>{endpoint}</client>
          </system.serviceModel>
        </configuration>
        """;

    private const string Client = """
        class FundsClient : System.ServiceModel.ClientBase<IFunds> { public FundsClient() { } }
        class Use { void Go() { using (var c = new FundsClient()) { } } }
        """;

    [Fact]
    public void A_basicHttp_endpoint_with_nothing_declared_is_security_None_and_supported_with_its_matrix_entry()
    {
        var invocation = Assert.Single(Detect(Client, ("src/App/App.config", Config(
            """<basicHttpBinding><binding name="FundsSoap" /></basicHttpBinding>""",
            """<endpoint address="http://funds.corp.example.com/Funds.asmx" binding="basicHttpBinding" bindingConfiguration="FundsSoap" contract="Refs.IFunds" name="FundsSoap" />"""))));

        var binding = Assert.Single(invocation.EnvironmentBindings);
        Assert.Equal(("basicHttpBinding", "None", "None", "binding_default"),
            (binding.Soap!.Binding, binding.Soap.SecurityMode, binding.Soap.ClientCredentialType, binding.Soap.SecuritySource));
        Assert.Equal((RuntimeVerdictValues.Supported, "net10.0/basicHttpBinding/None/None"), (binding.RuntimeVerdict, binding.RuntimeMatrixEntry));
        // 1.1.0: confirmed by a reviewer on probe evidence, so no "not yet confirmed" reason.
        Assert.DoesNotContain(binding.RuntimeReasons!, r => r.Contains("not yet confirmed by a person"));
        Assert.Equal((Verdicts.Compatible, "net10.0/linux/basicHttpBinding/None/None"), (binding.LinuxVerdict, binding.PlatformMatrixEntry));
        Assert.Equal(("net10.0", "1.1.0", RuntimeVerdictValues.Supported),
            (invocation.RuntimeCompatibility!.Target, invocation.RuntimeCompatibility.MatrixVersion, invocation.RuntimeCompatibility.Verdict));
    }

    [Fact]
    public void A_wsHttp_endpoint_with_nothing_declared_is_evaluated_as_its_default_Message_security_and_is_unsupported()
    {
        var invocation = Assert.Single(Detect(Client, ("src/App/App.config", Config(
            """<wsHttpBinding><binding name="ws" /></wsHttpBinding>""",
            """<endpoint address="http://funds.corp.example.com/Funds.svc" binding="wsHttpBinding" bindingConfiguration="ws" contract="Refs.IFunds" name="Funds" />"""))));

        var binding = Assert.Single(invocation.EnvironmentBindings);
        Assert.Equal(("Message", "Windows", "binding_default"), (binding.Soap!.SecurityMode, binding.Soap.ClientCredentialType, binding.Soap.SecuritySource));
        Assert.Equal(RuntimeVerdictValues.Unsupported, binding.RuntimeVerdict);
        Assert.Equal("net10.0/wsHttpBinding/Message/*", binding.RuntimeMatrixEntry);
        Assert.Contains(binding.RuntimeReasons!, r => r.Contains("the binding's default: nothing declared"));
    }

    [Fact]
    public void Each_environment_file_is_judged_on_its_own_security()
    {
        // Release declares TransportWithMessageCredential; the default file declares nothing (Message).
        var invocation = Assert.Single(Detect(Client,
            ("src/App/Web.config", Config("""<wsHttpBinding><binding name="ws" /></wsHttpBinding>""",
                """<endpoint address="http://dev.corp.example.com/Funds.svc" binding="wsHttpBinding" bindingConfiguration="ws" contract="Refs.IFunds" name="Funds" />""")),
            ("src/App/Web.Release.config", Config(
                """<wsHttpBinding><binding name="ws"><security mode="TransportWithMessageCredential"><message clientCredentialType="Certificate" /></security></binding></wsHttpBinding>""",
                """<endpoint address="https://prod.corp.example.com/Funds.svc" binding="wsHttpBinding" bindingConfiguration="ws" contract="Refs.IFunds" name="Funds" />"""))));

        var byEnvironment = invocation.EnvironmentBindings.ToDictionary(b => b.Environment);
        Assert.Equal(RuntimeVerdictValues.Unsupported, byEnvironment["default"].RuntimeVerdict);
        Assert.Equal(("TransportWithMessageCredential", "Certificate", RuntimeVerdictValues.SupportedWithCaveat),
            (byEnvironment["Release"].Soap!.SecurityMode, byEnvironment["Release"].Soap!.ClientCredentialType, byEnvironment["Release"].RuntimeVerdict));
        Assert.Equal(RuntimeVerdictValues.Unsupported, invocation.RuntimeCompatibility!.Verdict);   // the worst environment's
        Assert.Contains(invocation.RuntimeCompatibility.Reasons, r => r.StartsWith("Release: "));
    }

    [Fact]
    public async Task The_artifact_with_both_verdicts_passes_its_schema()
    {
        var invocations = Detect(Client,
            ("src/App/Web.config", Config("""<wsHttpBinding><binding name="ws" /></wsHttpBinding>""",
                """<endpoint address="http://dev.corp.example.com/Funds.svc" binding="wsHttpBinding" bindingConfiguration="ws" contract="Refs.IFunds" name="Funds" />""")));
        var artifact = new OutboundInventoryArtifact
        {
            ScannerVersion = OutboundPipeline.ScannerVersion,
            RepositoryId = Guid.Empty,
            RepositorySlug = "fixture",
            SkipSource = "application-fingerprint",
            WcfClientSupport = new WcfClientSupportStamp { MatrixVersion = Matrix.MatrixVersion, Target = "net10.0", Sha256 = Matrix.Sha256, UnconfirmedEntries = Matrix.UnconfirmedCount },
            Summary = new OutboundSummary { InvocationCount = invocations.Count },
            Projects = [new ProjectInvocations { ProjectId = Guid.Empty, ProjectPath = "src/App/App.csproj", Status = "SCANNED", Summary = new ProjectOutboundSummary(), Invocations = invocations }],
        };
        var directory = Path.Combine(Path.GetTempPath(), "outbound-runtime-" + Guid.NewGuid().ToString("N"));
        try
        {
            var written = await File.ReadAllTextAsync(await Fingerprinting.Outbound.Cli.OutboundInventoryCli.WriteArtifactAsync(artifact, directory));
            Assert.Contains("\"runtimeVerdict\": \"unsupported\"", written);
        }
        finally
        {
            Directory.Delete(directory, recursive: true);
        }
    }

    [Fact]
    public void A_code_built_netTcp_binding_with_a_certificate_is_supported_and_compatible_both_from_data()
    {
        const string code = """
            using System.ServiceModel;
            class Use
            {
                void Go()
                {
                    var binding = new NetTcpBinding(SecurityMode.Transport) { Security = { Transport = { ClientCredentialType = TcpClientCredentialType.Certificate } } };
                    var f = new ChannelFactory<IOrders>(binding, new EndpointAddress("net.tcp://orders.corp.example.com:8201/Order"));
                }
            }
            """;
        var invocation = Assert.Single(Detect(code));
        Assert.Equal(RuntimeVerdictValues.Supported, invocation.RuntimeCompatibility!.Verdict);   // the WCF client supports it
        Assert.Equal(Verdicts.Compatible, invocation.LinuxCompatibility.Verdict);                // and on Linux: certificate, not Windows
    }

    [Fact]
    public void No_matrix_entries_for_the_target_is_unknown_never_a_guess()
    {
        var invocation = OutboundPipeline.Detect(Guid.Empty,
            [(new OutboundInputProject("src/App/App.csproj", Guid.Empty, null, [], []),
              ProjectSource.FromText("src/App/App.csproj", new Dictionary<string, string> { ["src/App/Use.cs"] = Client }))],
            RepositoryConfig.FromText([("src/App/App.config", Config("", """<endpoint address="http://x.corp/F.asmx" binding="basicHttpBinding" contract="Refs.IFunds" name="F" />"""))]))
            .Single().Invocations.Single();
        var judged = RuntimeVerdicts.Apply(invocation, Matrix, "net9.0");
        Assert.Equal(RuntimeVerdictValues.Unknown, judged.RuntimeCompatibility!.Verdict);
        Assert.Contains(judged.RuntimeCompatibility.Reasons, r => r.Contains("no entries for net9.0"));
    }

    // ---------- the matrix itself ----------

    [Fact]
    public void Every_matrix_entry_is_well_formed_cites_a_known_source_and_awaits_confirmation()
    {
        using var document = JsonDocument.Parse(File.ReadAllBytes(MatrixPath));
        var root = document.RootElement;
        var sources = root.GetProperty("sources").EnumerateArray().ToDictionary(s => s.GetProperty("id").GetString()!);
        var chart = sources["chart-v2.1.0"];
        Assert.Equal(("v2.1.0", "4429ddf7939696571ea6eb1439dc45684ab97829"), (chart.GetProperty("version").GetString(), chart.GetProperty("commit").GetString()));

        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var entry in root.GetProperty("entries").EnumerateArray())
        {
            var id = entry.GetProperty("id").GetString()!;
            Assert.True(ids.Add(id), $"duplicate entry {id}");
            Assert.Equal($"{entry.GetProperty("target").GetString()}/{entry.GetProperty("binding").GetString()}/" +
                         $"{entry.GetProperty("securityMode").GetString()}/{entry.GetProperty("credentialType").GetString()}", id);
            Assert.Contains(entry.GetProperty("verdict").GetString(), new[] { "supported", "supported_with_caveat", "unsupported", "unknown" });
            Assert.NotEmpty(entry.GetProperty("sources").EnumerateArray());
            Assert.All(entry.GetProperty("sources").EnumerateArray(), s => Assert.True(sources.ContainsKey(s.GetString()!), $"{id}: unknown source {s}"));
            Assert.False(string.IsNullOrWhiteSpace(entry.GetProperty("basis").GetString()));
            Assert.Contains(entry.GetProperty("confirmation").GetProperty("status").GetString(), new[] { "unconfirmed", "confirmed" });
        }
    }

    [Fact]
    public void The_platform_matrix_is_keyed_by_credential_netTcp_is_cross_platform_and_Windows_credentials_need_Kerberos()
    {
        var security = (string binding, string mode, string credential) => new EnvironmentSoapSecurity
        {
            Binding = binding, SecurityMode = mode, ClientCredentialType = credential, SecuritySource = "declared",
        };
        var (none, _, noneEntry) = LinuxVerdicts.SoapPlatform(security("netTcpBinding", "Transport", "None"), TestMatrices.Soap);
        var (cert, _, _) = LinuxVerdicts.SoapPlatform(security("netTcpBinding", "Transport", "Certificate"), TestMatrices.Soap);
        var (windows, reasons, windowsEntry) = LinuxVerdicts.SoapPlatform(security("netTcpBinding", "Transport", "Windows"), TestMatrices.Soap);
        Assert.Equal((Verdicts.Compatible, Verdicts.Compatible, "net10.0/linux/netTcpBinding/Transport/None"), (none, cert, noneEntry));
        Assert.Equal((Verdicts.RequiresChange, "net10.0/linux/netTcpBinding/*/Windows"), (windows, windowsEntry));
        Assert.Contains("change: Kerberos configuration on our side, or a credential change by the backend's owner", reasons);

        var (ntlm, _, _) = LinuxVerdicts.SoapPlatform(security("basicHttpBinding", "TransportCredentialOnly", "Ntlm"), TestMatrices.Soap);
        Assert.Equal(Verdicts.Incompatible, ntlm);                                                    // chart Linux: NTLM not supported
        var (custom, customReasons, _) = LinuxVerdicts.SoapPlatform(security("customBinding", "Transport", "None"), TestMatrices.Soap);
        Assert.Equal(Verdicts.Unknown, custom);                                                       // no entry: unknown, never a guess
        Assert.Contains(customReasons, r => r.Contains("no entry in the WCF client platform matrix"));
        Assert.Equal(Verdicts.Unknown, LinuxVerdicts.SoapPlatform(security("netTcpBinding", "Transport", "None"), null).Verdict);

        // 1.1.0: what no probe has exercised is unknown, never assumed compatible.
        var (twmc, twmcReasons, twmcEntry) = LinuxVerdicts.SoapPlatform(
            security("netTcpBinding", "TransportWithMessageCredential", "Certificate"), TestMatrices.Soap);
        Assert.Equal((Verdicts.Unknown, "net10.0/linux/netTcpBinding/*/*"), (twmc, twmcEntry));
        Assert.Contains(twmcReasons, r => r.StartsWith("change: probe this binding"));
    }

    [Fact]
    public void BasicHttps_transport_with_no_credential_or_a_certificate_has_specific_unconfirmed_entries_and_the_rest_stays_unprobed()
    {
        // Platform matrix 1.2.0: specific entries from the probe evidence, left unconfirmed for a person to confirm.
        var security = (string mode, string credential) => new EnvironmentSoapSecurity
        {
            Binding = "basicHttpsBinding", SecurityMode = mode, ClientCredentialType = credential, SecuritySource = "declared",
        };
        foreach (var credential in new[] { "None", "Certificate" })
        {
            var (verdict, reasons, entry) = LinuxVerdicts.SoapPlatform(security("Transport", credential), TestMatrices.Soap);
            Assert.Equal((Verdicts.Compatible, $"net10.0/linux/basicHttpsBinding/Transport/{credential}"), (verdict, entry));
            Assert.Contains($"matrix entry net10.0/linux/basicHttpsBinding/Transport/{credential} not yet confirmed by a person", reasons);
        }

        var (basic, _, basicEntry) = LinuxVerdicts.SoapPlatform(security("Transport", "Basic"), TestMatrices.Soap);
        Assert.Equal((Verdicts.Unknown, "net10.0/linux/basicHttpsBinding/*/*"), (basic, basicEntry));
    }

    [Fact]
    public void WsHttp_message_level_certificate_signing_is_incompatible_on_Linux_on_probe_evidence_and_the_rest_unprobed()
    {
        var security = (string mode, string credential) => new EnvironmentSoapSecurity
        {
            Binding = "wsHttpBinding", SecurityMode = mode, ClientCredentialType = credential, SecuritySource = "declared",
        };
        var (verdict, reasons, entry) = LinuxVerdicts.SoapPlatform(security("TransportWithMessageCredential", "Certificate"), TestMatrices.Soap);
        Assert.Equal((Verdicts.Incompatible, "net10.0/linux/wsHttpBinding/TransportWithMessageCredential/Certificate"), (verdict, entry));
        Assert.Contains(reasons, r => r.Contains("UriFormatException") && r.Contains("passes on Windows"));
        Assert.Equal("backend_owner", TestMatrices.Platform.Entries.Single(e => e.Id == entry).Fix!.Who);

        Assert.Equal(Verdicts.Unknown, LinuxVerdicts.SoapPlatform(security("Transport", "None"), TestMatrices.Soap).Verdict);
        Assert.Equal(Verdicts.Unknown, LinuxVerdicts.SoapPlatform(security("TransportWithMessageCredential", "UserName"), TestMatrices.Soap).Verdict);
        Assert.Equal(Verdicts.RequiresChange, LinuxVerdicts.SoapPlatform(security("Message", "Windows"), TestMatrices.Soap).Verdict);
    }

    /// <summary>The wildcard rule (both matrices' "rules"): a wildcard entry may
    /// not assert that a call works for a binding whose behaviour depends on its
    /// security mode or credential — every binding in the matrices has one. Only
    /// a specific entry can. A wildcard may say a call does not work, needs a
    /// change, or is unprobed.</summary>
    [Theory]
    [InlineData("wcf-client-support-1.1.0.json", new[] { "supported", "supported_with_caveat" })]
    [InlineData("wcf-client-platform-1.2.0.json", new[] { "compatible" })]
    public void No_wildcard_entry_asserts_that_a_call_works(string file, string[] works)
    {
        using var document = JsonDocument.Parse(File.ReadAllBytes(TestMatrices.Schemas(file)));
        var offenders = document.RootElement.GetProperty("entries").EnumerateArray()
            .Where(e => e.GetProperty("securityMode").GetString() == "*" || e.GetProperty("credentialType").GetString() == "*")
            .Where(e => works.Contains(e.GetProperty("verdict").GetString()))
            .Select(e => e.GetProperty("id").GetString())
            .ToList();
        Assert.Empty(offenders);
        Assert.NotEmpty(document.RootElement.GetProperty("rules").EnumerateArray());
    }

    [Fact]
    public void Every_platform_entry_is_well_formed_and_says_who_changes_what_when_it_is_not_compatible()
    {
        using var document = JsonDocument.Parse(File.ReadAllBytes(TestMatrices.PlatformPath));
        var root = document.RootElement;
        var sources = root.GetProperty("sources").EnumerateArray().Select(s => s.GetProperty("id").GetString()!).ToHashSet();
        foreach (var entry in root.GetProperty("entries").EnumerateArray())
        {
            var id = entry.GetProperty("id").GetString()!;
            Assert.Equal($"net10.0/linux/{entry.GetProperty("binding").GetString()}/{entry.GetProperty("securityMode").GetString()}/" +
                         $"{entry.GetProperty("credentialType").GetString()}", id);
            var verdict = entry.GetProperty("verdict").GetString();
            Assert.Contains(verdict, new[] { "compatible", "requires_change", "incompatible", "unknown" });
            Assert.All(entry.GetProperty("sources").EnumerateArray(), s => Assert.Contains(s.GetString()!, sources));
            Assert.Contains(entry.GetProperty("confirmation").GetProperty("status").GetString(), new[] { "unconfirmed", "confirmed" });
            if (verdict == "unknown")
            {
                Assert.Equal("we", entry.GetProperty("fix").GetProperty("who").GetString());     // we probe it
            }
            if (verdict != "compatible")
            {
                var fix = entry.GetProperty("fix");
                Assert.Contains(fix.GetProperty("who").GetString(), new[] { "we", "backend_owner", "we_or_backend_owner" });
                Assert.False(string.IsNullOrWhiteSpace(fix.GetProperty("change").GetString()), id);
            }
        }
    }

    [Fact]
    public void The_binding_defaults_in_code_are_the_matrix_files_sourced_defaults()
    {
        var expected = Matrix.Defaults.ToDictionary(d => d.Key, d => (d.Value.SecurityMode, d.Value.TransportCredential, d.Value.MessageCredential));
        var actual = WcfSecurity.Defaults.ToDictionary(d => d.Key, d => (d.Value.Mode, d.Value.Transport, d.Value.Message));
        Assert.Equal(expected.OrderBy(k => k.Key), actual.OrderBy(k => k.Key));
    }
}
