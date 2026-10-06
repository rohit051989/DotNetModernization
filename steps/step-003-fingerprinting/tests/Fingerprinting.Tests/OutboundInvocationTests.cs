using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Fingerprinting.Outbound;
using Fingerprinting.Outbound.Cli;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>Step 5, outbound-invocation-inventory — 29-STEPS-004-005-INVENTORIES.md
/// Part C and its acceptance criteria.</summary>
public class OutboundInvocationTests
{
    private static readonly Guid RepositoryId = Guid.Parse("11111111-2222-3333-4444-555555555555");

    private static IReadOnlyList<Invocation> Detect(
        string projectPath, Dictionary<string, string> sources, IReadOnlyList<(string Path, string Text)>? config = null,
        IReadOnlyList<UncLiteral>? unc = null) =>
        Run(projectPath, sources, config, unc).Single().Invocations;

    private static IReadOnlyList<ProjectInvocations> Run(
        string projectPath, Dictionary<string, string> sources, IReadOnlyList<(string Path, string Text)>? config = null,
        IReadOnlyList<UncLiteral>? unc = null, IReadOnlyList<(string Path, string Text)>? setParameters = null,
        IReadOnlyDictionary<string, string>? declarations = null)
    {
        var project = new OutboundInputProject(projectPath, Guid.Empty, null, [], unc ?? []);
        var source = ProjectSource.FromText(projectPath, sources);
        var repositoryConfig = RepositoryConfig.FromText(config ?? [])
            .WithDeployParameters(DeployParameterFiles.FromText(setParameters ?? [], [projectPath]), declarations ?? new Dictionary<string, string>());
        return OutboundPipeline.Detect(RepositoryId, [(project, source)], repositoryConfig);
    }

    private static OutboundInventoryArtifact Artifact(IReadOnlyList<ProjectInvocations> projects) => new()
    {
        ScannerVersion = OutboundPipeline.ScannerVersion,
        RepositoryId = RepositoryId,
        RepositorySlug = "fixture",
        SkipSource = "application-fingerprint",
        Summary = new OutboundSummary { InvocationCount = projects.Sum(p => p.Invocations.Count) },
        Projects = projects,
    };

    // ---------- SOAP: the WCF sample's hard case ----------

    private const string TestClient = """
        using System.ServiceModel;
        class ClientSettings
        {
            public int UtilityTcpPort { get; private set; }
            public int OrderTcpPort { get; private set; }
            public int ProductHttpsPort { get; private set; }
            public bool EnableHttpEndpoints { get; private set; }
            public static ClientSettings Load()
            {
                var settings = System.Configuration.ConfigurationManager.AppSettings;
                return new ClientSettings
                {
                    UtilityTcpPort = int.Parse(settings["Ports.UtilityTcp"] ?? "8101"),
                    OrderTcpPort = int.Parse(settings["Ports.OrderTcp"] ?? "8201"),
                    ProductHttpsPort = int.Parse(settings["Ports.ProductHttps"] ?? "8443"),
                    EnableHttpEndpoints = bool.Parse(settings["EnableHttpEndpoints"] ?? "false"),
                };
            }
        }
        class Program
        {
            static void Main()
            {
                var settings = ClientSettings.Load();
                Run(settings, null);
                if (settings.EnableHttpEndpoints)
                {
                    RunHttp(settings);
                }
            }
            static void Run(ClientSettings settings, X509Certificate2 cert)
            {
                using (var u = CreateTcpFactory<IUtilityService>("Utility", settings.UtilityTcpPort, requireClientCertificate: false, clientCert: null)) { }
                using (var o = CreateTcpFactory<IOrderService>("Order", settings.OrderTcpPort, requireClientCertificate: true, clientCert: cert)) { }
            }
            static void RunHttp(ClientSettings settings)
            {
                using (var u = CreateBasicHttpsFactory<IUtilityService>("Utility", settings.ProductHttpsPort)) { }
            }
            static ChannelFactory<T> CreateTcpFactory<T>(string name, int port, bool requireClientCertificate, X509Certificate2 clientCert)
            {
                var address = new EndpointAddress(new Uri($"net.tcp://localhost:{port}/{name}"));
                var binding = new NetTcpBinding(SecurityMode.Transport)
                {
                    Security = { Transport = { ClientCredentialType = requireClientCertificate ? TcpClientCredentialType.Certificate : TcpClientCredentialType.None } }
                };
                var factory = new ChannelFactory<T>(binding, address);
                if (requireClientCertificate)
                    factory.Credentials.ClientCertificate.Certificate = clientCert;
                return factory;
            }
            static ChannelFactory<T> CreateBasicHttpsFactory<T>(string name, int port)
            {
                var address = new EndpointAddress(new Uri($"https://localhost:{port}/{name}"));
                var binding = new BasicHttpBinding(BasicHttpSecurityMode.Transport);
                return new ChannelFactory<T>(binding, address);
            }
        }
        """;

    private const string TestClientConfig = """
        <configuration>
          <appSettings>
            <add key="Ports.UtilityTcp" value="8101" />
            <add key="Ports.OrderTcp" value="8201" />
            <add key="Ports.ProductHttps" value="8443" />
            <add key="EnableHttpEndpoints" value="false" />
          </appSettings>
        </configuration>
        """;

    [Fact]
    public void ChannelFactory_through_generic_helpers_resolves_each_call_site_on_its_own()
    {
        var invocations = Detect("src/Client/Client.csproj", new() { ["src/Client/Program.cs"] = TestClient },
            [("src/Client/App.config", TestClientConfig)]);

        Assert.Equal(3, invocations.Count);
        Assert.All(invocations, i => Assert.Equal(Mechanisms.SoapClient, i.Mechanism));

        var utility = Assert.Single(invocations, i => i.Soap!.Contract == "IUtilityService" && i.Soap.Binding == "netTcpBinding");
        Assert.Equal(("net.tcp", "localhost", 8101, "/Utility"), (utility.Endpoint.Scheme, utility.Endpoint.Host, utility.Endpoint.Port, utility.Endpoint.Path));
        Assert.Equal(Resolutions.Resolved, utility.Endpoint.Resolution);
        Assert.Equal("Transport", utility.Soap!.SecurityMode);
        Assert.Equal("None", utility.Soap.ClientCredentialType);
        Assert.Equal(AuthDeclared.NoneDeclared, utility.AuthDeclared);
        Assert.Empty(utility.Credentials);
        Assert.Equal(Verdicts.Incompatible, utility.LinuxCompatibility.Verdict);
        Assert.StartsWith("CreateTcpFactory", utility.Soap.Via);
        var port = Assert.Single(utility.EnvironmentBindings);
        Assert.Equal(("src/Client/App.config", "Ports.UtilityTcp"), (port.SourceFile, port.KeyPath));

        // The per-call certificate switch: true at this call site.
        var order = Assert.Single(invocations, i => i.Soap!.Contract == "IOrderService");
        Assert.Equal("Certificate", order.Soap!.ClientCredentialType);
        Assert.Equal(AuthDeclared.Declared, order.AuthDeclared);
        Assert.Equal("certificate", Assert.Single(order.Credentials).Kind);
        Assert.Equal(8201, order.Endpoint.Port);

        var https = Assert.Single(invocations, i => i.Soap!.Binding == "basicHttpBinding");
        Assert.Equal(("https", 8443), (https.Endpoint.Scheme, https.Endpoint.Port));
        Assert.Equal(Verdicts.Compatible, https.LinuxCompatibility.Verdict);
        Assert.Contains("settings.EnableHttpEndpoints", https.Soap!.Condition);
        Assert.Contains("= false", https.Soap.Condition);
    }

    [Fact]
    public void A_config_client_endpoint_gives_the_binding_and_a_netTcp_client_is_incompatible_a_basicHttp_one_compatible()
    {
        const string config = """
            <configuration>
              <system.serviceModel>
                <bindings>
                  <netTcpBinding><binding name="secure"><security mode="Transport"><transport clientCredentialType="Windows" /></security></binding></netTcpBinding>
                </bindings>
                <client>
                  <endpoint name="Account" address="net.tcp://WSSE0.saifg.rbc.com/AccountService.svc" binding="netTcpBinding" bindingConfiguration="secure" contract="Refs.IAccountService" />
                  <endpoint name="Catalog" address="http://catalog.local:8080/Catalog.svc" binding="basicHttpBinding" contract="Refs.ICatalogService" />
                </client>
              </system.serviceModel>
            </configuration>
            """;
        const string code = """
            class AccountClient : System.ServiceModel.ClientBase<IAccountService> { public AccountClient(string name) : base(name) { } }
            class Use { void Go() { var c = new AccountClient("Account"); } }
            """;

        var invocations = Detect("src/App/App.csproj", new() { ["src/App/Use.cs"] = code }, [("src/App/web.config", config)]);

        var account = Assert.Single(invocations, i => i.Soap!.Contract == "IAccountService");
        Assert.Equal(("config", "hand_written", "AccountClient"), (account.Soap!.BindingSource, account.Soap.ClientSource, account.Soap.ClientType));
        Assert.Equal(("net.tcp", "wsse0.saifg.rbc.com", 808), (account.Endpoint.Scheme, account.Endpoint.Host, account.Endpoint.Port));
        Assert.Equal("Windows", account.Soap.ClientCredentialType);
        Assert.Equal(Verdicts.Incompatible, account.LinuxCompatibility.Verdict);
        Assert.Contains(account.LinuxCompatibility.Reasons, r => r.StartsWith("netTcpBinding"));
        Assert.Contains(account.LinuxCompatibility.Reasons, r => r.StartsWith("Windows client credentials"));

        // Declared in config, never constructed: still recorded.
        var catalog = Assert.Single(invocations, i => i.Soap!.Contract == "ICatalogService");
        Assert.Equal("config_only", catalog.Soap!.ClientSource);
        Assert.Equal(Verdicts.Compatible, catalog.LinuxCompatibility.Verdict);
    }

    [Fact]
    public void A_generated_svcutil_reference_supplies_the_binding_when_nothing_else_does()
    {
        const string reference = """
            [System.CodeDom.Compiler.GeneratedCode("dotnet-svcutil", "1.0")]
            public partial class OrderClient : System.ServiceModel.ClientBase<IOrderService>
            {
                public enum EndpointConfiguration { NetTcpBinding_IOrderService }
                public OrderClient() : base(GetDefaultBinding(), GetDefaultEndpointAddress()) { }
                private static System.ServiceModel.Channels.Binding GetBindingForEndpoint(EndpointConfiguration endpointConfiguration)
                {
                    if ((endpointConfiguration == EndpointConfiguration.NetTcpBinding_IOrderService))
                    {
                        System.ServiceModel.NetTcpBinding result = new System.ServiceModel.NetTcpBinding();
                        result.Security.Mode = System.ServiceModel.SecurityMode.None;
                        return result;
                    }
                    throw new System.InvalidOperationException();
                }
                private static System.ServiceModel.EndpointAddress GetEndpointAddress(EndpointConfiguration endpointConfiguration)
                {
                    if ((endpointConfiguration == EndpointConfiguration.NetTcpBinding_IOrderService))
                    {
                        return new System.ServiceModel.EndpointAddress("net.tcp://orders.local:9000/Orders");
                    }
                    throw new System.InvalidOperationException();
                }
                private static System.ServiceModel.Channels.Binding GetDefaultBinding() => GetBindingForEndpoint(EndpointConfiguration.NetTcpBinding_IOrderService);
            }
            """;
        const string use = "class Use { void Go() { var c = new OrderClient(); } }";

        var invocation = Assert.Single(Detect("src/App/App.csproj", new()
        {
            ["src/App/Connected Services/Orders/Reference.cs"] = reference,
            ["src/App/Use.cs"] = use,
        }));

        Assert.Equal(("generated_reference", "generated"), (invocation.Soap!.BindingSource, invocation.Soap.ClientSource));
        Assert.Equal(("netTcpBinding", "None"), (invocation.Soap.Binding, invocation.Soap.SecurityMode));
        Assert.Equal(("orders.local", 9000), (invocation.Endpoint.Host, invocation.Endpoint.Port));
        Assert.Equal(Verdicts.Incompatible, invocation.LinuxCompatibility.Verdict);
    }

    // ---------- C3: normalisation ----------

    [Fact]
    public void Endpoints_normalise_and_never_keep_userinfo_query_or_fragment()
    {
        var endpoint = Endpoints.FromUrl("http://svc:pass@WSSE0.saifg.rbc.com:8080/Account.svc?wsdl#frag")!;
        Assert.Equal(("http", "wsse0.saifg.rbc.com", 8080, "/Account.svc"), (endpoint.Scheme, endpoint.Host, endpoint.Port, endpoint.Path));

        var partial = Endpoints.FromValue(new ResolvedValue([new TextPart("https://user:pw@api.local/v1/"), new HolePart("id"), new TextPart("?token=abc")]));
        Assert.Equal(Resolutions.Partial, partial.Resolution);
        Assert.Equal(("https", "api.local", "/v1/{…}"), (partial.Scheme, partial.Host, partial.Path));
        Assert.DoesNotContain(partial.Fragments, f => f.Contains("pw") || f.Contains("token"));
    }

    // ---------- C4: environments and placeholders ----------

    [Fact]
    public void One_logical_endpoint_across_environment_files_is_one_invocation_with_a_binding_per_environment()
    {
        const string code = """
            using System.ServiceModel;
            class AccountClient
            {
                private readonly IConfiguration _configuration;
                public IAccountService Create()
                {
                    var factory = new ChannelFactory<IAccountService>(new NetTcpBinding(), new EndpointAddress(_configuration["Services:Account:Url"]));
                    return factory.CreateChannel();
                }
            }
            """;
        var invocations = Detect("src/AccountOpenAPI/AccountOpenAPI.csproj", new() { ["src/AccountOpenAPI/Services/AccountClient.cs"] = code },
        [
            ("src/AccountOpenAPI/appsettings.DEVOCP.json", """{ "Services": { "Account": { "Url": "net.tcp://wsse0-dev.saifg.rbc.com/AccountService.svc" } } }"""),
            ("src/AccountOpenAPI/appsettings.PROD.json", """{ "Services": { "Account": { "Url": "net.tcp://wsse0.saifg.rbc.com/AccountService.svc" } } }"""),
        ]);

        var invocation = Assert.Single(invocations);
        Assert.Equal(2, invocation.EnvironmentBindings.Count);
        Assert.Equal(["DEVOCP", "PROD"], invocation.EnvironmentBindings.Select(b => b.Environment));
        Assert.Equal(["wsse0-dev.saifg.rbc.com", "wsse0.saifg.rbc.com"], invocation.EnvironmentBindings.Select(b => b.Host));
        Assert.All(invocation.EnvironmentBindings, b => Assert.Equal("Services:Account:Url", b.KeyPath));
        // No default file sets it: the default endpoint waits on the key.
        Assert.Equal(Resolutions.Unresolved, invocation.Endpoint.Resolution);
        Assert.Equal("config:Services:Account:Url", invocation.Endpoint.Placeholder);
        Assert.Equal(Verdicts.Incompatible, invocation.LinuxCompatibility.Verdict);
    }

    [Fact]
    public void Placeholders_and_environment_variables_are_recorded_unresolved_never_guessed()
    {
        const string code = """
            class Clients
            {
                void Go(IConfiguration configuration)
                {
                    var a = new HttpClient { BaseAddress = new Uri(configuration["Downstream:Url"]) };
                    var b = new HttpClient { BaseAddress = new Uri(Environment.GetEnvironmentVariable("SERVICE_URL")) };
                }
            }
            """;
        var invocations = Detect("src/Api/Api.csproj", new() { ["src/Api/Clients.cs"] = code },
            [("src/Api/appsettings.json", """{ "Downstream": { "Url": "${SERVICE_URL}" } }""")]);

        Assert.Equal(2, invocations.Count);
        Assert.All(invocations, i => Assert.Equal(Resolutions.Unresolved, i.Endpoint.Resolution));
        Assert.Contains(invocations, i => i.Endpoint.Placeholder == "${SERVICE_URL}");
        Assert.Contains(invocations, i => i.Endpoint.Placeholder == "env:SERVICE_URL");
        Assert.All(invocations, i => Assert.Null(i.Endpoint.Host));
    }

    // ---------- C5: secrets ----------

    [Fact]
    public void Connection_strings_yield_name_provider_and_server_host_only()
    {
        const string code = "class Data { void Go(IServiceCollection s, IConfiguration c) { s.AddDbContext<Ctx>(o => o.UseSqlServer(c.GetConnectionString(\"Orders\"))); } }";
        var invocation = Assert.Single(Detect("src/Api/Api.csproj", new() { ["src/Api/Data.cs"] = code },
        [
            ("src/Api/appsettings.json", """{ "ConnectionStrings": { "Orders": "Server=tcp:SQL01.corp.local,1433;Database=OrdersDb;User Id=orders_app;Password=pw" } }"""),
        ]));

        Assert.Equal(Mechanisms.Database, invocation.Mechanism);
        Assert.Equal(("Orders", "sqlserver", "credentials"), (invocation.Database!.Name, invocation.Database.Provider, invocation.Database.Authentication));
        Assert.Equal(("sql01.corp.local", 1433), (invocation.Endpoint.Host, invocation.Endpoint.Port));
        Assert.Equal(Verdicts.Compatible, invocation.LinuxCompatibility.Verdict);

        var json = DeterministicJson.Serialize(Artifact(Run("src/Api/Api.csproj", new() { ["src/Api/Data.cs"] = code },
        [
            ("src/Api/appsettings.json", """{ "ConnectionStrings": { "Orders": "Server=tcp:SQL01.corp.local,1433;Database=OrdersDb;User Id=orders_app;Password=pw" } }"""),
        ])));
        Assert.DoesNotContain("OrdersDb", json);
        Assert.DoesNotContain("orders_app", json);
    }

    [Fact]
    public async Task The_three_secret_fixture_produces_an_artifact_containing_none_of_its_secrets()
    {
        const string password = "Pa55w0rd-Fixture-7781";
        const string urlSecret = "UrlCr3dential-4402";
        const string apiKey = "ak_live_Fixture9Q2W3E4R";

        const string code = """
            class Payments
            {
                private readonly HttpClient _client;
                public Payments(IConfiguration configuration)
                {
                    _client = new HttpClient { BaseAddress = new Uri(configuration["Payments:Url"]) };
                    _client.DefaultRequestHeaders.Add("X-Api-Key", configuration["Payments:ApiKey"]);
                }
            }
            class Data { void Go(IServiceCollection s, IConfiguration c) { s.AddDbContext<Ctx>(o => o.UseSqlServer(c.GetConnectionString("Main"))); } }
            """;
        var config = $$"""
            {
              "ConnectionStrings": { "Main": "Server=db.internal;Database=Main;User Id=app;Password={{password}}" },
              "Payments": {
                "Url": "https://svc-user:{{urlSecret}}@payments.example.com:8443/v2/?signature={{urlSecret}}#{{urlSecret}}",
                "ApiKey": "{{apiKey}}"
              }
            }
            """;

        // 1.3.0: a SetParameters file mixing a URL, a path, a password, a
        // connection string and a plain property. Only the URL (linked to
        // the endpoint by parameters.xml) and the path may keep a value.
        const string setParamPassword = "SetP4ram-Secret-6630";
        const string setParamDatabaseUser = "setparam_db_user";
        var setParam = $$"""
            <parameters>
              <setParameter name="PaymentsUrl" value="https://payments-prod.example.com/v2/" />
              <setParameter name="ArchiveFolder" value="G:\Archive\Payments\" />
              <setParameter name="ServicePassword" value="{{setParamPassword}}" />
              <setParameter name="MainConnection" value="Server=db-prod.internal;Database=Main;User Id={{setParamDatabaseUser}};Password={{setParamPassword}}" />
              <setParameter name="BatchUser" value="PAYBATCH" />
            </parameters>
            """;
        const string declarations = """
            <parameters>
              <parameter name="PaymentsUrl"><parameterEntry kind="XmlFile" scope="x" match="/configuration/appSettings/add[@key='Payments:Url']/@value" /></parameter>
              <parameter name="MainConnection"><parameterEntry kind="XmlFile" scope="x" match="/configuration/connectionStrings/add[@name='Main']/@connectionString" /></parameter>
            </parameters>
            """;

        var projects = Run("src/Api/Api.csproj", new() { ["src/Api/Payments.cs"] = code }, [("src/Api/appsettings.json", config)],
            setParameters: [("deploy/Api/PROD/SetParam.xml", setParam)], declarations: new Dictionary<string, string> { ["src/Api"] = declarations });
        var artifact = Artifact(projects);
        var json = DeterministicJson.Serialize(artifact);

        Assert.DoesNotContain(password, json);
        Assert.DoesNotContain(urlSecret, json);
        Assert.DoesNotContain(apiKey, json);
        Assert.DoesNotContain("svc-user", json);
        Assert.DoesNotContain(setParamPassword, json);
        Assert.DoesNotContain(setParamDatabaseUser, json);
        Assert.DoesNotContain("PAYBATCH", json);

        // Every parameter is recorded as present; values only where allowed.
        var parameters = projects.Single().DeployParameters.ToDictionary(p => p.Name);
        Assert.Equal(("sensitive", null), (parameters["ServicePassword"].Kind, parameters["ServicePassword"].Value));
        Assert.Equal(("connection_string", null), (parameters["MainConnection"].Kind, parameters["MainConnection"].Value));
        Assert.Equal(("other", null), (parameters["BatchUser"].Kind, parameters["BatchUser"].Value));
        Assert.Equal(("path", @"G:\Archive\Payments\"), (parameters["ArchiveFolder"].Kind, parameters["ArchiveFolder"].Value));
        Assert.Equal(("url", "https://payments-prod.example.com:443/v2/"), (parameters["PaymentsUrl"].Kind, parameters["PaymentsUrl"].Value));
        Assert.Equal(("parameters_xml", "PROD"), (parameters["PaymentsUrl"].LinkMethod, parameters["PaymentsUrl"].Environment));
        // The connection string still yields its server host for the PROD binding — facts only.
        var database = Assert.Single(projects.Single().Invocations, i => i.Mechanism == Mechanisms.Database);
        Assert.Contains(database.EnvironmentBindings, b => b.Environment == "PROD" && b.Host == "db-prod.internal" && b.DeployParameter == "MainConnection");

        // What is kept: the endpoints, and that a key is configured and where.
        var invocations = projects.Single().Invocations;
        var http = Assert.Single(invocations, i => i.Mechanism == Mechanisms.HttpClient);
        Assert.Equal(("https", "payments.example.com", 8443, "/v2/"), (http.Endpoint.Scheme, http.Endpoint.Host, http.Endpoint.Port, http.Endpoint.Path));
        var key = Assert.Single(http.Credentials);
        Assert.Equal(("api_key", "Payments:ApiKey"), (key.Kind, key.KeyPath));
        Assert.Equal(AuthDeclared.Declared, http.AuthDeclared);
        Assert.Equal("db.internal", Assert.Single(invocations, i => i.Mechanism == Mechanisms.Database).Endpoint.Host);

        // And the file the step writes, schema-validated, is just as clean.
        var directory = Path.Combine(Path.GetTempPath(), "outbound-secrets-" + Guid.NewGuid().ToString("N"));
        try
        {
            var written = await File.ReadAllTextAsync(await OutboundInventoryCli.WriteArtifactAsync(artifact, directory));
            Assert.DoesNotContain(password, written);
            Assert.DoesNotContain(urlSecret, written);
            Assert.DoesNotContain(apiKey, written);
            Assert.DoesNotContain(setParamPassword, written);
            Assert.DoesNotContain(setParamDatabaseUser, written);
        }
        finally
        {
            Directory.Delete(directory, recursive: true);
        }
    }

    // ---------- C6: verdicts ----------

    [Fact]
    public void Kafka_with_GSSAPI_stated_in_code_requires_a_Kerberos_keytab()
    {
        const string code = """
            class Events
            {
                void Go()
                {
                    var config = new ProducerConfig { BootstrapServers = "kafka1.corp.local:9092,kafka2.corp.local:9092", SaslMechanism = SaslMechanism.Gssapi };
                    using var producer = new ProducerBuilder<string, string>(config).Build();
                    producer.Produce("orders.created", null);
                }
            }
            """;
        var invocation = Assert.Single(Detect("src/Api/Api.csproj", new() { ["src/Api/Events.cs"] = code }));

        Assert.Equal(Mechanisms.MessageProducer, invocation.Mechanism);
        Assert.Equal(("kafka", "gssapi"), (invocation.Messaging!.Transport, invocation.Messaging.Authentication));
        Assert.Equal(["orders.created"], invocation.Messaging.Topics);
        Assert.Equal(("kafka1.corp.local", 9092), (invocation.Endpoint.Host, invocation.Endpoint.Port));
        Assert.Equal(Verdicts.RequiresChange, invocation.LinuxCompatibility.Verdict);
        Assert.Contains("Kerberos keytab required", invocation.LinuxCompatibility.Reasons[0]);
    }

    [Fact]
    public void Kafka_SASL_in_configuration_gives_each_environment_its_own_verdict()
    {
        const string code = """
            class Events
            {
                void Go(IConfiguration configuration)
                {
                    var config = new ConsumerConfig { BootstrapServers = configuration["Kafka:BootstrapServers"] };
                    configuration.GetSection("Kafka").Bind(config);
                    using var consumer = new ConsumerBuilder<string, string>(config).Build();
                    consumer.Subscribe("payments");
                }
            }
            """;
        var invocation = Assert.Single(Detect("src/Api/Api.csproj", new() { ["src/Api/Events.cs"] = code },
        [
            ("src/Api/appsettings.json", """{ "Kafka": { "BootstrapServers": "kafka.corp.local:9092", "sasl.mechanism": "GSSAPI" } }"""),
            ("src/Api/appsettings.DEVOCP.json", """{ "Kafka": { "BootstrapServers": "kafka.apps.ocp.local:9093", "sasl.mechanism": "SCRAM-SHA-512" } }"""),
        ]));

        Assert.Equal(Mechanisms.MessageConsumer, invocation.Mechanism);
        var byEnvironment = invocation.EnvironmentBindings.ToDictionary(b => b.Environment);
        Assert.Equal(("gssapi", Verdicts.RequiresChange), (byEnvironment["default"].Authentication, byEnvironment["default"].LinuxVerdict));
        Assert.Equal(("scram", Verdicts.Compatible), (byEnvironment["DEVOCP"].Authentication, byEnvironment["DEVOCP"].LinuxVerdict));
        Assert.Equal("kafka.apps.ocp.local", byEnvironment["DEVOCP"].Host);
        // The summary is the worst environment.
        Assert.Equal(Verdicts.RequiresChange, invocation.LinuxCompatibility.Verdict);
    }

    [Fact]
    public void Kafka_SASL_is_unknown_only_where_nothing_states_it()
    {
        const string suppliedElsewhere = """
            class Events
            {
                void Go(ProducerConfig config)
                {
                    using var producer = new ProducerBuilder<string, string>(config).Build();
                }
            }
            """;
        Assert.Equal("unknown", Assert.Single(Detect("src/A/A.csproj", new() { ["src/A/E.cs"] = suppliedElsewhere })).Messaging!.Authentication);

        const string saslWithoutMechanism = """
            class Events
            {
                void Go()
                {
                    var config = new ProducerConfig { BootstrapServers = "k:9092", SecurityProtocol = SecurityProtocol.SaslSsl };
                    using var producer = new ProducerBuilder<string, string>(config).Build();
                }
            }
            """;
        var defaulted = Assert.Single(Detect("src/B/B.csproj", new() { ["src/B/E.cs"] = saslWithoutMechanism }));
        Assert.Equal(("gssapi", Verdicts.RequiresChange), (defaulted.Messaging!.Authentication, defaulted.LinuxCompatibility.Verdict));

        const string noSasl = """
            class Events
            {
                void Go()
                {
                    using var producer = new ProducerBuilder<string, string>(new ProducerConfig { BootstrapServers = "k:9092" }).Build();
                }
            }
            """;
        var plain = Assert.Single(Detect("src/C/C.csproj", new() { ["src/C/E.cs"] = noSasl }));
        Assert.Equal(("none", Verdicts.Compatible), (plain.Messaging!.Authentication, plain.LinuxCompatibility.Verdict));
    }

    [Fact]
    public void Each_environment_binding_carries_its_own_verdict_and_the_invocation_the_worst()
    {
        const string code = "class Data { void Go(IServiceCollection s, IConfiguration c) { s.AddDbContext<Ctx>(o => o.UseSqlServer(c.GetConnectionString(\"Main\"))); } }";
        var invocation = Assert.Single(Detect("src/Api/Api.csproj", new() { ["src/Api/Data.cs"] = code },
        [
            ("src/Api/appsettings.json", """{ "ConnectionStrings": { "Main": "Server=SQLWIN01;Database=Main;Integrated Security=true" } }"""),
            ("src/Api/appsettings.DEVOCP.json", """{ "ConnectionStrings": { "Main": "Server=mssql.apps.ocp.local,1433;Database=Main;User Id=app;Password=x" } }"""),
        ]));

        var byEnvironment = invocation.EnvironmentBindings.ToDictionary(b => b.Environment);
        Assert.Equal(Verdicts.RequiresChange, byEnvironment["default"].LinuxVerdict);
        Assert.Equal(Verdicts.Compatible, byEnvironment["DEVOCP"].LinuxVerdict);
        Assert.Equal(["SQL authentication"], byEnvironment["DEVOCP"].LinuxReasons);
        Assert.Equal(Verdicts.RequiresChange, invocation.LinuxCompatibility.Verdict);
    }

    [Fact]
    public void A_client_constructed_nowhere_and_configured_nowhere_is_unused_and_not_counted()
    {
        const string code = """
            class DeadClient : System.ServiceModel.ClientBase<ICatalogService>, ICatalogService
            {
                public int Count() => base.Channel.Count();
            }
            class Live { System.Threading.Tasks.Task Go(HttpClient http) => http.GetAsync("https://catalog.local/items"); }
            """;
        var project = Assert.Single(Run("src/Svc/Svc.csproj", new() { ["src/Svc/Clients.cs"] = code }));

        var dead = Assert.Single(project.Invocations, i => i.Mechanism == Mechanisms.SoapClient);
        Assert.Equal(Usages.Unused, dead.Usage);
        Assert.Equal(Usages.Used, Assert.Single(project.Invocations, i => i.Mechanism == Mechanisms.HttpClient).Usage);
        Assert.Equal(1, project.Summary.UnusedCount);
        Assert.Equal(1, project.Summary.CountByVerdict.Values.Sum());
        Assert.False(project.Summary.CountByMechanism.ContainsKey(Mechanisms.SoapClient));
        // Used first, unused last.
        Assert.Equal(Usages.Unused, project.Invocations[^1].Usage);
    }

    [Fact]
    public void Integrated_security_requires_change_msmq_ldap_are_incompatible_unc_requires_an_smb_mount()
    {
        const string code = """
            using System.DirectoryServices;
            class Infra
            {
                void Go()
                {
                    var queue = new System.Messaging.MessageQueue(@"FormatName:DIRECT=OS:mq01\private$\orders");
                    queue.Send("x");
                    var entry = new DirectoryEntry("LDAP://DC01.corp.local/DC=corp,DC=local");
                }
            }
            """;
        var invocations = Detect("src/Legacy/Legacy.csproj", new() { ["src/Legacy/Infra.cs"] = code },
            [("src/Legacy/web.config", """<configuration><connectionStrings><add name="Main" connectionString="Data Source=SQL01;Initial Catalog=Main;Integrated Security=SSPI" providerName="System.Data.SqlClient" /></connectionStrings></configuration>""")],
            [new UncLiteral("src/Legacy/Infra.cs", 12, 12, @"\\FILES01\Exports\alice\report.csv")]);

        Assert.Equal(Verdicts.RequiresChange, Assert.Single(invocations, i => i.Mechanism == Mechanisms.Database).LinuxCompatibility.Verdict);
        Assert.Equal(Verdicts.Incompatible, Assert.Single(invocations, i => i.Mechanism == Mechanisms.MessageProducer).LinuxCompatibility.Verdict);
        var ldap = Assert.Single(invocations, i => i.Mechanism == Mechanisms.Ldap);
        Assert.Equal((Verdicts.Incompatible, "dc01.corp.local"), (ldap.LinuxCompatibility.Verdict, ldap.Endpoint.Host));

        var share = Assert.Single(invocations, i => i.Mechanism == Mechanisms.FileShare);
        Assert.Equal(Verdicts.RequiresChange, share.LinuxCompatibility.Verdict);
        Assert.Equal(@"\\files01\Exports", share.FileShare!.Share);
        Assert.DoesNotContain("alice", DeterministicJson.Serialize(share));

        // Incompatible first: the list someone will act on.
        Assert.Equal(Verdicts.Incompatible, invocations[0].LinuxCompatibility.Verdict);
    }

    // ---------- C7: ids ----------

    [Fact]
    public void InvocationId_is_stable_across_rescans_and_one_dependency_from_several_call_sites_is_one_invocation()
    {
        const string code = """
            class Api
            {
                private readonly HttpClient _http = new HttpClient();
                Task A() => _http.GetAsync("https://inventory.local/items");
                Task B() => _http.GetAsync("https://inventory.local/items");
            }
            """;
        var first = Detect("src/Api/Api.csproj", new() { ["src/Api/Api.cs"] = code });
        var second = Detect("src/Api/Api.csproj", new() { ["src/Api/Api.cs"] = code });

        var invocation = Assert.Single(first);
        Assert.Equal(2, invocation.CallSites.Count);
        Assert.Matches("^[0-9a-f]{32}$", invocation.InvocationId);
        Assert.Equal(invocation.InvocationId, Assert.Single(second).InvocationId);
    }

    // ---------- 1.2.0: the operation each call site invokes ----------

    private const string Contracts = """
        using System.ServiceModel;
        [ServiceContract] public interface IUtilityService { [OperationContract] string Ping(); [OperationContract] System.DateTime GetServerTimeUtc(); }
        [ServiceContract] public interface IProductService { [OperationContract] int CreateProduct(string name); }
        """;

    [Fact]
    public void Operations_called_on_the_channel_of_each_helper_created_factory_are_recorded_per_call_site()
    {
        const string code = """
            using System.ServiceModel;
            class Program
            {
                static void Main()
                {
                    using (var utilityFactory = CreateTcpFactory<IUtilityService>("Utility", 8101))
                    {
                        var utility = utilityFactory.CreateChannel();
                        utility.Ping();
                        utility.GetServerTimeUtc();
                        ((ICommunicationObject)utility).Close();
                    }
                    using (var productFactory = CreateTcpFactory<IProductService>("Product", 8301))
                    {
                        productFactory.CreateChannel().CreateProduct("x");
                    }
                }
                static ChannelFactory<T> CreateTcpFactory<T>(string name, int port) =>
                    new ChannelFactory<T>(new NetTcpBinding(), new EndpointAddress(new System.Uri($"net.tcp://localhost:{port}/{name}")));
            }
            """;
        var invocations = Detect("src/Client/Client.csproj", new() { ["src/Client/Program.cs"] = code, ["src/Client/Contracts.cs"] = Contracts });

        var utility = Assert.Single(invocations, i => i.Soap!.Contract == "IUtilityService");
        Assert.Equal(["GetServerTimeUtc", "Ping"], utility.Operations.Select(o => o.Operation!).Order());
        Assert.All(utility.Operations, o => Assert.Equal((Resolutions.Resolved, "src/Client/Program.cs"), (o.Resolution, o.CallSite.FilePath)));
        Assert.Equal(9, utility.Operations.Single(o => o.Operation == "Ping").CallSite.LineStart);

        var product = Assert.Single(invocations, i => i.Soap!.Contract == "IProductService");
        Assert.Equal("CreateProduct", Assert.Single(product.Operations).Operation);
    }

    [Fact]
    public void A_proxy_passed_on_from_where_it_is_created_is_followed_through_receivers_of_its_type()
    {
        const string code = """
            using System.ServiceModel;
            class UtilityClient : ClientBase<IUtilityService>, IUtilityService
            {
                public UtilityClient() : base(new BasicHttpBinding(), new EndpointAddress("http://utility.local/Utility.svc")) { }
                public string Ping() => Channel.Ping();
                public System.DateTime GetServerTimeUtc() => Channel.GetServerTimeUtc();
            }
            class Form
            {
                static void Main() => new Presenter(new UtilityClient()).Show();
            }
            class Presenter
            {
                private readonly IUtilityService _service;
                public Presenter(IUtilityService service) { _service = service; }
                public void Show() { _service.Ping(); }
            }
            """;
        var invocation = Assert.Single(Detect("src/Win/Win.csproj", new() { ["src/Win/Form.cs"] = code, ["src/Win/Contracts.cs"] = Contracts }));

        var ping = Assert.Single(invocation.Operations);
        Assert.Equal(("Ping", Resolutions.Resolved), (ping.Operation, ping.Resolution));
        Assert.Contains("passed on", ping.Reason);
    }

    [Fact]
    public void The_service_contract_names_the_operations_when_a_domain_interface_shares_its_name()
    {
        const string code = """
            using System.ServiceModel;
            namespace Domain { public interface ICatalogService { void GetBrands(); } }
            namespace Proxy
            {
                [ServiceContract] public interface ICatalogService { [OperationContract] void GetBrands(); [OperationContract] void GetItems(); }
                class CatalogServiceClient : ClientBase<ICatalogService>, ICatalogService
                {
                    public CatalogServiceClient() : base(new BasicHttpBinding(), new EndpointAddress("http://catalog.local/Catalog.svc")) { }
                    public void GetBrands() => Channel.GetBrands();
                    public void GetItems() => Channel.GetItems();
                }
                class Controller
                {
                    private ICatalogService _service = new CatalogServiceClient();
                    void Load() { _service.GetBrands(); _service.GetItems(); }
                }
            }
            """;
        var invocation = Assert.Single(Detect("src/Win/Win.csproj", new() { ["src/Win/Code.cs"] = code }));

        Assert.Equal(["GetBrands", "GetItems"], invocation.Operations.Select(o => o.Operation!).Order());
    }

    [Fact]
    public void A_client_with_nothing_called_on_it_records_one_unresolved_operation_with_the_reason()
    {
        const string code = """
            using System.ServiceModel;
            class Program
            {
                static object Make() => new ChannelFactory<IRemote>(new BasicHttpBinding(), new EndpointAddress("http://remote.local/R.svc"));
            }
            """;
        var operation = Assert.Single(Assert.Single(Detect("src/C/C.csproj", new() { ["src/C/P.cs"] = code })).Operations);
        Assert.Equal(Resolutions.Unresolved, operation.Resolution);
        Assert.Null(operation.Operation);
        Assert.False(string.IsNullOrEmpty(operation.Reason));
    }

    [Fact]
    public void An_http_wrapper_records_the_verb_and_the_path_each_caller_passes()
    {
        const string code = """
            class HttpService
            {
                private readonly HttpClient _httpClient = new HttpClient();
                private readonly string _apiUrl = "https://localhost:5099/api/";
                public Task<string> HttpGet(string uri) => _httpClient.GetStringAsync($"{_apiUrl}{uri}");
            }
            class CatalogItems
            {
                private readonly HttpService _http;
                public Task List() => _http.HttpGet("catalog-items?pageSize=10");
                public Task One(int id) => _http.HttpGet($"catalog-items/{id}");
            }
            """;
        var invocation = Assert.Single(Detect("src/Admin/Admin.csproj", new() { ["src/Admin/Http.cs"] = code }));

        Assert.Equal(
            [("GET", "/api/catalog-items", Resolutions.Resolved), ("GET", "/api/catalog-items/{…}", Resolutions.Partial)],
            invocation.Operations.Select(o => (o.Verb!, o.Path!, o.Resolution)).Order());
    }

    [Fact]
    public void Relative_requests_through_a_client_with_a_base_address_are_joined_to_its_path()
    {
        const string code = """
            class Orders
            {
                private readonly HttpClient _client = new HttpClient { BaseAddress = new System.Uri("http://orders.local/v1/") };
                public Task Create() => _client.PostAsync("orders", null);
                public Task Remove(int id) => _client.DeleteAsync($"orders/{id}");
            }
            """;
        var invocation = Assert.Single(Detect("src/Shop/Shop.csproj", new() { ["src/Shop/Orders.cs"] = code }));

        Assert.Equal([("DELETE", "/v1/orders/{…}"), ("POST", "/v1/orders")], invocation.Operations.Select(o => (o.Verb!, o.Path!)).Order());
    }

    [Fact]
    public void Grpc_methods_called_on_the_stub_are_the_rpcs_without_the_async_suffix()
    {
        const string code = """
            using Grpc.Net.Client;
            class Program
            {
                static async Task Main()
                {
                    using var channel = GrpcChannel.ForAddress("https://greeter.local:5001");
                    var client = new Greeter.GreeterClient(channel);
                    await client.SayHelloAsync(new HelloRequest());
                    client.SayGoodbye(new GoodbyeRequest());
                }
            }
            """;
        var invocation = Assert.Single(Detect("src/G/G.csproj", new() { ["src/G/Program.cs"] = code }));

        Assert.Equal(["SayGoodbye", "SayHello"], invocation.Operations.Select(o => o.Operation!).Order());
        Assert.Contains(invocation.Operations, o => o.Member == "SayHelloAsync");
    }
}
