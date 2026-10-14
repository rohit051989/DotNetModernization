using Fingerprinting.Analysis;
using Fingerprinting.Domain;
using Fingerprinting.Extractors;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>Registry 1.12.0: what the first Copilot pilot run (AccountsApi.Net10) exposed.</summary>
public sealed class PilotGapsTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "pilot-gaps-" + Guid.NewGuid().ToString("N"));
    private readonly string _project;

    public PilotGapsTests()
    {
        _project = Path.Combine(_root, "src", "Api");
        Directory.CreateDirectory(_project);
        File.WriteAllText(Path.Combine(_project, "Api.csproj"), "<Project Sdk=\"Microsoft.NET.Sdk.Web\" />");
    }

    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, true);
    }

    private ProjectContext Context() => new()
    {
        ProjectId = Guid.NewGuid(), RepositoryRoot = _root, ProjectRelativePath = "src/Api/Api.csproj", ProjectDirectory = _project,
    };

    private void Write(string name, string text) => File.WriteAllText(Path.Combine(_project, name), text);

    private static string[] Values(ExtractorResult result, string signal) =>
        result.Signals.Where(s => s.Name == signal).Select(s => s.Value!).Order(StringComparer.Ordinal).ToArray();

    // ---- A1: a sensitive key is recorded by its leaf's full path ----

    [Fact]
    public async Task A_sensitive_section_is_walked_and_each_secret_leaf_recorded_by_its_full_path()
    {
        Write("appsettings.json", """
            { "EnterpriseAuthentication": {
                "Token": { "SigningKey": "plain-signing-key-1", "Issuer": "enterprise-identity", "ClockSkewSeconds": 60 },
                "Client": { "ClientId": "accounts-api", "ClientSecret": "plain-client-secret" } },
              "Payments": { "Credentials": { "Primary": { "Password": "p1", "UserName": "svc" }, "Region": "eu" } },
              "Legacy": { "Token": { "Lifetime": 30 } },
              "Smtp": { "Password": "plain-password" } }
            """);
        var result = await new ConfigurationExtractor().ExtractAsync(Context(), CancellationToken.None);
        Assert.Equal(
            ["EnterpriseAuthentication:Client:ClientSecret", "EnterpriseAuthentication:Token:SigningKey", "Legacy:Token",
             "Payments:Credentials:Primary:Password", "Smtp:Password"],
            Values(result, "SENSITIVE_CONFIG_KEY"));
        // Nothing under a sensitive section that is not the secret, and no value, is ever recorded.
        Assert.DoesNotContain(result.Signals, s => (s.Value ?? "").Contains("Issuer") || (s.Value ?? "").Contains("plain-"));
    }

    // ---- B3: Enterprise.Vault references ----

    [Fact]
    public async Task A_vault_reference_is_recorded_as_one_not_as_a_secret_in_the_file()
    {
        Write("appsettings.json", """
            { "ConnectionStrings": { "AccountsDatabase": "vault:accounts-db-connection", "Local": "Server=.;Database=x;Integrated Security=true" },
              "EnterpriseAuthentication": { "Token": { "SigningKey": "vault:token-signing-key", "Issuer": "enterprise-identity" } },
              "Certificates": { "CreditCheckClient": { "CertificateBase64": "vault:creditcheck-client-cert" } },
              "Cache": { "Redis": { "Password": "vault:redis-password" } } }
            """);
        Write("web.config", """<configuration><appSettings><add key="ApiKey" value="vault:legacy-api-key" /></appSettings></configuration>""");
        var result = await new ConfigurationExtractor().ExtractAsync(Context(), CancellationToken.None);
        Assert.Equal(
            ["ApiKey", "Cache:Redis:Password", "Certificates:CreditCheckClient:CertificateBase64", "ConnectionStrings:AccountsDatabase",
             "EnterpriseAuthentication:Token:SigningKey"],
            Values(result, ConfigurationExtractor.VaultSecretReference));
        Assert.Empty(Values(result, "SENSITIVE_CONFIG_KEY"));
    }

    // ---- B4: an unparseable configuration file is a finding ----

    [Fact]
    public async Task An_unparseable_configuration_file_is_a_finding_never_skipped_silently()
    {
        Write("appsettings.json", "{\n  \"Paths\": {\n    \"Keys\": \"C:\\Keys\\private\"\n  }\n}\n");          // an unescaped backslash
        Write("web.config", "<configuration><appSettings><add key=\"A\" value=\"1\"></appSettings></configuration>");
        var result = await new ConfigurationExtractor().ExtractAsync(Context(), CancellationToken.None);
        var findings = result.Signals.Where(s => s.Name == ConfigurationExtractor.ConfigFileUnparseable).OrderBy(s => s.SourcePath).ToList();
        Assert.Equal(["src/Api/appsettings.json", "src/Api/web.config"], findings.Select(s => s.SourcePath!));
        Assert.StartsWith("invalid JSON at line 3", findings[0].Value);
        Assert.Equal(3, findings[0].Evidence.Single().LineStart);
        Assert.StartsWith("invalid XML at line 1", findings[1].Value);
        Assert.DoesNotContain(findings, f => f.Value!.Contains("private"));                                    // never the text there
    }

    // ---- A2: a path literal in configuration carries its configuration key ----

    [Fact]
    public async Task A_path_in_configuration_carries_the_key_the_code_reads_it_by()
    {
        Write("appsettings.json", """{ "FileContent": { "FilePath": "C:\\Accounts\\Content\\terms.pdf" } }""");
        Write("web.config", """
            <configuration><system.webServer><aspNetCore processPath="dotnet" stdoutLogFile="C:\logs\stdout">
              <environmentVariables><environmentVariable name="ENTERPRISE_VAULT_SECRETS_DIR" value="C:\Vault\secrets" /></environmentVariables>
            </aspNetCore></system.webServer></configuration>
            """);
        var result = await new PathLiteralExtractor().ExtractAsync(Context(), CancellationToken.None);
        var members = result.Signals.Where(s => s.Name == PathLiteralExtractor.WindowsPathLiteral)
            .ToDictionary(s => s.Value!, s => s.Evidence.Single().Member);
        Assert.Equal("FileContent:FilePath", members[@"C:\Accounts\Content\terms.pdf"]);
        Assert.Equal("ENTERPRISE_VAULT_SECRETS_DIR", members[@"C:\Vault\secrets"]);
        Assert.Equal("aspNetCore@stdoutLogFile", members[@"C:\logs\stdout"]);
    }

    // ---- B5: a custom logging provider that writes files ----

    [Fact]
    public async Task A_logging_provider_that_writes_files_is_found_and_one_that_does_not_is_not()
    {
        Write("FileLoggerProvider.cs", """
            using Microsoft.Extensions.Logging;
            public sealed class FileLoggerProvider : ILoggerProvider
            {
                public ILogger CreateLogger(string name) => new FileLogger();
                public void Dispose() { }
                private sealed class FileLogger { public void Log(string line) => System.IO.File.AppendAllText("app.log", line); }
            }
            """);
        Write("ConsoleProvider.cs", """
            public sealed class ConsoleProvider : Microsoft.Extensions.Logging.ILoggerProvider
            {
                public Microsoft.Extensions.Logging.ILogger CreateLogger(string name) => null!;
                public void Dispose() { System.Console.WriteLine("bye"); }
            }
            """);
        var result = await new FileLoggerProviderExtractor().ExtractAsync(Context(), CancellationToken.None);
        var found = Assert.Single(result.Signals);
        Assert.Equal((FileLoggerProviderExtractor.CustomFileLoggerProvider, "FileLoggerProvider", 2),
            (found.Name, found.Value, found.Evidence.Single().LineStart!.Value));
    }

    // ---- B6: Windows-oriented build and pipeline files ----

    [Fact]
    public void Windows_build_scripts_and_pipelines_are_found()
    {
        Assert.Equal(["Windows batch script package.bat"], WindowsBuild.Findings("Build/package.bat", "@echo off").Select(f => f.Value));
        Assert.Equal(
            [("Jenkins agent label windows-dotnet", 3), ("Jenkins bat step", 5)],
            WindowsBuild.Findings("Build/Jenkins/Jenkinsfile", "// Windows agent.\npipeline {\n    agent { label 'windows-dotnet' }\n    // bat 'commented out'\n    stages { stage('Build') { steps { bat 'Build\\build.bat' } } }\n}\n")
                .Select(f => (f.Value, f.Line)));
        Assert.Equal(
            [("runner: windows-latest", 3), ("Windows workflow uses: org/workflows/.github/workflows/windows-package.yml@v4", 5)],
            WindowsBuild.Findings(".github/workflows/ci.yml", "jobs:\n  build:\n    runner: windows-latest\n  package:\n    uses: org/workflows/.github/workflows/windows-package.yml@v4\n")
                .Select(f => (f.Value, f.Line)));
        Assert.Empty(WindowsBuild.Findings(".github/workflows/linux.yml", "jobs:\n  build:\n    runs-on: ubuntu-latest\n"));
        Assert.False(WindowsBuild.IsCandidate("docs/notes.yml"));
    }
}
