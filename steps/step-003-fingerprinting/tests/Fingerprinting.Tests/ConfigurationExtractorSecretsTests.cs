using Fingerprinting.Domain;
using Fingerprinting.Extractors;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>
/// Mechanical proof of 21-APPLICATION-FINGERPRINTING.md Part G's secrets rule:
/// "A fixture containing a full connection string with credentials produces
/// an artifact whose text does not contain the password." Covers both the
/// web.config/app.config (XML) and appsettings.json (JSON) parsing paths.
/// </summary>
public sealed class ConfigurationExtractorSecretsTests
{
    private const string Password = "Tr0ub4dor-SuperSecret-Password!";

    [Fact]
    public async Task WebConfigConnectionString_DoesNotLeakPasswordIntoArtifact()
    {
        using var fixture = new TempProjectFixture();
        await File.WriteAllTextAsync(Path.Combine(fixture.ProjectDirectory, "web.config"), $"""
            <?xml version="1.0" encoding="utf-8"?>
            <configuration>
              <connectionStrings>
                <add name="CustomerDb"
                     connectionString="Server=sql01;Database=Customers;User Id=app;Password={Password};"
                     providerName="System.Data.SqlClient" />
              </connectionStrings>
              <appSettings>
                <add key="ApiKey" value="{Password}" />
              </appSettings>
            </configuration>
            """);

        var artifactText = await ExtractAndSerializeAsync(fixture);

        Assert.DoesNotContain(Password, artifactText);
        // The safe facts must still be present — the rule is "no secrets", not "no signal".
        Assert.Contains("CONNECTION_STRING_CONFIG", artifactText);
        Assert.Contains("\"value\": \"CustomerDb\"", artifactText);
        Assert.Contains("CONNECTION_STRING_PROVIDER_CONFIG", artifactText);
        Assert.Contains("\"value\": \"System.Data.SqlClient\"", artifactText);
        Assert.Contains("SENSITIVE_CONFIG_KEY", artifactText);
        Assert.Contains("\"value\": \"ApiKey\"", artifactText);
    }

    [Fact]
    public async Task AppSettingsJson_DoesNotLeakPasswordIntoArtifact()
    {
        using var fixture = new TempProjectFixture();
        await File.WriteAllTextAsync(Path.Combine(fixture.ProjectDirectory, "appsettings.json"), $$"""
            {
              "ConnectionStrings": {
                "CustomerDb": "Server=sql01;Database=Customers;User Id=app;Password={{Password}};"
              },
              "Azure": {
                "Storage": {
                  "AccountKey": "{{Password}}"
                }
              }
            }
            """);

        var artifactText = await ExtractAndSerializeAsync(fixture);

        Assert.DoesNotContain(Password, artifactText);
        Assert.Contains("CONNECTION_STRING_CONFIG", artifactText);
        Assert.Contains("\"value\": \"CustomerDb\"", artifactText);
        Assert.Contains("SENSITIVE_CONFIG_KEY", artifactText);
        Assert.Contains("\"value\": \"AccountKey\"", artifactText);
    }

    // ---- Part G restated: nothing derived from a connection string is persisted ----

    private const string ServerName = "sql-prod-07.corp.example";

    [Fact]
    public async Task WindowsAuthConnectionString_YieldsOnlyTheName_Xml()
    {
        using var fixture = new TempProjectFixture();
        await File.WriteAllTextAsync(Path.Combine(fixture.ProjectDirectory, "web.config"), $"""
            <?xml version="1.0" encoding="utf-8"?>
            <configuration>
              <connectionStrings>
                <add name="LedgerDb"
                     connectionString="Server={ServerName};Database=Ledger;Integrated Security=SSPI;Password={Password};"
                     providerName="System.Data.SqlClient" />
                <add name="AuditDb"
                     connectionString="Server={ServerName};Database=Audit;User Id=app;Password={Password};" />
              </connectionStrings>
            </configuration>
            """);

        var signals = await ExtractAsync(fixture);
        var artifactText = DeterministicJson.Serialize(signals);

        AssertNothingFromTheString(artifactText);
        var windowsAuth = Assert.Single(signals, s => s.Name == "WINDOWS_AUTH_CONNECTION_STRING_CONFIG");
        Assert.Equal("LedgerDb", windowsAuth.Value);
    }

    [Fact]
    public async Task WindowsAuthConnectionString_YieldsOnlyTheName_Json()
    {
        using var fixture = new TempProjectFixture();
        await File.WriteAllTextAsync(Path.Combine(fixture.ProjectDirectory, "appsettings.Production.json"), $$"""
            {
              "ConnectionStrings": {
                "LedgerDb": "Server={{ServerName}};Database=Ledger;Trusted_Connection=True;Password={{Password}};",
                "Legacy": "metadata=res://*/Model.csdl;provider=System.Data.SqlClient;provider connection string=\"data source={{ServerName}};integrated security=True;password={{Password}}\"",
                "AuditDb": "Server={{ServerName}};Database=Audit;User Id=app;Password={{Password}};"
              }
            }
            """);

        var signals = await ExtractAsync(fixture);
        var artifactText = DeterministicJson.Serialize(signals);

        AssertNothingFromTheString(artifactText);
        var names = signals.Where(s => s.Name == "WINDOWS_AUTH_CONNECTION_STRING_CONFIG").Select(s => s.Value).OrderBy(v => v).ToList();
        Assert.Equal(["LedgerDb", "Legacy"], names);
    }

    [Fact]
    public async Task TrustedConnectionFalseAfterIntegratedSecurityTrue_IsNotWindowsAuth()
    {
        // eShopOnWeb's appsettings.Docker.json shape: the later synonym wins.
        using var fixture = new TempProjectFixture();
        await File.WriteAllTextAsync(Path.Combine(fixture.ProjectDirectory, "appsettings.Docker.json"), $$"""
            {
              "ConnectionStrings": {
                "CatalogConnection": "Server=sqlserver,1433;Integrated Security=true;User Id=sa;Password={{Password}};Trusted_Connection=false;"
              }
            }
            """);

        var signals = await ExtractAsync(fixture);

        Assert.DoesNotContain(signals, s => s.Name == "WINDOWS_AUTH_CONNECTION_STRING_CONFIG");
        Assert.Contains(signals, s => s.Name == "CONNECTION_STRING_CONFIG" && s.Value == "CatalogConnection");
    }

    [Fact]
    public async Task WindowsPathInsideAConnectionString_ProducesNoLiteralRow()
    {
        using var fixture = new TempProjectFixture();
        await File.WriteAllTextAsync(Path.Combine(fixture.ProjectDirectory, "web.config"), $"""
            <?xml version="1.0" encoding="utf-8"?>
            <configuration>
              <connectionStrings>
                <add name="LocalDb" connectionString="Data Source=(localdb)\v11;AttachDbFilename=C:\Data\Ledger.mdf;Password={Password};" />
              </connectionStrings>
              <appSettings>
                <add key="ReportFolder" value="D:\Reports\Out" />
                <add key="ApiKey" value="E:\keys\{Password}" />
              </appSettings>
            </configuration>
            """);
        await File.WriteAllTextAsync(Path.Combine(fixture.ProjectDirectory, "appsettings.json"), $$"""
            {
              "ConnectionStrings": { "Ledger": "Server=.;AttachDbFilename=C:\\Data\\Ledger.mdf;Password={{Password}};" },
              "Paths": { "Inbox": "G:\\Inbox" },
              "Secrets": { "Token": "F:\\tokens\\{{Password}}" }
            }
            """);
        await File.WriteAllTextAsync(Path.Combine(fixture.ProjectDirectory, "Paths.cs"), $$"""
            class Paths
            {
                // A comment mentioning C:\Commented\Out is never read.
                string LogDir = @"C:\Logs\App";
                string Cs = "Server=.;AttachDbFilename=C:\\Data\\Ledger.mdf;Password={{Password}};";
                string connectionString = @"H:\looks\like\a\path";
                void M() { var password = @"I:\{{Password}}"; }
            }
            """);

        var signals = await new PathLiteralExtractor().ExtractAsync(Context(fixture), CancellationToken.None);
        var artifactText = DeterministicJson.Serialize(signals.Signals);

        Assert.DoesNotContain(Password, artifactText);
        Assert.DoesNotContain("Ledger.mdf", artifactText);
        Assert.DoesNotContain("Commented", artifactText);
        Assert.DoesNotContain(@"H:\\looks", artifactText);
        var found = signals.Signals.Where(s => s.Name == PathLiteralExtractor.WindowsPathLiteral)
            .Select(s => s.Value).OrderBy(v => v, StringComparer.Ordinal).ToList();
        Assert.Equal([@"C:\Logs\App", @"D:\Reports\Out", @"G:\Inbox"], found);
    }

    private static void AssertNothingFromTheString(string artifactText)
    {
        Assert.DoesNotContain(Password, artifactText);
        Assert.DoesNotContain(ServerName, artifactText);
        Assert.DoesNotContain("Integrated Security", artifactText, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("Trusted_Connection", artifactText, StringComparison.OrdinalIgnoreCase);
    }

    private static ProjectContext Context(TempProjectFixture fixture) => new()
    {
        ProjectId = Guid.NewGuid(),
        RepositoryRoot = fixture.RepositoryRoot,
        ProjectRelativePath = "Test.csproj",
        ProjectDirectory = fixture.ProjectDirectory,
    };

    private static async Task<IReadOnlyList<Signal>> ExtractAsync(TempProjectFixture fixture)
    {
        var result = await new ConfigurationExtractor().ExtractAsync(Context(fixture), CancellationToken.None);
        Assert.Empty(result.Warnings);
        return result.Signals;
    }

    private static async Task<string> ExtractAndSerializeAsync(TempProjectFixture fixture)
    {
        var extractor = new ConfigurationExtractor();
        var context = new ProjectContext
        {
            ProjectId = Guid.NewGuid(),
            RepositoryRoot = fixture.RepositoryRoot,
            ProjectRelativePath = "Test.csproj",
            ProjectDirectory = fixture.ProjectDirectory,
        };

        var result = await extractor.ExtractAsync(context, CancellationToken.None);
        Assert.Empty(result.Warnings);

        return DeterministicJson.Serialize(result.Signals);
    }

    private sealed class TempProjectFixture : IDisposable
    {
        public string RepositoryRoot { get; }
        public string ProjectDirectory { get; }

        public TempProjectFixture()
        {
            RepositoryRoot = Directory.CreateTempSubdirectory("fingerprinting-secrets-test-").FullName;
            ProjectDirectory = RepositoryRoot;
        }

        public void Dispose()
        {
            try
            {
                Directory.Delete(RepositoryRoot, recursive: true);
            }
            catch (IOException)
            {
                // Best-effort cleanup; a lingering temp dir is not a test failure.
            }
        }
    }
}
