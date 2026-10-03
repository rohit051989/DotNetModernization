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
        repo.Write("appsettings.DEVOCP.json", """
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
            ["DOCKERFILE_FILE Dockerfile", "HELM_CHART_FILE charts/api/Chart.yaml", "OCP4_MANIFEST_FILE k8s/deployment.yaml"],
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
        // + 1.6.0 the six PACKAGE_* signals, produced by step 6 (not step 3).
        Assert.Equal("1.6.0", registry.RegistryVersion);
        Assert.Equal(127, registry.Entries.Count);
        Assert.Equal(6, registry.Entries.Count(e => e.Extractor == "DependencyAssessment" && e.Category == SignalCategories.PackageDependency));
        Assert.Contains(registry.Entries, e => e.Name == "WCF_CLIENT_BINDING_CONFIG" && e.Extractor == ConfigurationExtractor.ExtractorName);
        Assert.Equal(10, registry.Entries.Count(e => e.Extractor == ApiUsageExtractor.ExtractorName));
        Assert.Equal(2, registry.Entries.Count(e => e.Extractor == PathLiteralExtractor.ExtractorName));
        Assert.All(registry.Entries.Where(e => e.Type is SignalTypes.ApiInvocation or SignalTypes.Literal),
            e => Assert.Equal(SignalEvidenceKinds.File, e.EvidenceKind));
    }

    // ---- helpers ----

    private static async Task<IReadOnlyList<Signal>> Extract(IFingerprintExtractor extractor, TempRepo repo)
    {
        var result = await extractor.ExtractAsync(new ProjectContext
        {
            ProjectId = Guid.NewGuid(),
            RepositoryRoot = repo.Root,
            ProjectRelativePath = "Test.csproj",
            ProjectDirectory = repo.Root,
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
