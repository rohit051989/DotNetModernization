using Fingerprinting.Analysis;
using Fingerprinting.Outbound;
using Fingerprinting.Outbound.Cli;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>Outbound 1.6.0: SOAP clients built by a custom helper (AccountsApi's WCFClientHelper) from options-bound
/// configuration — one client per <c>CreateClient&lt;I&gt;(name)</c>, each with its binding, security mode, credential and
/// address per environment.</summary>
public class SoapHelperClientTests
{
    private const string Project = "src/Api/Api.csproj";

    private const string Settings = """
        public sealed class WcfSettings
        {
            public const string SectionName = "Wcf";
            public Dictionary<string, WcfBindingSettings> Bindings { get; set; } = new();
            public Dictionary<string, WcfClientSettings> Clients { get; set; } = new();
        }
        public sealed class WcfBindingSettings
        {
            public string BindingType { get; set; } = "BasicHttpsBinding";
            public string BindingMode { get; set; } = "Transport";
            public string ClientCredentialType { get; set; } = "None";
        }
        public sealed class WcfClientSettings
        {
            public string EndpointAddress { get; set; } = string.Empty;
            public string BindingName { get; set; } = string.Empty;
            public string CertificateName { get; set; } = string.Empty;
        }
        static class Registration
        {
            static void Add(IServiceCollection services, IConfiguration configuration) =>
                services.Configure<WcfSettings>(configuration.GetSection(WcfSettings.SectionName));
        }
        """;

    private const string Helper = """
        using System.Collections.Concurrent;
        using System.ServiceModel;
        public sealed class WCFClientHelper : IWCFClientHelper
        {
            private readonly WcfSettings _settings;
            private readonly ConcurrentDictionary<string, ChannelFactory> _factories = new();
            public WCFClientHelper(IOptions<WcfSettings> settings) { _settings = settings.Value; }

            public TChannel CreateClient<TChannel>(string clientName) where TChannel : class
            {
                var factory = (ChannelFactory<TChannel>)_factories.GetOrAdd(clientName, name => BuildFactory<TChannel>(name));
                return factory.CreateChannel();
            }

            private ChannelFactory<TChannel> BuildFactory<TChannel>(string clientName)
            {
                if (!_settings.Clients.TryGetValue(clientName, out var client)) throw new InvalidOperationException();
                if (!_settings.Bindings.TryGetValue(client.BindingName, out var bindingSettings)) throw new InvalidOperationException();
                if (!Uri.TryCreate(client.EndpointAddress, UriKind.Absolute, out var address)) throw new InvalidOperationException();
                var factory = new ChannelFactory<TChannel>(WcfBindingFactory.Create(client.BindingName, bindingSettings), new EndpointAddress(address));
                if (!string.IsNullOrWhiteSpace(client.CertificateName))
                {
                    factory.Credentials.ClientCertificate.Certificate = Load(client.CertificateName);
                }
                return factory;
            }
        }
        """;

    private const string Clients = """
        public sealed class CreditCheckClient
        {
            public const string ClientName = "CreditCheck";
            private readonly IWCFClientHelper _wcfClientHelper;
            public async Task<bool> CheckAsync(string id)
            {
                var client = _wcfClientHelper.CreateClient<ICreditCheckService>(ClientName);
                return await _wcfClientHelper.ChannelDisposalAsync(client, client.CheckCreditAsync(id));
            }
        }
        public sealed class BranchDirectoryClient
        {
            public const string ClientName = "BranchDirectory";
            private readonly IWCFClientHelper _wcfClientHelper;
            public async Task<string> FindAsync(string code)
            {
                var client = _wcfClientHelper.CreateClient<IBranchDirectoryService>(ClientName);
                return await client.GetBranchAsync(code);
            }
        }
        public sealed class LedgerClient
        {
            public const string ClientName = "Ledger";
            private readonly IWCFClientHelper _wcfClientHelper;
            public async Task PostAsync(string entry)
            {
                var client = _wcfClientHelper.CreateClient<ILedgerService>(ClientName);
                await client.PostEntryAsync(entry);
            }
        }
        """;

    private const string AppSettings = """
        { "Wcf": {
            "Bindings": {
              "SecureCertificateBinding": { "BindingType": "BasicHttpsBinding", "BindingMode": "Transport", "ClientCredentialType": "Certificate" },
              "ReferenceDataBinding": { "BindingType": "BasicHttpsBinding", "BindingMode": "Transport", "ClientCredentialType": "None" },
              "LegacyHttpBinding": { "BindingType": "BasicHttpBinding", "BindingMode": "None", "ClientCredentialType": "None" }
            },
            "Clients": {
              "CreditCheck": { "EndpointAddress": "https://creditcheck.corp.example/CreditCheckService.svc", "BindingName": "SecureCertificateBinding", "CertificateName": "CreditCheckClient" },
              "BranchDirectory": { "EndpointAddress": "https://refdata.corp.example/BranchDirectoryService.svc", "BindingName": "ReferenceDataBinding" },
              "Ledger": { "EndpointAddress": "http://ledgersvc01.corp.example/LedgerService.svc", "BindingName": "LegacyHttpBinding" }
            } } }
        """;

    private const string Sit = """
        { "Wcf": { "Clients": {
            "CreditCheck": { "EndpointAddress": "https://creditcheck-sit.corp.example/CreditCheckService.svc" },
            "BranchDirectory": { "EndpointAddress": "https://refdata-sit.corp.example/BranchDirectoryService.svc" },
            "Ledger": { "EndpointAddress": "http://ledgersvc-sit01.corp.example/LedgerService.svc" } } } }
        """;

    private static IReadOnlyList<Invocation> Detect()
    {
        var project = new OutboundInputProject(Project, Guid.Empty, null, [], []);
        var source = ProjectSource.FromText(Project, new Dictionary<string, string>
        {
            ["src/Api/Configuration/Settings.cs"] = Settings,
            ["src/Api/Wcf/WCFClientHelper.cs"] = Helper,
            ["src/Api/Clients/SoapClients.cs"] = Clients,
        });
        var config = RepositoryConfig.FromText([("src/Api/appsettings.json", AppSettings), ("src/Api/appsettings.SIT.json", Sit)]);
        return OutboundPipeline.Detect(Guid.NewGuid(), [(project, source)], config, soapMatrices: TestMatrices.Soap).Single().Invocations;
    }

    [Fact]
    public void Each_CreateClient_call_is_its_own_client_with_its_contract_and_name()
    {
        var soap = Detect().Where(i => i.Mechanism == Mechanisms.SoapClient).ToList();
        Assert.Equal(["IBranchDirectoryService", "ICreditCheckService", "ILedgerService"], soap.Select(i => i.Soap!.Contract).Order());
        Assert.DoesNotContain(soap, i => i.Soap!.Contract == "TChannel");
        Assert.All(soap, i => Assert.Equal(("config", "ChannelFactory"), (i.Soap!.BindingSource, i.Soap.ClientType)));
        Assert.Equal(["BranchDirectory", "CreditCheck", "Ledger"], soap.Select(i => i.Soap!.EndpointName).Order());
        Assert.All(soap, i => Assert.StartsWith("src/Api/Clients/SoapClients.cs:", i.CallSites.Single().FilePath + ":"));
    }

    [Fact]
    public void Binding_mode_and_credential_come_from_the_client_s_binding_section()
    {
        var soap = Detect().Where(i => i.Mechanism == Mechanisms.SoapClient).ToDictionary(i => i.Soap!.EndpointName!);
        Assert.Equal(("basicHttpsBinding", "Transport", "Certificate"), Security(soap["CreditCheck"]));
        Assert.Equal(("basicHttpsBinding", "Transport", "None"), Security(soap["BranchDirectory"]));
        Assert.Equal(("basicHttpBinding", "None", "None"), Security(soap["Ledger"]));

        // The certificate is attached only where the client names one, and carries the key that names it.
        var certificate = Assert.Single(soap["CreditCheck"].Credentials);
        Assert.Equal(("certificate", "Wcf:Clients:CreditCheck:CertificateName"), (certificate.Kind, certificate.KeyPath));
        Assert.Empty(soap["BranchDirectory"].Credentials);
        Assert.Empty(soap["Ledger"].Credentials);
        Assert.Equal(AuthDeclared.NoneDeclared, soap["Ledger"].AuthDeclared);

        static (string, string?, string?) Security(Invocation i) => (i.Soap!.Binding, i.Soap.SecurityMode, i.Soap.ClientCredentialType);
    }

    [Fact]
    public void Each_environment_has_its_own_address_and_security()
    {
        var ledger = Detect().Single(i => i.Soap?.EndpointName == "Ledger");
        Assert.Equal(("http", "ledgersvc01.corp.example"), (ledger.Endpoint.Scheme, ledger.Endpoint.Host));
        Assert.Equal(["default", "SIT"], ledger.EnvironmentBindings.Select(b => b.Environment));
        Assert.Equal(["ledgersvc01.corp.example", "ledgersvc-sit01.corp.example"], ledger.EnvironmentBindings.Select(b => b.Host));
        Assert.Equal(["src/Api/appsettings.json", "src/Api/appsettings.SIT.json"], ledger.EnvironmentBindings.Select(b => b.SourceFile));
        Assert.All(ledger.EnvironmentBindings, b => Assert.Equal("Wcf:Clients:Ledger:EndpointAddress", b.KeyPath));
        // SIT sets only the address: its binding is the default file's.
        Assert.All(ledger.EnvironmentBindings, b => Assert.Equal(("basicHttpBinding", "None", "declared"), (b.Soap!.Binding, b.Soap.SecurityMode, b.Soap.SecuritySource)));
        Assert.All(ledger.EnvironmentBindings, b => Assert.NotNull(b.RuntimeVerdict));
    }

    [Fact]
    public void Operations_are_followed_on_the_channel_CreateClient_returns()
    {
        var ledger = Detect().Single(i => i.Soap?.EndpointName == "Ledger");
        Assert.Equal("PostEntryAsync", Assert.Single(ledger.Operations).Member);
    }
}
