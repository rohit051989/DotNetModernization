using Fingerprinting.Domain;
using Fingerprinting.Extractors;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>
/// Mechanical proof of 21-STEP-003-FINGERPRINTING.md Part G's secrets rule:
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
