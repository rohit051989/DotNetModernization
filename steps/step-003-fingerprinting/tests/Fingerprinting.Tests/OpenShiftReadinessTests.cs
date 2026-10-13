using Fingerprinting.Analysis;
using Fingerprinting.Extractors;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>Registry 1.11.0: presence is not readiness — an existing Dockerfile or manifest that OpenShift's restricted
/// policy refuses; IIS hosting through the ASP.NET Core Module; sensitive keys as full paths, without settings that
/// only describe a secret.</summary>
public sealed class OpenShiftReadinessTests : IDisposable
{
    private readonly string _root = Path.Combine(Path.GetTempPath(), "openshift-tests-" + Guid.NewGuid().ToString("N"));

    public void Dispose()
    {
        if (Directory.Exists(_root)) Directory.Delete(_root, true);
    }

    private static string[] Signals(IReadOnlyList<ContainerSecurity.Finding> findings, string signal) =>
        findings.Where(f => f.Signal == signal).Select(f => f.Value).ToArray();

    [Fact]
    public void A_dockerfile_without_a_user_on_port_80_with_a_fixed_owner_fails_all_three()
    {
        var findings = ContainerSecurity.Dockerfile("""
            FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
            USER root
            RUN dotnet publish -o /out

            FROM mcr.microsoft.com/dotnet/aspnet:8.0
            WORKDIR /app
            COPY --from=build /out .
            RUN mkdir /app/logs \
                && chown -R app:app /app/logs
            ENV ASPNETCORE_URLS=http://+:80
            EXPOSE 80
            ENTRYPOINT ["dotnet", "Web.dll"]
            """);
        Assert.Equal(["no USER instruction: the image runs as root"], Signals(findings, ContainerSecurity.RunsAsRoot));
        Assert.Equal(["ASPNETCORE_URLS=http://+:80", "EXPOSE 80"], Signals(findings, ContainerSecurity.PrivilegedPort).Order());
        Assert.Equal(["chown -R app:app"], Signals(findings, ContainerSecurity.FixedUserWritablePath));
        Assert.Equal(8, findings.Single(f => f.Signal == ContainerSecurity.FixedUserWritablePath).Line);   // the RUN's first line
    }

    [Fact]
    public void An_openshift_ready_dockerfile_has_no_finding()
    {
        // AccountsApi's: a non-root UID in group 0, group given the owner's rights, port 8080.
        var findings = ContainerSecurity.Dockerfile("""
            FROM mcr.microsoft.com/dotnet/runtime-deps:10.0
            WORKDIR /app
            COPY DeploymentPackage/linux-x64/ /app/
            RUN chmod 0755 /app/docker-entrypoint.sh /app/Accounts.CoreApi \
                && chown -R 1001:0 /app \
                && chmod -R g=u /app
            ENV ASPNETCORE_URLS=http://+:8080 \
                TZ=Etc/UTC
            EXPOSE 8080
            USER 1001
            ENTRYPOINT ["/app/docker-entrypoint.sh"]
            """);
        Assert.Empty(findings);
    }

    [Fact]
    public void The_final_stage_inherits_the_stage_it_is_built_from()
    {
        // Visual Studio's template (eShopOnWeb PublicApi): EXPOSE in base, final built FROM base.
        var findings = ContainerSecurity.Dockerfile("""
            FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS base
            WORKDIR /app
            EXPOSE 80
            EXPOSE 443

            FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
            EXPOSE 22
            RUN dotnet publish -o /app/publish

            FROM base AS final
            COPY --from=build /app/publish .
            ENTRYPOINT ["dotnet", "PublicApi.dll"]
            """);
        Assert.Equal(["EXPOSE 443", "EXPOSE 80"], Signals(findings, ContainerSecurity.PrivilegedPort).Order());   // not the build stage's 22
        Assert.Equal([3, 4], findings.Where(f => f.Signal == ContainerSecurity.PrivilegedPort).Select(f => f.Line).Order());
        Assert.Single(Signals(findings, ContainerSecurity.RunsAsRoot));
        Assert.Empty(ContainerSecurity.Dockerfile("FROM aspnet:8.0 AS base\nUSER 1001\nFROM base AS final\nENTRYPOINT x\n"));
    }

    [Fact]
    public void A_later_user_root_or_an_owner_only_mode_is_found()
    {
        var findings = ContainerSecurity.Dockerfile("FROM alpine\nUSER 1001\nRUN chmod 700 /data\nUSER root\n");
        Assert.Equal(["USER root"], Signals(findings, ContainerSecurity.RunsAsRoot));
        Assert.Equal(["chmod 700"], Signals(findings, ContainerSecurity.FixedUserWritablePath));
    }

    [Fact]
    public void A_manifest_is_judged_line_by_line()
    {
        var findings = ContainerSecurity.Manifest("""
            apiVersion: apps/v1
            kind: Deployment
            spec:
              template:
                spec:
                  securityContext:
                    runAsUser: 1000
                    fsGroup: 2000
                  containers:
                    - name: web
                      ports:
                        - containerPort: 80
                      securityContext:
                        privileged: true
                        runAsNonRoot: true
            """);
        Assert.Equal(["privileged: true"], Signals(findings, ContainerSecurity.RunsAsRoot));
        Assert.Equal(["containerPort: 80"], Signals(findings, ContainerSecurity.PrivilegedPort));
        Assert.Equal(["fsGroup: 2000", "runAsUser: 1000"], Signals(findings, ContainerSecurity.FixedUserWritablePath).Order());
        Assert.Empty(ContainerSecurity.Manifest("spec:\n  securityContext:\n    runAsNonRoot: true\n  ports:\n    - containerPort: 8080\n"));
    }

    [Fact]
    public async Task The_iis_hosting_model_comes_from_the_project_file_and_web_config()
    {
        var project = Path.Combine(_root, "src", "Api");
        Directory.CreateDirectory(project);
        File.WriteAllText(Path.Combine(project, "Api.csproj"),
            "<Project Sdk=\"Microsoft.NET.Sdk.Web\">\n  <PropertyGroup>\n    <AspNetCoreHostingModel>InProcess</AspNetCoreHostingModel>\n  </PropertyGroup>\n</Project>\n");
        File.WriteAllText(Path.Combine(project, "web.config"), """
            <configuration>
              <system.webServer>
                <handlers><add name="aspNetCore" path="*" verb="*" modules="AspNetCoreModuleV2" /></handlers>
                <aspNetCore processPath=".\Api.exe" hostingModel="outofprocess" />
              </system.webServer>
            </configuration>
            """);
        var result = await new IisHostingExtractor().ExtractAsync(new ProjectContext
        {
            ProjectId = Guid.NewGuid(), RepositoryRoot = _root, ProjectRelativePath = "src/Api/Api.csproj", ProjectDirectory = project,
        }, CancellationToken.None);
        Assert.Equal([("src/Api/Api.csproj", "inprocess", 3), ("src/Api/web.config", "outofprocess", 4)],
            result.Signals.Select(s => (s.SourcePath!, s.Value!, s.Evidence.Single().LineStart!.Value)).Order());
        Assert.All(result.Signals, s => Assert.Equal(IisHostingExtractor.HostingModel, s.Name));
    }

    [Theory]
    [InlineData("Password", true)]
    [InlineData("ClientSecret", true)]
    [InlineData("Token", true)]
    [InlineData("api_key", true)]
    [InlineData("Wcf:Bindings:Secure:ClientCredentialType", false)]
    [InlineData("TokenEndpoint", false)]
    [InlineData("SecretsDir", false)]
    [InlineData("ApiKeyHeader", false)]
    [InlineData("ConnectionStringName", false)]
    [InlineData("BindingMode", false)]
    public void A_key_that_only_describes_a_secret_is_a_setting(string key, bool sensitive) =>
        Assert.Equal(sensitive, Secrets.IsSensitiveKey(key));

    [Fact]
    public async Task A_sensitive_key_is_recorded_by_its_full_path_never_its_value()
    {
        var project = Path.Combine(_root, "src", "Api");
        Directory.CreateDirectory(project);
        File.WriteAllText(Path.Combine(project, "Api.csproj"), "<Project Sdk=\"Microsoft.NET.Sdk.Web\" />");
        File.WriteAllText(Path.Combine(project, "appsettings.json"), """
            { "EnterpriseAuthentication": { "Token": { "ClientSecret": "s3cr3t-v4lue", "TokenEndpoint": "https://idp/token" } },
              "Wcf": { "Bindings": { "Secure": { "ClientCredentialType": "Certificate" } } } }
            """);
        var result = await new ConfigurationExtractor().ExtractAsync(new ProjectContext
        {
            ProjectId = Guid.NewGuid(), RepositoryRoot = _root, ProjectRelativePath = "src/Api/Api.csproj", ProjectDirectory = project,
        }, CancellationToken.None);
        var keys = result.Signals.Where(s => s.Name == "SENSITIVE_CONFIG_KEY").Select(s => s.Value!).ToArray();
        Assert.Equal(["EnterpriseAuthentication:Token"], keys);                                     // the section, once; nothing below it read
        Assert.DoesNotContain(result.Signals, s => (s.Value ?? "").Contains("s3cr3t"));
    }
}
