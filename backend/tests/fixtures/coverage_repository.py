"""A generated repository that holds at least one occurrence of every active catalog item, each triggered by the item's
real signals, in realistic project kinds (tests/test_catalog_coverage.py). Made-up code only: nothing here comes from a
client's code.

    python -m tests.fixtures.coverage_repository <folder>

Writes, into an empty folder:

    Core/       old-style class library on .NET Framework 4.7, packages.config: the occurrence items of plain code, one
                file each (local time, the default encoding, the registry, the Event Log, paths, System.Drawing, a
                Serilog file sink, a file logger, an unqualified host, MSMQ), and a Windows-only database provider by path (not the SSIS
                runtime, which the SSIS item's C# rewrite replaces)
    Data/, WebKit/, Identity/, Flow/
                old-style libraries using APIs only .NET Framework has (tests/fixtures/framework_only_repository.py):
                LINQ to SQL, System.Web, WIF and directory services, Windows Workflow
    Nightly/    old-style console batch job: its App.config holds a Windows-authentication connection string, a
                sensitive key, a vault reference and a WCF client endpoint over NetTcp
    Prompt/     old-style interactive console tool, with an App.config that does not parse
    Poller/     old-style Windows Service (ServiceBase)
    Desk/       old-style WinForms application; Board/: old-style WPF application
    Shop/       classic ASP.NET Web Forms application; Web/: classic ASP.NET MVC application; Orders/: classic WCF
                service; Legacy/: ASMX web service, with a Windows deploy script (tests/fixtures/guidance_repository.py)
    Etl/        an SSIS package project (tests/fixtures/guidance_repository.py)
    Modern/Api/     SDK-style ASP.NET Core API on net8.0 (a Startup class, IIS hosting, no health endpoint) with a
                    Dockerfile that runs as root on port 80 and chowns to a fixed user, and the PackageReferences the
                    package items need
    Modern/Worker/  SDK-style worker service (BackgroundService), with a Windows batch build script
    Modern/WinSvc/  SDK-style service hosted as a Windows Service (UseWindowsService)

The repository's NuGet.config names one client feed, FEED; LOOKUPS is what that feed says, and PUBLIC what nuget.org
says, for the scan's offline lookups (the test puts both in the lookup cache).

EXPECTED: {item id: {(project, file or None)}}, where the scan must find each item. An item missing from it fails the
test with its id (tests/test_catalog_coverage.py), so a new catalog item cannot be added without its occurrence here.
"""
import sys
from pathlib import Path

from tests.fixtures import framework_only_repository as framework_only
from tests.fixtures import guidance_repository as guidance
from tests.fixtures.guidance_repository import _project
from tests.fixtures.services_repository import WEB_GUIDS

FEED = "https://feed.client-a.example/coverage/{tag}"
NUGET_ORG = "https://api.nuget.org/v3/index.json"
WEBFORMS_GUIDS = WEB_GUIDS


def _version(version: str, frameworks: list[str], *, libs: list[str] | None = None, deprecation: dict | None = None,
             vulnerabilities: list[dict] | None = None) -> dict:
    return {"version": version, "listed": True, "dependencyFrameworks": frameworks, "libFrameworks": libs,
            "dependencies": [{"framework": f, "packages": []} for f in frameworks],
            **({"deprecation": deprecation} if deprecation else {}), "vulnerabilities": vulnerabilities or []}


# What the client feed says, per package (lower-case id): {version: its metadata}, newest first.
LOOKUPS = {
    # A minor upgrade: safe.
    "acme.text": {"1.4.0": _version("1.4.0", ["netstandard2.0"]), "1.0.0": _version("1.0.0", ["netstandard2.0"])},
    # A major upgrade: breaking.
    "acme.http": {"2.1.0": _version("2.1.0", ["netstandard2.0"]), "1.2.0": _version("1.2.0", ["netstandard2.0"])},
    # A known advisory on the referenced version, fixed in the next.
    "acme.crypto": {"2.0.3": _version("2.0.3", ["netstandard2.0"]),
                    "2.0.0": _version("2.0.0", ["netstandard2.0"], vulnerabilities=[
                        {"severity": 2, "advisoryUrl": "https://advisories.client-a.example/acme-crypto-1"}])},
    # Retired by its publisher, who names a successor.
    "acme.legacy": {"1.0.0": _version("1.0.0", ["netstandard2.0"], deprecation={
        "reasons": ["Legacy"], "message": "Use Acme.Modern.", "alternateId": "Acme.Modern", "alternateRange": "[1.0.0, )"})},
    "acme.modern": {"1.1.0": _version("1.1.0", ["netstandard2.0"])},
    # Built only for .NET Framework: no version supports the target framework.
    "acme.classic": {"3.0.0": _version("3.0.0", [], libs=["net45"])},
    # Approved at 1.0.0 only; nuget.org has a newer one.
    "acme.feed": {"1.0.0": _version("1.0.0", ["netstandard2.0"])},
    # The target framework's shared framework provides it.
    "system.text.json": {"6.0.0": _version("6.0.0", ["net6.0", "netstandard2.0"])},
    "newtonsoft.json": {"13.0.1": _version("13.0.1", ["net45", "netstandard2.0"])},
}
PUBLIC = {
    "acme.feed": {"1.5.0": _version("1.5.0", ["netstandard2.0"]), "1.0.0": _version("1.0.0", ["netstandard2.0"])},
}

SDK_WEB = """<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>{framework}</TargetFramework>{extra}
  </PropertyGroup>
  <ItemGroup>
{packages}
  </ItemGroup>
</Project>
"""
SDK_WORKER = """<Project Sdk="Microsoft.NET.Sdk.Worker">
  <PropertyGroup>
    <TargetFramework>{framework}</TargetFramework>
  </PropertyGroup>
  <ItemGroup>
{packages}
  </ItemGroup>
</Project>
"""


def _packages(pairs: list[tuple[str, str]]) -> str:
    return "\n".join(f'    <PackageReference Include="{i}" Version="{v}" />' for i, v in pairs)


CORE_FILES = {
    "Core/Core.csproj": _project("Core", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.Drawing" />', '<Reference Include="System.Messaging" />',
        '<Reference Include="Sybase.AdoNet4.AseClient, Version=4.157.0.0"><HintPath>..\\lib\\Sybase.AdoNet4.AseClient.dll</HintPath></Reference>',
        '<Reference Include="Newtonsoft.Json, Version=13.0.0.0"><HintPath>..\\packages\\Newtonsoft.Json.13.0.1\\lib\\net45\\Newtonsoft.Json.dll</HintPath></Reference>',
    ], ["Clock.cs", "Text.cs", "Settings.cs", "Audit.cs", "Paths.cs", "Thumbnails.cs", "Logging.cs", "FileLogger.cs",
        "Pricing.cs", "Queue.cs"]),
    "Core/packages.config": '<?xml version="1.0" encoding="utf-8"?>\n<packages>\n'
                            '  <package id="Newtonsoft.Json" version="13.0.1" targetFramework="net47" />\n</packages>\n',
    "Core/Clock.cs": """using System;

namespace Core
{
    public static class Clock
    {
        public static string Stamp() => DateTime.Now.ToString("yyyyMMdd");
    }
}
""",
    "Core/Text.cs": """using System.IO;
using System.Text;

namespace Core
{
    public static class Text
    {
        public static string Read(string path) => File.ReadAllText(path, Encoding.Default);
    }
}
""",
    "Core/Settings.cs": """using Microsoft.Win32;

namespace Core
{
    public static class Settings
    {
        public static object Region() => Registry.LocalMachine.OpenSubKey("SOFTWARE\\\\Orders")?.GetValue("Region");
    }
}
""",
    "Core/Audit.cs": """using System.Diagnostics;

namespace Core
{
    public static class Audit
    {
        public static void Write(string message) => EventLog.WriteEntry("Orders", message, EventLogEntryType.Information);
    }
}
""",
    "Core/Paths.cs": """namespace Core
{
    public static class Paths
    {
        public const string Inbox = @"D:\\orders\\inbox";

        public static string Archive(string folder, string name) => folder + "\\\\" + name;
    }
}
""",
    "Core/Thumbnails.cs": """using System.Drawing;

namespace Core
{
    public static class Thumbnails
    {
        public static Bitmap Make(int width, int height) => new Bitmap(width, height);
    }
}
""",
    "Core/Logging.cs": """using Serilog;

namespace Core
{
    public static class Logging
    {
        public static ILogger Create() => new LoggerConfiguration()
            .WriteTo.File(@"C:\\logs\\orders.log")
            .CreateLogger();
    }
}
""",
    "Core/FileLogger.cs": """using System;
using System.IO;
using Microsoft.Extensions.Logging;

namespace Core
{
    public sealed class FileLoggerProvider : ILoggerProvider
    {
        public ILogger CreateLogger(string category) => null;

        public void Write(string line) => File.AppendAllText("orders.log", line + Environment.NewLine);

        public void Dispose() { }
    }
}
""",
    "Core/Pricing.cs": """namespace Core
{
    public static class Pricing
    {
        public const string Endpoint = "http://pricing/api/prices";
    }
}
""",
    "Core/Queue.cs": """using System.Messaging;

namespace Core
{
    public static class Outbox
    {
        public static void Send(object body)
        {
            using (var queue = new MessageQueue(@".\\private$\\orders"))
            {
                queue.Send(body);
            }
        }
    }
}
""",
}

JOB_FILES = {
    "Nightly/Nightly.csproj": _project("Nightly", "Exe", ['<Reference Include="System" />', '<Reference Include="System.Configuration" />',
                                                          '<ProjectReference Include="..\\Core\\Core.csproj"><Name>Core</Name></ProjectReference>'],
                                       ["Program.cs"], more='\n  <ItemGroup>\n    <None Include="App.config" />\n  </ItemGroup>'),
    "Nightly/Program.cs": """namespace Nightly
{
    public static class Program
    {
        public static int Main(string[] args)
        {
            Core.Audit.Write("nightly run " + Core.Clock.Stamp());
            return 0;
        }
    }
}
""",
    "Nightly/App.config": """<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <connectionStrings>
    <add name="Orders" connectionString="Data Source=ordersdb;Initial Catalog=Orders;Integrated Security=SSPI" />
  </connectionStrings>
  <appSettings>
    <add key="ApiPassword" value="placeholder" />
    <add key="ReportingConnection" value="vault:reporting-db" />
  </appSettings>
  <system.serviceModel>
    <client>
      <endpoint name="Stock" address="net.tcp://stock.client-a.example:8090/stock" binding="netTcpBinding" contract="IStock" />
    </client>
  </system.serviceModel>
</configuration>
""",
    "Prompt/Prompt.csproj": _project("Prompt", "Exe", ['<Reference Include="System" />'], ["Program.cs"],
                                     more='\n  <ItemGroup>\n    <None Include="App.config" />\n  </ItemGroup>'),
    "Prompt/Program.cs": """using System;

namespace Prompt
{
    public static class Program
    {
        public static int Main(string[] args)
        {
            Console.Write("Order number: ");
            var answer = Console.ReadLine();
            Console.WriteLine("Looking up " + answer);
            return 0;
        }
    }
}
""",
    # Does not parse: an element is never closed.
    "Prompt/App.config": '<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n  <appSettings>\n    <add key="Mode" value="ask" />\n</configuration>\n',
    "Poller/Poller.csproj": _project("Poller", "Exe", ['<Reference Include="System" />', '<Reference Include="System.ServiceProcess" />'],
                                     ["PollerService.cs", "Program.cs"]),
    "Poller/PollerService.cs": """using System.ServiceProcess;

namespace Poller
{
    public class PollerService : ServiceBase
    {
        protected override void OnStart(string[] args) { }
    }
}
""",
    "Poller/Program.cs": """using System.ServiceProcess;

namespace Poller
{
    public static class Program
    {
        public static void Main() => ServiceBase.Run(new PollerService());
    }
}
""",
}

DESKTOP_FILES = {
    "Desk/Desk.csproj": _project("Desk", "WinExe", ['<Reference Include="System" />', '<Reference Include="System.Windows.Forms" />'],
                                 ["MainForm.cs", "Program.cs"]),
    "Desk/MainForm.cs": """using System.Windows.Forms;

namespace Desk
{
    public class MainForm : Form
    {
    }
}
""",
    "Desk/Program.cs": """using System;
using System.Windows.Forms;

namespace Desk
{
    public static class Program
    {
        [STAThread]
        public static void Main() => Application.Run(new MainForm());
    }
}
""",
    "Board/Board.csproj": _project("Board", "WinExe", ['<Reference Include="System" />', '<Reference Include="PresentationFramework" />',
                                                       '<Reference Include="System.Xaml" />'], ["MainWindow.xaml.cs"],
                                   more='\n  <ItemGroup>\n    <Page Include="MainWindow.xaml" />\n  </ItemGroup>'),
    "Board/MainWindow.xaml": """<Window x:Class="Board.MainWindow"
        xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" Title="Board">
  <Grid />
</Window>
""",
    "Board/MainWindow.xaml.cs": """using System.Windows;

namespace Board
{
    public partial class MainWindow : Window
    {
    }
}
""",
}

SHOP_FILES = {
    "Shop/Shop.csproj": _project("Shop", "Library", ['<Reference Include="System" />', '<Reference Include="System.Web" />'],
                                 ["Default.aspx.cs"], extra=WEBFORMS_GUIDS,
                                 more='\n  <ItemGroup>\n    <Content Include="Default.aspx" />\n    <Content Include="Web.config" />\n  </ItemGroup>'),
    "Shop/Default.aspx": '<%@ Page Language="C#" CodeBehind="Default.aspx.cs" Inherits="Shop.DefaultPage" %>\n<html><body>Shop</body></html>\n',
    "Shop/Default.aspx.cs": """using System;
using System.Web.UI;

namespace Shop
{
    public partial class DefaultPage : Page
    {
        protected void Page_Load(object sender, EventArgs e) { }
    }
}
""",
    "Shop/Web.config": '<?xml version="1.0"?>\n<configuration>\n  <system.web>\n    <compilation targetFramework="4.7" />\n'
                       '  </system.web>\n</configuration>\n',
}

MODERN_FILES = {
    "Modern/Api/Api.csproj": SDK_WEB.format(framework="net8.0", extra="\n    <AspNetCoreHostingModel>InProcess</AspNetCoreHostingModel>",
                                            packages=_packages([("Acme.Text", "1.0.0"), ("Acme.Http", "1.2.0"),
                                                                ("Acme.Crypto", "2.0.0"), ("Acme.Legacy", "1.0.0"),
                                                                ("Acme.Classic", "3.0.0"), ("Acme.Feed", "1.0.0"),
                                                                ("System.Text.Json", "6.0.0")])),
    "Modern/Api/Program.cs": """using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.Hosting;

namespace Api
{
    public static class Program
    {
        public static void Main(string[] args) =>
            Host.CreateDefaultBuilder(args)
                .ConfigureWebHostDefaults(web => web.UseIIS().UseStartup<Startup>())
                .Build()
                .Run();
    }
}
""",
    "Modern/Api/Startup.cs": """using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;

namespace Api
{
    public class Startup
    {
        public void ConfigureServices(IServiceCollection services) => services.AddControllers();

        public void Configure(IApplicationBuilder app)
        {
            app.UseRouting();
            app.UseEndpoints(endpoints => endpoints.MapControllers());
        }
    }
}
""",
    "Modern/Api/web.config": """<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <system.webServer>
    <handlers>
      <add name="aspNetCore" path="*" verb="*" modules="AspNetCoreModuleV2" resourceType="Unspecified" />
    </handlers>
    <aspNetCore processPath="dotnet" arguments=".\\Api.dll" hostingModel="inprocess" />
  </system.webServer>
</configuration>
""",
    "Modern/Api/Dockerfile": """FROM mcr.microsoft.com/dotnet/sdk AS build
WORKDIR /src
COPY . .
RUN dotnet publish -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet AS final
WORKDIR /app
COPY --from=build /app .
RUN chown -R 1000:1000 /app
EXPOSE 80
ENV ASPNETCORE_URLS=http://+:80
ENTRYPOINT ["dotnet", "Api.dll"]
""",
    "Modern/Worker/Worker.csproj": SDK_WORKER.format(framework="net10.0", packages=""),
    "Modern/Worker/Program.cs": """using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

var builder = Host.CreateApplicationBuilder(args);
builder.Services.AddHostedService<Worker.Poll>();
builder.Build().Run();
""",
    "Modern/Worker/Poll.cs": """using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Hosting;

namespace Worker
{
    public class Poll : BackgroundService
    {
        protected override Task ExecuteAsync(CancellationToken stoppingToken) => Task.Delay(1000, stoppingToken);
    }
}
""",
    "Modern/Worker/build.cmd": "@echo off\r\ndotnet publish -c Release -r win-x64\r\n",
    "Modern/WinSvc/WinSvc.csproj": SDK_WORKER.format(framework="net10.0", packages=_packages(
        [("Microsoft.Extensions.Hosting.WindowsServices", "8.0.0")])),
    "Modern/WinSvc/Program.cs": """using Microsoft.Extensions.Hosting;

Host.CreateDefaultBuilder(args)
    .UseWindowsService()
    .Build()
    .Run();
""",
}


def _from(fixture_files: dict, folders: tuple[str, ...]) -> dict:
    return {path: body for path, body in fixture_files.items() if path.split("/", 1)[0] in folders}


def files(tag: str) -> dict[str, str]:
    """Every file of the repository, for the run's tag (the client feed's URL)."""
    out = {
        **CORE_FILES, **JOB_FILES, **DESKTOP_FILES, **SHOP_FILES, **MODERN_FILES,
        **_from(framework_only.FILES, ("Data", "WebKit", "Identity", "Flow")),
        **_from(guidance.FILES, ("Etl", "Orders", "Legacy", "Web", "lib", "packages")),
        "NuGet.config": '<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n  <packageSources>\n    <clear />\n'
                        f'    <add key="client-a" value="{FEED.format(tag=tag)}" />\n  </packageSources>\n</configuration>\n',
    }
    return out


# Where the scan must find each item: (project, file); file None for an item located on the project itself.
EXPECTED: dict[str, set[tuple[str, str | None]]] = {
    # ---- occurrence items, located per file
    "datetime-now-usage": {("Core/Core.csproj", "Core/Clock.cs")},
    "encoding-default": {("Core/Core.csproj", "Core/Text.cs")},
    "registry-access": {("Core/Core.csproj", "Core/Settings.cs")},
    "event-log-usage": {("Core/Core.csproj", "Core/Audit.cs")},
    "hardcoded-windows-path": {("Core/Core.csproj", "Core/Paths.cs")},
    "backslash-path-building": {("Core/Core.csproj", "Core/Paths.cs")},
    "system-drawing-common": {("Core/Core.csproj", "Core/Thumbnails.cs")},
    "serilog-file-sink": {("Core/Core.csproj", "Core/Logging.cs")},
    "custom-file-logger-provider": {("Core/Core.csproj", "Core/FileLogger.cs")},
    "unqualified-hostname": {("Core/Core.csproj", "Core/Pricing.cs")},
    "linq-to-sql-usage": {("Data/Data.csproj", "Data/OrdersContext.cs")},
    "system-web-in-library": {("WebKit/WebKit.csproj", "WebKit/AuditModule.cs")},
    "wif-usage": {("Identity/Identity.csproj", "Identity/SignIn.cs")},
    "directory-services-usage": {("Identity/Identity.csproj", "Identity/People.cs")},
    "windows-workflow-usage": {("Flow/Flow.csproj", "Flow/ApproveOrder.cs")},
    "windows-auth-connection-string": {("Nightly/Nightly.csproj", "Nightly/App.config")},
    "sensitive-config-key": {("Nightly/Nightly.csproj", "Nightly/App.config")},
    "enterprise-vault-secret-reference": {("Nightly/Nightly.csproj", "Nightly/App.config")},
    "unparseable-config-file": {("Prompt/Prompt.csproj", "Prompt/App.config")},
    "package-upgrade-safe": {("Modern/Api/Api.csproj", "Modern/Api/Api.csproj")},
    "package-upgrade-breaking": {("Modern/Api/Api.csproj", "Modern/Api/Api.csproj")},
    "package-vulnerable": {("Modern/Api/Api.csproj", "Modern/Api/Api.csproj")},
    "package-replacement-required": {("Modern/Api/Api.csproj", "Modern/Api/Api.csproj")},
    "package-not-approved": {("Modern/Api/Api.csproj", "Modern/Api/Api.csproj")},
    "package-provided-by-framework": {("Modern/Api/Api.csproj", "Modern/Api/Api.csproj")},
    # ---- application items, located on the project
    "msmq-usage": {("Core/Core.csproj", None)},
    "windows-only-assembly-reference": {("Core/Core.csproj", None)},
    "fx47-class-library": {("Core/Core.csproj", None), ("Data/Data.csproj", None)},
    "legacy-project-format": {("Core/Core.csproj", None), ("Nightly/Nightly.csproj", None)},
    "packages-config": {("Core/Core.csproj", None)},
    "console-batch-job": {("Nightly/Nightly.csproj", None)},
    "wcf-nettcp-client": {("Nightly/Nightly.csproj", None)},
    "interactive-console-tool": {("Prompt/Prompt.csproj", None)},
    "windows-service": {("Poller/Poller.csproj", None)},
    "winforms-desktop": {("Desk/Desk.csproj", None)},
    "wpf-desktop": {("Board/Board.csproj", None)},
    "aspnet-webforms": {("Shop/Shop.csproj", None)},
    "fx-aspnet-mvc": {("Web/Web.csproj", None)},
    "wcf-service": {("Orders/Orders.csproj", None)},
    "wcf-service-host": {("Orders/Orders.csproj", None)},
    "asmx-service": {("Legacy/Legacy.csproj", None)},
    "windows-build-pipeline": {("Legacy/Legacy.csproj", None), ("Modern/Worker/Worker.csproj", None)},
    "ssis-package": {("Etl/Etl.dtproj", None)},
    "aspnetcore-rest-api-legacy": {("Modern/Api/Api.csproj", None)},
    "aspnetcore-iis-hosting": {("Modern/Api/Api.csproj", None)},
    "target-framework-retarget": {("Modern/Api/Api.csproj", None)},
    "missing-health-endpoint": {("Modern/Api/Api.csproj", None), ("Orders/Orders.csproj", None)},
    "container-runs-as-root": {("Modern/Api/Api.csproj", None)},
    "container-privileged-port": {("Modern/Api/Api.csproj", None)},
    "container-fixed-user-writable-path": {("Modern/Api/Api.csproj", None)},
    "missing-dockerfile": {("Modern/Worker/Worker.csproj", None), ("Orders/Orders.csproj", None)},
    "missing-ocp4-manifests": {("Modern/Api/Api.csproj", None), ("Orders/Orders.csproj", None)},
    "modern-worker-service": {("Modern/Worker/Worker.csproj", None)},
    "windows-service-hosting": {("Modern/WinSvc/WinSvc.csproj", None)},
}


def write(root: Path, tag: str = "local") -> None:
    for rel, body in files(tag).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m tests.fixtures.coverage_repository <empty folder>")
    target = Path(sys.argv[1])
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise SystemExit(f"{target} is not empty")
    write(target)
    print(f"wrote {len(files('local'))} files to {target}")
