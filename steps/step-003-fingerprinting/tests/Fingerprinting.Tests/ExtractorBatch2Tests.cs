using Fingerprinting.Domain;
using Fingerprinting.Extractors;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>
/// Step 3 extractor batch 2 (signal registry 1.4.0): ApiUsageExtractor,
/// PathLiteralExtractor, the ConfigurationExtractor rewrite, and
/// FileIndicatorExtractor's repository-level pass. Secrets behaviour is proved
/// separately in ConfigurationExtractorSecretsTests.
/// </summary>
public sealed class ExtractorBatch2Tests
{
    // ---- ApiUsageExtractor ----

    [Fact]
    public async Task ApiUsage_MatchesMembersWithSyntaxOnlyConfidence()
    {
        using var repo = new TempRepo();
        repo.Write("Worker.cs", """
            using System;
            using System.Text;
            using System.Diagnostics;
            using Microsoft.Win32;
            class Worker
            {
                void Run(IHostBuilder host, IServiceCollection services, IApplicationBuilder app)
                {
                    var a = DateTime.Now;
                    var b = DateTime.UtcNow;
                    var c = DateTimeOffset.Now;
                    var e = Encoding.Default;
                    host.UseWindowsService();
                    services.AddHealthChecks();
                    app.MapHealthChecks("/healthz");
                    Process.Start("cmd.exe", "/c secret-args");
                    var key = Registry.LocalMachine;
                }
            }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        Assert.All(signals, s =>
        {
            Assert.Equal(SignalTypes.ApiInvocation, s.Type);
            Assert.True(s.ExtractionConfidence < 1.0m, $"{s.Name} reported {s.ExtractionConfidence}");
            Assert.All(s.Evidence, e => Assert.NotNull(e.LineStart));
        });
        Assert.Equal(
            ["System.DateTime.Now", "System.DateTimeOffset.Now"],
            Values(signals, "DATETIME_NOW_USAGE"));
        Assert.Equal(["System.Text.Encoding.Default"], Values(signals, "ENCODING_DEFAULT_USAGE"));
        Assert.Equal(["UseWindowsService"], Values(signals, "USE_WINDOWS_SERVICE_INVOCATION"));
        Assert.Equal(["AddHealthChecks"], Values(signals, "ADD_HEALTH_CHECKS_INVOCATION"));
        Assert.Equal(["MapHealthChecks"], Values(signals, "MAP_HEALTH_CHECKS_INVOCATION"));
        Assert.Equal(["System.Diagnostics.Process.Start"], Values(signals, "PROCESS_START_USAGE"));
        Assert.Equal(["Microsoft.Win32.Registry.LocalMachine"], Values(signals, "REGISTRY_ACCESS_USAGE"));
        Assert.Equal("Run", signals.First(s => s.Name == "DATETIME_NOW_USAGE").Evidence[0].Member);
        // Process.Start's arguments are never recorded.
        Assert.DoesNotContain("secret-args", DeterministicJson.Serialize(signals));
    }

    /// <summary>Registry 1.15.0: the forms that depend on the host's time zone are the same signal, each its own value.
    /// UtcNow, UTC kinds and a named zone are not matched.</summary>
    [Fact]
    public async Task ApiUsage_HostTimeZoneForms_AreDateTimeNowUsage()
    {
        using var repo = new TempRepo();
        repo.Write("Clock.cs", """
            using System;
            class Clock
            {
                DateTime Day() => DateTime.Today;
                DateTime Back(DateTime stored) => stored.ToLocalTime();
                DateTimeOffset Offset(DateTimeOffset at) => at.ToLocalTime();
                TimeZoneInfo Zone() => TimeZoneInfo.Local;
                DateTime Kind(DateTime t) => DateTime.SpecifyKind(t, DateTimeKind.Local);
                DateTime Fine() => DateTime.SpecifyKind(DateTime.UtcNow, DateTimeKind.Utc);
                DateTimeOffset AlsoFine() => DateTimeOffset.UtcNow;
                TimeZoneInfo Named() => TimeZoneInfo.FindSystemTimeZoneById("Europe/London");
            }
            """);
        repo.Write("App.csproj", "<Project Sdk=\"Microsoft.NET.Sdk\" />");

        var signals = await Extract(new ApiUsageExtractor(), repo);

        Assert.Equal(["System.DateTime.Today", "System.DateTimeKind.Local", "System.TimeZoneInfo.Local", "ToLocalTime"],
            Values(signals, "DATETIME_NOW_USAGE"));
        var toLocal = signals.Single(s => s.Name == "DATETIME_NOW_USAGE" && s.Value == "ToLocalTime");
        Assert.Equal(2, toLocal.Evidence.Count);
        Assert.Equal(0.80m, toLocal.ExtractionConfidence);
    }

    [Fact]
    public async Task ApiUsage_SystemDrawing_MatchesGdiTypesButNotPrimitives()
    {
        using var repo = new TempRepo();
        repo.Write("Thumbs.cs", """
            using System.Drawing;
            class Thumbs
            {
                Color Accent = Color.Red;
                Point Origin;
                Bitmap Make(Image source) { using var g = Graphics.FromImage(source); return new Bitmap(10, 10); }
            }
            """);
        repo.Write("NoImport.cs", "class Other { Bitmap B; }");

        var signals = await Extract(new ApiUsageExtractor(), repo);

        var drawing = signals.Where(s => s.Name == "SYSTEM_DRAWING_USAGE").ToList();
        Assert.All(drawing, s => Assert.Equal("Thumbs.cs", s.SourcePath));
        Assert.Equal(
            ["System.Drawing.Bitmap", "System.Drawing.Graphics", "System.Drawing.Image"],
            drawing.Select(s => s.Value!).OrderBy(v => v, StringComparer.Ordinal).ToList());
    }

    [Fact]
    public async Task ApiUsage_DirectoryServicesProtocols_IsNotMatched()
    {
        using var repo = new TempRepo();
        repo.Write("Ldap.cs", """
            using System.DirectoryServices.Protocols;
            class Ldap { LdapConnection C; }
            """);
        repo.Write("Ad.cs", """
            using System.DirectoryServices.AccountManagement;
            class Ad { void M() { using var ctx = new PrincipalContext(ContextType.Domain); } }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        var directory = Assert.Single(signals, s => s.Name == "DIRECTORY_SERVICES_USAGE");
        Assert.Equal("Ad.cs", directory.SourcePath);
        Assert.Equal("System.DirectoryServices.AccountManagement.PrincipalContext", directory.Value);
    }

    // ---- console input (registry 1.9.0) ----

    [Fact]
    public async Task ApiUsage_ConsoleInput_ReadsThatNeedAPerson_AreInteractive()
    {
        using var repo = new TempRepo();
        repo.Write("Menu.cs", """
            using System;
            class Menu
            {
                void Run()
                {
                    var choice = Console.ReadLine();
                    if (Console.ReadKey().Key == ConsoleKey.Q) return;
                    int c = System.Console.Read();
                }
            }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        Assert.Equal(["System.Console.Read", "System.Console.ReadKey", "System.Console.ReadLine"],
            Values(signals, "INTERACTIVE_CONSOLE_INPUT"));
        Assert.DoesNotContain(signals, s => s.Name == "CONSOLE_PAUSE_FOR_INPUT");
    }

    [Fact]
    public async Task ApiUsage_ConsoleInput_DiscardedReadIsAPause_NotInteractive()
    {
        // The WCF sample's Catalog.TestClient and Catalog.Host: "Press ENTER
        // to exit" / "to shut down". With no console the read returns at once.
        using var repo = new TempRepo();
        repo.Write("Program.cs", """
            using System;
            class Program
            {
                static void Main()
                {
                    Console.WriteLine("Done. Press ENTER to exit.");
                    Console.ReadLine();
                    _ = Console.Read();
                }
            }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        Assert.Equal(["System.Console.Read", "System.Console.ReadLine"], Values(signals, "CONSOLE_PAUSE_FOR_INPUT"));
        Assert.DoesNotContain(signals, s => s.Name == "INTERACTIVE_CONSOLE_INPUT");
    }

    [Fact]
    public async Task ApiUsage_ConsoleInput_PromptLibraries_OnlyWhereImported()
    {
        using var repo = new TempRepo();
        repo.Write("Spectre.cs", """
            using Spectre.Console;
            class Wizard
            {
                void Run()
                {
                    var name = AnsiConsole.Ask<string>("Name?");
                    var env = AnsiConsole.Prompt(new SelectionPrompt<string>().AddChoices("dev", "prod"));
                }
            }
            """);
        repo.Write("Sharp.cs", """
            using Sharprompt;
            class Setup { void Run() { var ok = Prompt.Confirm("Continue?"); } }
            """);
        repo.Write("Unrelated.cs", """
            class Prompt { public static bool Confirm(string s) => true; }
            class AnsiConsole { public static string Ask<T>(string s) => s; }
            class User { void Run() { Prompt.Confirm("x"); AnsiConsole.Ask<string>("y"); } }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        var interactive = signals.Where(s => s.Name == "INTERACTIVE_CONSOLE_INPUT").ToList();
        Assert.Equal(["Sharp.cs", "Spectre.cs"], interactive.Select(s => s.SourcePath).Distinct().OrderBy(p => p, StringComparer.Ordinal).ToList());
        Assert.Equal(["Sharprompt.Prompt.Confirm", "Spectre.Console.AnsiConsole.Ask", "Spectre.Console.AnsiConsole.Prompt",
                      "Spectre.Console.SelectionPrompt"], Values(signals, "INTERACTIVE_CONSOLE_INPUT"));
    }

    // ---- PathLiteralExtractor ----

    [Fact]
    public async Task PathLiteral_OneRowPerDistinctValue_WithMatchedValueEvidence()
    {
        using var repo = new TempRepo();
        repo.Write("Io.cs", """
            class Io
            {
                const string A = @"C:\Temp\in";
                const string B = "C:\\Temp\\in";
                const string C = @"G:\Archive";
                const string Share = @"\\fileserver01\drops\incoming";
                const string Regex = @"\\d+\\w";
                const string Url = "http://example.com/path";
            }
            """);

        var signals = await Extract(new PathLiteralExtractor(), repo);

        var windows = signals.Where(s => s.Name == PathLiteralExtractor.WindowsPathLiteral).ToList();
        Assert.Equal([@"C:\Temp\in", @"G:\Archive"], windows.Select(s => s.Value!).OrderBy(v => v, StringComparer.Ordinal).ToList());
        var temp = windows.Single(s => s.Value == @"C:\Temp\in");
        Assert.Equal(2, temp.OccurrenceCount);
        Assert.All(temp.Evidence, e => Assert.Equal(@"C:\Temp\in", e.MatchedValue));
        Assert.Equal(SignalTypes.Literal, temp.Type);

        var unc = Assert.Single(signals, s => s.Name == PathLiteralExtractor.UncPathLiteral);
        Assert.Equal(@"\\fileserver01\drops\incoming", unc.Value);
    }

    // ---- SetParameters files (registry 1.7.0) ----

    private const string SetParam = """
        <parameters>
          <setParameter name="FundsTransferWSURL" value="http://appsrv0341/FundsTransferWS/FundsTransferWS.asmx" />
          <setParameter name="LogDirectory" value="G:\Logs\WcfCatalog\FundsTransfer\" />
          <setParameter name="ServicePassword" value="G:\NotAPath-Secret-5521" />
          <setParameter name="TransfersDb" value="Server=sql01;Database=Transfers;Integrated Security=true;Password=Hidden-8831" />
          <setParameter name="Qualified" value="http://ftmt.corp.example.com/x.asmx" />
        </parameters>
        """;

    [Fact]
    public async Task SetParam_values_yield_path_literals_and_unqualified_hosts_and_never_secrets()
    {
        using var repo = new TempRepo();
        var files = Fingerprinting.Analysis.DeployParameterFiles.FromText(
            [("CustomFiles/Test/SetParamFiles/DEV/SetParam.xml", SetParam)], ["src/Test/Test.csproj"]);
        Assert.Equal(("DEV", "src/Test/Test.csproj"), (files[0].Environment, files[0].ProjectPath));

        var literals = await Extract(new PathLiteralExtractor(), repo, files);
        var path = Assert.Single(literals, s => s.Name == PathLiteralExtractor.WindowsPathLiteral);
        Assert.Equal((@"G:\Logs\WcfCatalog\FundsTransfer\", "CustomFiles/Test/SetParamFiles/DEV/SetParam.xml", 3),
            (path.Value, path.SourcePath, path.Evidence[0].LineStart));
        var host = Assert.Single(literals, s => s.Name == PathLiteralExtractor.UnqualifiedHostnameUrl);
        Assert.Equal(("appsrv0341", SignalCategories.EndpointIndicator), (host.Value, host.Category));

        var config = await Extract(new ConfigurationExtractor(), repo, files);
        Assert.Contains(config, s => s.Name == "SENSITIVE_CONFIG_KEY" && s.Value == "ServicePassword");
        Assert.Contains(config, s => s.Name == "CONNECTION_STRING_CONFIG" && s.Value == "TransfersDb");
        Assert.Contains(config, s => s.Name == "WINDOWS_AUTH_CONNECTION_STRING_CONFIG" && s.Value == "TransfersDb");

        var json = DeterministicJson.Serialize(literals.Concat(config).ToList());
        Assert.DoesNotContain("Secret-5521", json);
        Assert.DoesNotContain("Hidden-8831", json);
        Assert.DoesNotContain("sql01", json);
    }

    [Theory]
    [InlineData("http://appsrv0341/x", true)]
    [InlineData("net.tcp://APPSRV0341:808/x", true)]
    [InlineData("http://localhost:8090/x", false)]
    [InlineData("http://10.1.2.3/x", false)]
    [InlineData("https://ftmt.corp.example.com/x", false)]
    [InlineData("http://user:pw@appsrv9/x?token=abc", true)]
    public void Unqualified_hosts_in_urls(string url, bool unqualified) =>
        Assert.Equal(unqualified, Fingerprinting.Analysis.Hostnames.UnqualifiedInUrls(url).Any());

    [Fact]
    public void MatchedValue_IsOmittedFromJsonWhenNull()
    {
        var json = DeterministicJson.Serialize(new Evidence { LineStart = 1, LineEnd = 1 });
        Assert.DoesNotContain("matchedValue", json);
    }

    // ---- ConfigurationExtractor ----

    [Fact]
    public async Task Config_ReadsEnvironmentAppSettings_WithLineNumbers_AndSerilogSinks()
    {
        using var repo = new TempRepo();
        repo.Write("appsettings.DEV.json", """
            {
              // comments are allowed, as .NET's loader allows them
              "Serilog": {
                "WriteTo": [
                  { "Name": "Console" },
                  { "Name": "File", "Args": { "path": "G:\\Logs\\App\\" } },
                  { "Name": "Async", "Args": { "configure": [ { "Name": "File", "Args": { "path": "C:\\logs\\async.log" } } ] } }
                ]
              },
              "Kafka": { "BootstrapServers": "broker-01.corp:9092" },
              "Redis": { "Configuration": "cache-01.corp:6380", "Password": "hunter2" },
              "Vault": { "Address": "https://vault.corp", "RoleId": "abc" },
              "KeyVaultName": "azure-kv-01",
              "ConnectionStrings": { "Cache": "x" }
            },
            """);

        var signals = await Extract(new ConfigurationExtractor(), repo);
        var text = DeterministicJson.Serialize(signals);

        var sinks = signals.Where(s => s.Name == "SERILOG_FILE_SINK_CONFIG").ToList();
        Assert.Equal([@"C:\logs\async.log", @"G:\Logs\App\"], sinks.Select(s => s.Value!).OrderBy(v => v, StringComparer.Ordinal).ToList());
        Assert.All(signals, s => Assert.All(s.Evidence, e => Assert.NotNull(e.LineStart)));
        Assert.Equal(6, sinks.Single(s => s.Value == @"G:\Logs\App\").Evidence[0].LineStart);

        Assert.Equal(["Kafka:BootstrapServers"], Values(signals, "KAFKA_BOOTSTRAP_CONFIG"));
        Assert.Equal(["Redis"], Values(signals, "REDIS_CONNECTION_CONFIG"));
        Assert.Equal(["Vault"], Values(signals, "VAULT_CONFIG"));
        Assert.DoesNotContain("broker-01", text);
        Assert.DoesNotContain("cache-01", text);
        Assert.DoesNotContain("hunter2", text);
        Assert.DoesNotContain("vault.corp", text);
    }

    [Fact]
    public async Task Config_SeparatesWcfServiceAndClientEndpoints()
    {
        using var repo = new TempRepo();
        repo.Write("web.config", """
            <configuration>
              <system.serviceModel>
                <services><service name="S"><endpoint contract="IOrders" binding="basicHttpBinding" /></service></services>
                <client><endpoint name="Ledger" contract="ILedger" binding="netTcpBinding" address="net.tcp://ledger/svc" /></client>
              </system.serviceModel>
            </configuration>
            """);

        var signals = await Extract(new ConfigurationExtractor(), repo);

        Assert.Equal(["IOrders"], Values(signals, "WCF_SERVICE_ENDPOINT_CONFIG"));
        Assert.Equal(["ILedger"], Values(signals, "WCF_CLIENT_ENDPOINT_CONFIG"));
        Assert.Equal(["basicHttpBinding", "netTcpBinding"], Values(signals, "WCF_BINDING_CONFIG"));
        Assert.Equal(["netTcpBinding"], Values(signals, "WCF_CLIENT_BINDING_CONFIG"));
        Assert.Equal(["basicHttpBinding"], Values(signals, "WCF_SERVICE_BINDING_CONFIG"));   // registry 1.13.0
    }

    [Fact]
    public async Task Config_NetTcpServiceWithHttpClient_IsNotANetTcpClient()
    {
        // The false positive wcf-nettcp-client used to have: NetTcp on the
        // service side, HTTP on the client side. WCF_BINDING_CONFIG sees
        // netTcpBinding; the client binding signal must not.
        using var repo = new TempRepo();
        repo.Write("web.config", """
            <configuration>
              <system.serviceModel>
                <services><service name="Orders"><endpoint contract="IOrders" binding="netTcpBinding" /></service></services>
                <client><endpoint name="Ledger" contract="ILedger" binding="basicHttpBinding" address="https://ledger/svc" /></client>
              </system.serviceModel>
            </configuration>
            """);

        var signals = await Extract(new ConfigurationExtractor(), repo);

        Assert.Contains("netTcpBinding", Values(signals, "WCF_BINDING_CONFIG"));
        Assert.Equal(["basicHttpBinding"], Values(signals, "WCF_CLIENT_BINDING_CONFIG"));
        Assert.Equal(["netTcpBinding"], Values(signals, "WCF_SERVICE_BINDING_CONFIG"));   // registry 1.13.0
    }

    [Fact]
    public async Task Config_CustomBindingOnANonHttpTransport_RecordsItsTransport()
    {
        // Registry 1.13.0: "customBinding" alone says nothing about the transport.
        using var repo = new TempRepo();
        repo.Write("app.config", """
            <configuration>
              <system.serviceModel>
                <bindings>
                  <customBinding>
                    <binding name="TcpBinary"><binaryMessageEncoding /><tcpTransport /></binding>
                    <binding name="PipeBinary"><binaryMessageEncoding /><namedPipeTransport /></binding>
                    <binding name="HttpsText"><textMessageEncoding /><httpsTransport /></binding>
                  </customBinding>
                </bindings>
                <services>
                  <service name="Orders"><endpoint contract="IOrders" binding="customBinding" bindingConfiguration="PipeBinary" /></service>
                </services>
                <client>
                  <endpoint name="Ledger" contract="ILedger" binding="customBinding" bindingConfiguration="TcpBinary" address="net.tcp://ledger/svc" />
                  <endpoint name="Audit" contract="IAudit" binding="customBinding" bindingConfiguration="HttpsText" address="https://audit/svc" />
                </client>
              </system.serviceModel>
            </configuration>
            """);

        var signals = await Extract(new ConfigurationExtractor(), repo);

        Assert.Equal(["customBinding", "customBinding:tcpTransport"], Values(signals, "WCF_CLIENT_BINDING_CONFIG"));
        Assert.Equal(["customBinding:namedPipeTransport"], Values(signals, "WCF_SERVICE_BINDING_CONFIG"));
        Assert.Equal(["customBinding"], Values(signals, "WCF_BINDING_CONFIG"));   // unchanged: the declared binding
    }

    [Fact]
    public async Task Config_DefaultEndpoints_FromNonHttpBaseAddresses_AndProtocolMapping()
    {
        // Registry 1.13.0: a <service> with no endpoint of its own gets one per base address (WCF 4).
        using var repo = new TempRepo();
        repo.Write("web.config", """
            <configuration>
              <system.serviceModel>
                <protocolMapping><add scheme="net.pipe" binding="customBinding" bindingConfiguration="Pipe" /></protocolMapping>
                <bindings><customBinding><binding name="Pipe"><namedPipeTransport /></binding></customBinding></bindings>
                <services>
                  <service name="Defaults">
                    <host><baseAddresses>
                      <add baseAddress="net.tcp://localhost:808/defaults" />
                      <add baseAddress="net.pipe://localhost/defaults" />
                      <add baseAddress="http://localhost/defaults" />
                    </baseAddresses></host>
                  </service>
                  <service name="Explicit">
                    <host><baseAddresses><add baseAddress="net.msmq://localhost/private/explicit" /></baseAddresses></host>
                    <endpoint address="" contract="IExplicit" binding="basicHttpBinding" />
                  </service>
                </services>
              </system.serviceModel>
            </configuration>
            """);

        var signals = await Extract(new ConfigurationExtractor(), repo);

        // The explicit service's net.msmq base address is not used by its HTTP endpoint: not a default endpoint.
        Assert.Equal(["basicHttpBinding", "customBinding:namedPipeTransport", "netTcpBinding"], Values(signals, "WCF_SERVICE_BINDING_CONFIG"));
    }

    [Fact]
    public async Task ApiUsage_SerilogSinksInCode_FileWithItsPath_AndConsole()
    {
        // Registry 1.14.0: Serilog sinks configured in code, also inside a wrapper's lambda.
        using var repo = new TempRepo();
        repo.Write("Program.cs", """
            using Serilog;
            Log.Logger = new LoggerConfiguration()
                .WriteTo.Console()
                .WriteTo.File(@"C:\logs\app-.log", rollingInterval: RollingInterval.Day)
                .WriteTo.Async(a => a.File(path: "logs/async.log"))
                .WriteTo.Conditional(e => true, wt => wt.RollingFile(LogPath()))
                .CreateLogger();
            """);
        // No Serilog in the file: File and Console are only method names here.
        repo.Write("Exporter.cs", """
            class Exporter
            {
                void Run(Writer w) { w.WriteTo.File("report.csv"); w.Console(); }
            }
            """);
        // Serilog written in the file without a using (a global using elsewhere).
        repo.Write("Logging.cs", """
            static class Logging
            {
                public static LoggerConfiguration Configure(LoggerConfiguration c) =>
                    c.WriteTo.Async(sinks => sinks.Console()).AuditTo.File(@"\\share\audit.log");
            }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        Assert.Equal([null, "C:\\logs\\app-.log", "\\\\share\\audit.log", "logs/async.log"],
            signals.Where(s => s.Name == ApiUsageExtractor.SerilogFileSinkUsage).Select(s => s.Value).Order(StringComparer.Ordinal).ToList());
        Assert.DoesNotContain(signals, s => s.SourcePath == "Exporter.cs");
        // The sink's own line, not the line the fluent chain starts on (line 2).
        Assert.Equal(4, signals.Single(s => s.Value == @"C:\logs\app-.log").Evidence[0].LineStart);
        Assert.Equal(3, signals.Single(s => s.Name == ApiUsageExtractor.SerilogConsoleSinkUsage && s.SourcePath == "Program.cs").Evidence[0].LineStart);
        Assert.Equal(["Logging.cs", "Program.cs"],
            signals.Where(s => s.Name == ApiUsageExtractor.SerilogConsoleSinkUsage).Select(s => s.SourcePath).Order().ToList());
        Assert.All(signals.Where(s => s.Name == ApiUsageExtractor.SerilogConsoleSinkUsage), s => Assert.Equal("Console", s.Value));
    }

    [Fact]
    public async Task Config_SerilogConsoleSink_BesideAndInsideAsync()
    {
        // Registry 1.14.0: a Console sink in appsettings, at the top level or inside an Async sink's configure.
        using var repo = new TempRepo();
        repo.Write("appsettings.json", """
            { "Serilog": { "WriteTo": [
                { "Name": "Console" },
                { "Name": "File", "Args": { "path": "G:\\Logs\\app-.log" } } ] } }
            """);
        repo.Write("appsettings.UAT.json", """
            { "Serilog": { "WriteTo": [ { "Name": "Async", "Args": { "configure": [ { "Name": "Console" } ] } } ] } }
            """);
        repo.Write("appsettings.Production.json", """
            { "Serilog": { "WriteTo": [ { "Name": "File", "Args": { "path": "logs/app.log" } } ] }, "Console": { "Name": "Console" } }
            """);

        var signals = await Extract(new ConfigurationExtractor(), repo);

        Assert.Equal(["appsettings.UAT.json", "appsettings.json"],
            signals.Where(s => s.Name == "SERILOG_CONSOLE_SINK_CONFIG").Select(s => s.SourcePath).Order(StringComparer.Ordinal).ToList());
        Assert.Equal(["G:\\Logs\\app-.log", "logs/app.log"], Values(signals, "SERILOG_FILE_SINK_CONFIG"));
    }

    [Fact]
    public async Task ApiUsage_CustomBindingTransportElements_OnBothSides()
    {
        using var repo = new TempRepo();
        repo.Write("Client.cs", """
            using System.ServiceModel;
            using System.ServiceModel.Channels;
            class Client
            {
                ILedger Open() => new ChannelFactory<ILedger>(
                    new CustomBinding(new BinaryMessageEncodingBindingElement(), new TcpTransportBindingElement()),
                    "net.tcp://ledger/svc").CreateChannel();
            }
            """);
        // A factory created target-typed is still a client file.
        repo.Write("Reporting.cs", """
            using System.ServiceModel;
            sealed class Reporting
            {
                private readonly ChannelFactory<IReporting> _factory = new(new NetNamedPipeBinding(), new EndpointAddress("net.pipe://localhost/r"));
            }
            """);
        repo.Write("Program.cs", """
            using CoreWCF;
            using CoreWCF.Channels;
            using CoreWCF.Configuration;
            var app = WebApplication.CreateBuilder(args).Build();
            app.UseServiceModel(sb => sb.AddServiceEndpoint<Orders, IOrders>(
                new CustomBinding(new BinaryMessageEncodingBindingElement(), new NamedPipeTransportBindingElement()), "/orders"));
            app.Run();
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        Assert.Equal(["System.ServiceModel.Channels.TcpTransportBindingElement", "System.ServiceModel.CustomBinding",
                "System.ServiceModel.NetNamedPipeBinding"],
            Values(signals, "WCF_CLIENT_BINDING_USAGE"));
        Assert.Equal(["CoreWCF.Channels.NamedPipeTransportBindingElement", "CoreWCF.CustomBinding"],
            Values(signals, "WCF_SERVICE_BINDING_USAGE"));
    }

    [Fact]
    public async Task ApiUsage_WcfClientBinding_OnlyInClientCode()
    {
        using var repo = new TempRepo();
        // svcutil-shaped client: HTTP binding.
        repo.Write("Reference.cs", """
            public partial class LedgerClient : System.ServiceModel.ClientBase<ILedger>
            {
                private static System.ServiceModel.Channels.Binding GetBinding() => new System.ServiceModel.BasicHttpBinding();
            }
            """);
        // Self-hosted service on NetTcp: not a client.
        repo.Write("Host.cs", """
            class Host
            {
                void Start()
                {
                    var host = new ServiceHost(typeof(Orders));
                    host.AddServiceEndpoint(typeof(IOrders), new NetTcpBinding(), "net.tcp://0.0.0.0/orders");
                }
            }
            """);
        // Code-configured NetTcp client.
        repo.Write("Audit.cs", """
            class Audit
            {
                IAudit Open() => new ChannelFactory<IAudit>(new NetTcpBinding(), "net.tcp://audit/svc").CreateChannel();
            }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        var bindings = signals.Where(s => s.Name == "WCF_CLIENT_BINDING_USAGE")
            .Select(s => $"{s.SourcePath} {s.Value}").OrderBy(v => v, StringComparer.Ordinal).ToList();
        Assert.Equal(
            ["Audit.cs System.ServiceModel.NetTcpBinding", "Reference.cs System.ServiceModel.BasicHttpBinding"],
            bindings);
        // Registry 1.13.0: the self-hosted service's binding is the service's.
        Assert.Equal(["Host.cs System.ServiceModel.NetTcpBinding"], signals.Where(s => s.Name == "WCF_SERVICE_BINDING_USAGE")
            .Select(s => $"{s.SourcePath} {s.Value}").ToList());
    }

    [Fact]
    public async Task ApiUsage_WcfServiceBinding_CoreWcfServiceBuilderAndLegacyNonHttpBindings()
    {
        using var repo = new TempRepo();
        // CoreWCF on .NET: the generic AddServiceEndpoint<TService, TContract> on the service builder.
        repo.Write("Program.cs", """
            using CoreWCF;
            using CoreWCF.Configuration;
            var builder = WebApplication.CreateBuilder(args);
            builder.WebHost.UseNetTcp(8089);
            var app = builder.Build();
            app.UseServiceModel(sb =>
            {
                sb.AddService<Orders>();
                sb.AddServiceEndpoint<Orders, IOrders>(new NetTcpBinding(), "/orders");
                sb.AddServiceEndpoint<Orders, IOrders>(new BasicHttpBinding(), "/orders.svc");
            });
            app.Run();
            """);
        // .NET Framework self-host over named pipes and MSMQ.
        repo.Write("Host.cs", """
            class Host
            {
                void Start()
                {
                    var host = new System.ServiceModel.ServiceHost(typeof(Ledger));
                    host.AddServiceEndpoint(typeof(ILedger), new System.ServiceModel.NetNamedPipeBinding(), "net.pipe://localhost/ledger");
                    host.AddServiceEndpoint(typeof(ILedger), new NetMsmqBinding(), "net.msmq://localhost/private/ledger");
                }
            }
            """);
        // A queued client: MSMQ binding on the client side.
        repo.Write("Queue.cs", """
            class Queue
            {
                ILedger Open() => new ChannelFactory<ILedger>(new NetMsmqBinding(), "net.msmq://ledger/private/q").CreateChannel();
            }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        Assert.Equal(
            ["Host.cs System.ServiceModel.NetMsmqBinding", "Host.cs System.ServiceModel.NetNamedPipeBinding",
             "Program.cs CoreWCF.BasicHttpBinding", "Program.cs CoreWCF.NetTcpBinding"],
            signals.Where(s => s.Name == "WCF_SERVICE_BINDING_USAGE").Select(s => $"{s.SourcePath} {s.Value}")
                .OrderBy(v => v, StringComparer.Ordinal).ToList());
        Assert.Equal(["Queue.cs System.ServiceModel.NetMsmqBinding"],
            signals.Where(s => s.Name == "WCF_CLIENT_BINDING_USAGE").Select(s => $"{s.SourcePath} {s.Value}").ToList());
    }

    [Fact]
    public async Task ApiUsage_WcfClientBinding_ReadsGeneratedSvcutilClient_ButNothingElseInIt()
    {
        using var repo = new TempRepo();
        repo.Write("Connected Services/Ledger/Reference.cs", """
            //------------------------------------------------------------------------------
            // <auto-generated>
            //     This code was generated by a tool.
            // </auto-generated>
            //------------------------------------------------------------------------------
            public partial class LedgerClient : System.ServiceModel.ClientBase<ILedger>
            {
                private static System.ServiceModel.Channels.Binding GetBindingForEndpoint()
                {
                    var stamp = System.DateTime.Now;
                    return new System.ServiceModel.NetTcpBinding();
                }
            }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        var binding = Assert.Single(signals, s => s.Name == "WCF_CLIENT_BINDING_USAGE");
        Assert.Equal("System.ServiceModel.NetTcpBinding", binding.Value);
        // Generated code stays out of every other rule.
        Assert.DoesNotContain(signals, s => s.Name == "DATETIME_NOW_USAGE");
    }

    // ---- FileIndicatorExtractor, repository level ----

    [Fact]
    public void RepositoryLevel_FindsDeploymentFilesOutsideProjects_AndSkipsHelmTemplates()
    {
        using var repo = new TempRepo();
        repo.Write("Dockerfile", "FROM mcr.microsoft.com/dotnet/aspnet:10.0");
        repo.Write("k8s/deployment.yaml", "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\n");
        repo.Write("docker-compose.yml", "services:\n  api:\n    image: api\n");
        repo.Write("charts/api/Chart.yaml", "apiVersion: v2\nname: api\n");
        repo.Write("charts/api/templates/deployment.yaml", "apiVersion: apps/v1\nkind: Deployment\n");
        repo.Write("src/Api/Dockerfile", "FROM x");

        var signals = FileIndicatorExtractor.ExtractRepositoryLevel(
            repo.Root, [Path.Combine(repo.Root, "src", "Api")], CancellationToken.None);

        var found = signals.Select(s => $"{s.Name} {s.SourcePath}").OrderBy(v => v, StringComparer.Ordinal).ToList();
        Assert.Equal(
            ["CONTAINER_RUNS_AS_ROOT Dockerfile", "DOCKERFILE_FILE Dockerfile", "HELM_CHART_FILE charts/api/Chart.yaml", "OCP4_MANIFEST_FILE k8s/deployment.yaml"],
            found);
    }

    // ---- existing hosted-service signals (registry 1.1.0, unchanged) ----

    [Fact]
    public async Task HostedServiceSignals_AlreadyExist_AndFire()
    {
        using var repo = new TempRepo();
        repo.Write("Consumer.cs", """
            class OrdersConsumer : BackgroundService { }
            class Heartbeat : IHostedService { }
            static class Setup { static void Add(IServiceCollection s) => s.AddHostedService<OrdersConsumer>(); }
            """);

        var inheritance = await Extract(new InheritanceExtractor(), repo);
        var entryPoints = await Extract(new EntryPointExtractor(), repo);

        Assert.Contains(inheritance, s => s.Name == "BACKGROUND_SERVICE_BASE_CLASS");
        Assert.Contains(inheritance, s => s.Name == "IHOSTED_SERVICE_BASE_CLASS");
        Assert.Contains(entryPoints, s => s.Name == "ADD_HOSTED_SERVICE_ENTRY_POINT");
    }

    // ---- registry ----

    [Fact]
    public void LatestRegistry_DeclaresEveryBatch2Signal_WithItsExtractor()
    {
        var schemas = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "schemas"));
        var registry = SignalRegistry.LoadLatest(schemas);
        // 1.4.0 batch 2 (119) + 1.5.0 WCF_CLIENT_BINDING_CONFIG and _USAGE
        // + 1.6.0 the six PACKAGE_* signals, produced by step 6 (not step 3)
        // + 1.7.0 UNQUALIFIED_HOSTNAME_URL
        // + 1.8.0 seven architecture signals, produced by step 4 (not step 3)
        // + 1.9.0 INTERACTIVE_CONSOLE_INPUT and CONSOLE_PAUSE_FOR_INPUT
        // + 1.10.0 AMBIGUOUS_TOP_LEVEL_PROGRAM_ON_NET10, a framework delta from step 4
        // + 1.11.0 TARGET_FRAMEWORK_BELOW_ENGAGEMENT_TARGET and PACKAGE_PROVIDED_BY_FRAMEWORK (step 6),
        //   USE_IIS_INVOCATION, ASPNETCORE_HOSTING_MODEL and the three CONTAINER_* signals
        // + 1.12.0 VAULT_SECRET_REFERENCE, CONFIG_FILE_UNPARSEABLE, CUSTOM_FILE_LOGGER_PROVIDER, WINDOWS_BUILD_PIPELINE
        // + 1.13.0 WCF_SERVICE_BINDING_CONFIG and WCF_SERVICE_BINDING_USAGE
        // + 1.14.0 SERILOG_FILE_SINK_USAGE, SERILOG_CONSOLE_SINK_USAGE and SERILOG_CONSOLE_SINK_CONFIG.
        // + 1.16.0 EVENT_LOG_USAGE, SSIS_PACKAGE_EXECUTION and BACKSLASH_PATH_BUILDING.
        // + 1.17.0 the LINQ to SQL, WIF and Windows Workflow namespaces and assemblies, DATACONTEXT_BASE_CLASS, DBML_FILE,
        //   WIF_API_USAGE, WORKFLOW_XAML_FILE and CURRENT_USER_IDENTITY_CHECK.
        Assert.Equal("1.17.0", registry.RegistryVersion);
        Assert.Equal(168, registry.Entries.Count);
        Assert.Contains(registry.Entries, e => e.Name == ApiUsageExtractor.SerilogFileSinkUsage && e.Extractor == ApiUsageExtractor.ExtractorName);
        Assert.Contains(registry.Entries, e => e.Name == ApiUsageExtractor.SerilogConsoleSinkUsage && e.Extractor == ApiUsageExtractor.ExtractorName);
        Assert.Contains(registry.Entries, e => e.Name == "SERILOG_CONSOLE_SINK_CONFIG" && e.Extractor == ConfigurationExtractor.ExtractorName);
        Assert.Contains(registry.Entries, e => e.Name == "WCF_SERVICE_BINDING_CONFIG" && e.Extractor == ConfigurationExtractor.ExtractorName);
        Assert.Contains(registry.Entries, e => e.Name == "WCF_SERVICE_BINDING_USAGE" && e.Extractor == ApiUsageExtractor.ExtractorName);
        Assert.Contains(registry.Entries, e => e.Name == FileLoggerProviderExtractor.CustomFileLoggerProvider && e.Extractor == FileLoggerProviderExtractor.ExtractorName);
        Assert.Contains(registry.Entries, e => e.Name == WindowsBuild.WindowsBuildPipeline && e.Extractor == FileIndicatorExtractor.ExtractorName);
        Assert.Equal(8, registry.Entries.Count(e => e.Extractor == "EntryPointInventory"));
        Assert.Equal(7, registry.Entries.Count(e => e.Extractor == "DependencyAssessment" && e.Category == SignalCategories.PackageDependency));
        Assert.Contains(registry.Entries, e => e.Name == "WCF_CLIENT_BINDING_CONFIG" && e.Extractor == ConfigurationExtractor.ExtractorName);
        Assert.Equal(20, registry.Entries.Count(e => e.Extractor == ApiUsageExtractor.ExtractorName));
        Assert.Contains(registry.Entries, e => e.Name == ApiUsageExtractor.WifApiUsage && e.Extractor == ApiUsageExtractor.ExtractorName);
        Assert.Contains(registry.Entries, e => e.Name == ApiUsageExtractor.CurrentUserIdentityCheck && e.Extractor == ApiUsageExtractor.ExtractorName);
        Assert.Contains(registry.Entries, e => e.Name == FileIndicatorExtractor.WorkflowXamlFile && e.Extractor == FileIndicatorExtractor.ExtractorName);
        Assert.Contains(registry.Entries, e => e.Name == "DBML_FILE" && e.Extractor == FileIndicatorExtractor.ExtractorName);
        Assert.Contains(registry.Entries, e => e.Name == "DATACONTEXT_BASE_CLASS" && e.Extractor == InheritanceExtractor.ExtractorName);
        Assert.Equal(6, registry.Entries.Count(e => e.Extractor == FrameworkReferenceExtractor.ExtractorName
            && (e.Name.StartsWith("SYSTEM_DATA_LINQ_") || e.Name.StartsWith("SYSTEM_IDENTITYMODEL_SERVICES_") || e.Name.StartsWith("SYSTEM_ACTIVITIES_"))));
        Assert.Equal(3, registry.Entries.Count(e => e.Name.StartsWith("CONTAINER_") && e.Extractor == FileIndicatorExtractor.ExtractorName));
        Assert.Contains(registry.Entries, e => e.Name == IisHostingExtractor.HostingModel && e.Extractor == IisHostingExtractor.ExtractorName);
        Assert.Equal(4, registry.Entries.Count(e => e.Extractor == PathLiteralExtractor.ExtractorName));
        Assert.All(registry.Entries.Where(e => e.Type is SignalTypes.ApiInvocation or SignalTypes.Literal),
            e => Assert.Equal(SignalEvidenceKinds.File, e.EvidenceKind));
    }

    // ---- registry 1.16.0 ----

    [Fact]
    public async Task ApiUsage_finds_the_event_log_static_and_instance_but_not_a_lookalike()
    {
        using var repo = new TempRepo();
        repo.Write("Job.cs", """
            using System.Diagnostics;
            class Job
            {
                void Run()
                {
                    if (!EventLog.SourceExists("Job")) EventLog.CreateEventSource("Job", "Application");
                    EventLog.WriteEntry("Job", "started", EventLogEntryType.Information);
                    var log = new EventLog("Application");
                    var other = new MyEventLogWriter();
                    other.WriteEntry("not the event log");
                }
            }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        Assert.Equal(
            ["System.Diagnostics.EventLog", "System.Diagnostics.EventLog.CreateEventSource",
             "System.Diagnostics.EventLog.SourceExists", "System.Diagnostics.EventLog.WriteEntry"],
            Values(signals, "EVENT_LOG_USAGE"));
        var write = Assert.Single(signals, s => s.Name == "EVENT_LOG_USAGE" && s.Value == "System.Diagnostics.EventLog.WriteEntry");
        Assert.Equal(("Job", "Run", 7), (write.Evidence[0].DeclaringType, write.Evidence[0].Member, write.Evidence[0].LineStart));
    }

    [Fact]
    public async Task ApiUsage_finds_where_an_ssis_package_is_loaded_and_run_only_where_the_runtime_is_imported()
    {
        using var repo = new TempRepo();
        repo.Write("Runner.cs", """
            using Microsoft.SqlServer.Dts.Runtime;
            class Runner
            {
                int RunPackage(string path)
                {
                    var app = new Application();
                    Package package = app.LoadPackage(path, null);
                    return package.Execute() == DTSExecResult.Success ? 0 : 1;
                }
            }
            """);
        repo.Write("Other.cs", """
            class Other
            {
                void Go(dynamic loader, dynamic command) { loader.LoadPackage("x", null); command.Execute(); }
            }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        var found = signals.Where(s => s.Name == "SSIS_PACKAGE_EXECUTION").ToList();
        Assert.Equal(["Microsoft.SqlServer.Dts.Runtime.Application.LoadPackage", "Microsoft.SqlServer.Dts.Runtime.Package.Execute"],
            Values(found, "SSIS_PACKAGE_EXECUTION"));
        Assert.All(found, s => Assert.Equal("Runner.cs", s.SourcePath));
        Assert.All(found.SelectMany(s => s.Evidence), e => Assert.Equal(("Runner", "RunPackage"), (e.DeclaringType, e.Member)));
    }

    [Fact]
    public async Task PathLiteral_finds_paths_joined_with_a_backslash_but_not_a_drive_path_or_a_regex()
    {
        using var repo = new TempRepo();
        repo.Write("Logs.cs", """
            using System.Text.RegularExpressions;
            class Logs
            {
                string A(string dir, string name) => dir + "\\" + name;
                string B(string dir, string name) => string.Concat(dir, @"\", name);
                string C(string dir, string name) => $"{dir}\\logs\\{name}.log";
                string D(string root) => root + "logs\\";
                string E() => "C:\\data\\in";
                bool F(string s) => Regex.IsMatch(s, "^" + "\\d+" + "$");
                string G() => "\\";
            }
            """);

        var signals = await Extract(new PathLiteralExtractor(), repo);

        Assert.Equal(["\\", "\\logs\\", "logs\\"], Values(signals, "BACKSLASH_PATH_BUILDING"));
        var single = Assert.Single(signals, s => s.Name == "BACKSLASH_PATH_BUILDING" && s.Value == "\\");
        Assert.Equal([4, 5], single.Evidence.Select(e => e.LineStart!.Value).Order().ToArray());
        Assert.Contains(signals, s => s.Name == PathLiteralExtractor.WindowsPathLiteral);
    }

    // ---- registry 1.17.0 ----

    [Fact]
    public async Task FrameworkReference_finds_linq_to_sql_wif_and_workflow_namespaces_and_assemblies()
    {
        using var repo = new TempRepo();
        repo.Write("Test.csproj", """
            <Project ToolsVersion="15.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
              <ItemGroup>
                <Reference Include="System.Data.Linq" />
                <Reference Include="System.IdentityModel.Services" />
                <Reference Include="System.Activities, Version=4.0.0.0" />
                <Reference Include="System.Data" />
              </ItemGroup>
            </Project>
            """);
        repo.Write("Orders.cs", "using System.Data.Linq; using System.Data.Linq.Mapping; class Orders { }");
        repo.Write("Sign.cs", "using System.IdentityModel.Services; class Sign { }");
        repo.Write("Flow.cs", "using System.Activities; using System.Data; class Flow { }");

        var signals = await Extract(new FrameworkReferenceExtractor(), repo);

        Assert.Equal(["System.Data.Linq", "System.Data.Linq.Mapping"], Values(signals, "SYSTEM_DATA_LINQ_NAMESPACE"));
        Assert.Equal(["System.IdentityModel.Services"], Values(signals, "SYSTEM_IDENTITYMODEL_SERVICES_NAMESPACE"));
        Assert.Equal(["System.Activities"], Values(signals, "SYSTEM_ACTIVITIES_NAMESPACE"));
        Assert.Equal(["System.Data.Linq"], Values(signals, "SYSTEM_DATA_LINQ_ASSEMBLY"));
        Assert.Equal(["System.IdentityModel.Services"], Values(signals, "SYSTEM_IDENTITYMODEL_SERVICES_ASSEMBLY"));
        Assert.Equal(["System.Activities"], Values(signals, "SYSTEM_ACTIVITIES_ASSEMBLY"));
        Assert.Equal("Orders.cs", Assert.Single(signals, s => s.Name == "SYSTEM_DATA_LINQ_NAMESPACE" && s.Value == "System.Data.Linq").SourcePath);
    }

    [Fact]
    public async Task Inheritance_finds_a_linq_to_sql_data_context_but_not_a_data_context_property()
    {
        using var repo = new TempRepo();
        repo.Write("LedgerContext.cs", "public partial class LedgerDataContext : System.Data.Linq.DataContext { }");
        repo.Write("Window.cs", "class Window { public object DataContext { get; set; } }");

        var signals = await Extract(new InheritanceExtractor(), repo);

        var found = Assert.Single(signals, s => s.Name == "DATACONTEXT_BASE_CLASS");
        Assert.Equal("LedgerContext.cs", found.SourcePath);
    }

    [Fact]
    public async Task FileIndicator_finds_dbml_files_and_workflows_but_not_a_wpf_window()
    {
        using var repo = new TempRepo();
        repo.Write("Ledger.dbml", "<Database Name=\"Ledger\" xmlns=\"http://schemas.microsoft.com/linqtosql/dbml/2007\" />");
        repo.Write("Approve.xaml", """
            <Activity x:Class="Flows.Approve" xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities"
                      xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"><Sequence /></Activity>
            """);
        repo.Write("Service.xamlx", "<WorkflowService />");
        repo.Write("MainWindow.xaml", """
            <Window x:Class="Desk.MainWindow" xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
                    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" />
            """);

        var signals = await Extract(new FileIndicatorExtractor(), repo);

        Assert.Equal(["Ledger.dbml"], signals.Where(s => s.Name == "DBML_FILE").Select(s => s.SourcePath).ToList());
        Assert.Equal(["Approve.xaml", "Service.xamlx"],
            signals.Where(s => s.Name == FileIndicatorExtractor.WorkflowXamlFile).Select(s => s.SourcePath).Order().ToList());
        Assert.Equal(["Approve.xaml", "MainWindow.xaml"],
            signals.Where(s => s.Name == "XAML_FILE").Select(s => s.SourcePath).Order().ToList());
    }

    [Fact]
    public async Task ApiUsage_finds_wif_entry_points_modules_and_claims_managers_but_not_a_lookalike()
    {
        using var repo = new TempRepo();
        repo.Write("SignIn.cs", """
            using System.IdentityModel.Services;
            class SignIn
            {
                void Out()
                {
                    var module = FederatedAuthentication.SessionAuthenticationModule;
                    module.SignOut();
                    SessionAuthenticationModule other = null;
                }
            }
            """);
        repo.Write("Mapper.cs", "class Mapper : System.Security.Claims.ClaimsAuthenticationManager { }");
        repo.Write("NoImport.cs", "class Other { SessionAuthenticationModule M; }");

        var signals = await Extract(new ApiUsageExtractor(), repo);

        Assert.Equal(
            ["System.IdentityModel.Services.FederatedAuthentication.SessionAuthenticationModule",
             "System.IdentityModel.Services.SessionAuthenticationModule",
             "System.Security.Claims.ClaimsAuthenticationManager"],
            Values(signals, ApiUsageExtractor.WifApiUsage));
        Assert.DoesNotContain(signals, s => s.Name == ApiUsageExtractor.WifApiUsage && s.SourcePath == "NoImport.cs");
        var entry = Assert.Single(signals, s => s.Name == ApiUsageExtractor.WifApiUsage && s.Value!.EndsWith(".FederatedAuthentication.SessionAuthenticationModule"));
        Assert.Equal(("SignIn", "Out", 6), (entry.Evidence[0].DeclaringType, entry.Evidence[0].Member, entry.Evidence[0].LineStart));
    }

    [Fact]
    public async Task ApiUsage_finds_the_signed_in_users_identity_checks_apart_from_directory_queries()
    {
        using var repo = new TempRepo();
        repo.Write("Access.cs", """
            using System.DirectoryServices.AccountManagement;
            using System.Security.Principal;
            using System.Threading;
            class Access
            {
                bool IsAdmin()
                {
                    var me = WindowsIdentity.GetCurrent();
                    var principal = new WindowsPrincipal(me);
                    var current = UserPrincipal.Current;
                    var thread = Thread.CurrentPrincipal;
                    return principal.IsInRole("APPS\\Admins");
                }

                string Manager(string login)
                {
                    using var ctx = new PrincipalContext(ContextType.Domain);
                    return UserPrincipal.FindByIdentity(ctx, login)?.DisplayName;
                }
            }
            """);

        var signals = await Extract(new ApiUsageExtractor(), repo);

        Assert.Equal(
            ["System.DirectoryServices.AccountManagement.UserPrincipal.Current",
             "System.Security.Principal.IPrincipal.IsInRole",
             "System.Security.Principal.WindowsIdentity.GetCurrent",
             "System.Security.Principal.WindowsPrincipal",
             "System.Threading.Thread.CurrentPrincipal"],
            Values(signals, ApiUsageExtractor.CurrentUserIdentityCheck));
        Assert.All(signals.Where(s => s.Name == ApiUsageExtractor.CurrentUserIdentityCheck).SelectMany(s => s.Evidence),
            e => Assert.Equal(("Access", "IsAdmin"), (e.DeclaringType, e.Member)));
        // The directory query for another user is unchanged: still DIRECTORY_SERVICES_USAGE.
        Assert.Contains(signals, s => s.Name == "DIRECTORY_SERVICES_USAGE"
                                      && s.Value == "System.DirectoryServices.AccountManagement.PrincipalContext");
    }

    [Fact]
    public async Task PathLiteral_reads_no_hostname_in_a_claim_type_or_an_xml_namespace()
    {
        using var repo = new TempRepo();
        repo.Write("Claims.cs", """
            using System.Security.Claims;
            using System.Xml.Linq;
            using System.Runtime.Serialization;
            public static class AppClaimTypes
            {
                public const string Role = "http://appsrv/claims/role";
                public const string Region = "http://appsrv/identity/region";
            }
            [DataContract(Namespace = "http://ordersvc/contracts")]
            class Order { }
            class Checks
            {
                const string TenantClaimType = "http://tenantsvc/tenant";
                static readonly XNamespace Ns = "http://schemasvc/orders";
                Claim Make(string v) => new Claim("http://appsrv/x", v);
                string Find(ClaimsPrincipal p) => p.FindFirst("http://idsvc/name")?.Value;
                string Call()
                {
                    var url = "http://appsrv/api/orders";
                    return url;
                }
                // An endpoint whose name merely contains "claims" is still an endpoint.
                string claimsServiceUrl = "http://claimsvc/api/claims-lookup";
            }
            """);

        var signals = await Extract(new PathLiteralExtractor(), repo);

        var found = signals.Where(s => s.Name == PathLiteralExtractor.UnqualifiedHostnameUrl).OrderBy(s => s.Value).ToList();
        Assert.Equal(["appsrv", "claimsvc"], found.Select(s => s.Value).ToArray());
        Assert.Equal([19], found[0].Evidence.Select(e => e.LineStart!.Value).ToArray());
        Assert.Equal([23], found[1].Evidence.Select(e => e.LineStart!.Value).ToArray());
    }

    // ---- helpers ----

    private static async Task<IReadOnlyList<Signal>> Extract(
        IFingerprintExtractor extractor, TempRepo repo, IReadOnlyList<Fingerprinting.Analysis.DeployParameterFile>? deployFiles = null)
    {
        var result = await extractor.ExtractAsync(new ProjectContext
        {
            ProjectId = Guid.NewGuid(),
            RepositoryRoot = repo.Root,
            ProjectRelativePath = "Test.csproj",
            ProjectDirectory = repo.Root,
            DeployParameterFiles = deployFiles ?? [],
        }, CancellationToken.None);
        return result.Signals;
    }

    private static List<string> Values(IEnumerable<Signal> signals, string name) =>
        signals.Where(s => s.Name == name).Select(s => s.Value!).Distinct().OrderBy(v => v, StringComparer.Ordinal).ToList();

    private sealed class TempRepo : IDisposable
    {
        public string Root { get; } = Directory.CreateTempSubdirectory("fingerprinting-batch2-").FullName;

        public void Write(string relativePath, string content)
        {
            var path = Path.Combine(Root, relativePath.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllText(path, content);
        }

        public void Dispose()
        {
            try
            {
                Directory.Delete(Root, recursive: true);
            }
            catch (IOException)
            {
                // Best-effort cleanup.
            }
        }
    }
}
