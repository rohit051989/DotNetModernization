"""A small, made-up .NET Framework repository that triggers, through a real scan, each catalog item whose engine
guidance was written on 2026-11-24 (tests/test_guidance_fixtures.py). Nothing here comes from a client's code.

    Batch/      old-style console job on .NET Framework 4.7: packages.config with HintPath references into packages/
                (System.Memory with the packages it depends on, one of them pinned higher than System.Memory asks), the
                SSIS runtime referenced by path (Windows-only), Encoding.Default, a directory lookup
    Shared/     old-style class library on .NET Framework 4.7, referenced by Batch
    Etl/        an SSIS package project: an Execute SQL task, a ragged-right flat file source, a derived column and an
                OLE DB destination
    Orders/     a classic ASP.NET WCF web project (the web application project type GUID, web.config, a .svc file, a
                packages.config): two operations, two data contracts, one fault
    Legacy/     an ASMX web service with two web methods
    Web/        a classic ASP.NET MVC controller with Global.asax

The repository's nuget.config names one feed, FEED with the run's tag; LOOKUPS is what that feed would say about the
packages Batch pins, for the scan's offline lookups (tests/test_guidance_fixtures.py puts them in the lookup cache).
"""
from pathlib import Path

OLD_STYLE = """<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="15.0" DefaultTargets="Build" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <Import Project="$(MSBuildExtensionsPath)\\$(MSBuildToolsVersion)\\Microsoft.Common.props" />
  <PropertyGroup>
    <OutputType>{output}</OutputType>
    <RootNamespace>{name}</RootNamespace>
    <AssemblyName>{name}</AssemblyName>
    <TargetFrameworkVersion>v4.7</TargetFrameworkVersion>{extra}
  </PropertyGroup>
  <ItemGroup>
{references}
  </ItemGroup>
  <ItemGroup>
{compile}
  </ItemGroup>{more}
  <Import Project="$(MSBuildToolsPath)\\Microsoft.CSharp.targets" />
</Project>
"""


def _project(name: str, output: str, references: list[str], compile_: list[str], extra: str = "", more: str = "") -> str:
    return OLD_STYLE.format(name=name, output=output, extra=extra, more=more,
                            references="\n".join(f"    {r}" for r in references),
                            compile="\n".join(f'    <Compile Include="{c}" />' for c in compile_))


FILES = {
    # ---- the batch job
    "Batch/Batch.csproj": _project("Batch", "Exe", [
        '<Reference Include="System" />',
        '<Reference Include="System.DirectoryServices" />',
        '<Reference Include="Microsoft.SqlServer.ManagedDTS, Version=13.0.0.0"><HintPath>..\\lib\\Microsoft.SqlServer.ManagedDTS.dll</HintPath></Reference>',
        '<Reference Include="Newtonsoft.Json, Version=13.0.0.0"><HintPath>..\\packages\\Newtonsoft.Json.13.0.1\\lib\\net45\\Newtonsoft.Json.dll</HintPath></Reference>',
        '<Reference Include="System.Memory, Version=4.0.1.1"><HintPath>..\\packages\\System.Memory.4.5.4\\lib\\net461\\System.Memory.dll</HintPath></Reference>',
        '<Reference Include="System.Buffers, Version=4.0.3.0"><HintPath>..\\packages\\System.Buffers.4.5.1\\lib\\net461\\System.Buffers.dll</HintPath></Reference>',
        '<Reference Include="System.Numerics.Vectors, Version=4.1.4.0"><HintPath>..\\packages\\System.Numerics.Vectors.4.5.0\\lib\\net46\\System.Numerics.Vectors.dll</HintPath></Reference>',
        '<Reference Include="System.Runtime.CompilerServices.Unsafe, Version=6.0.0.0"><HintPath>..\\packages\\System.Runtime.CompilerServices.Unsafe.6.0.0\\lib\\net461\\System.Runtime.CompilerServices.Unsafe.dll</HintPath></Reference>',
        '<ProjectReference Include="..\\Shared\\Shared.csproj"><Name>Shared</Name></ProjectReference>',
    ], ["Program.cs", "Directory.cs", "Export.cs"]),
    # System.Memory 4.5.4 asks for System.Runtime.CompilerServices.Unsafe 4.5.3 or higher; 6.0.0 is pinned here, so the
    # move to PackageReference keeps it, at 6.0.0. System.Buffers and System.Numerics.Vectors are pinned at the version
    # restore resolves, so they are left out.
    "Batch/packages.config": '<?xml version="1.0" encoding="utf-8"?>\n<packages>\n'
                             '  <package id="Newtonsoft.Json" version="13.0.1" targetFramework="net47" />\n'
                             '  <package id="System.Buffers" version="4.5.1" targetFramework="net47" />\n'
                             '  <package id="System.Memory" version="4.5.4" targetFramework="net47" />\n'
                             '  <package id="System.Numerics.Vectors" version="4.5.0" targetFramework="net47" />\n'
                             '  <package id="System.Runtime.CompilerServices.Unsafe" version="6.0.0" targetFramework="net47" />\n'
                             '</packages>\n',
    "Batch/Program.cs": """using Microsoft.SqlServer.Dts.Runtime;

namespace Batch
{
    public static class Program
    {
        public static int Main(string[] args)
        {
            var app = new Application();
            Package package = app.LoadPackage(args[0], null);
            DTSExecResult result = package.Execute();
            return result == DTSExecResult.Success ? 0 : 1;
        }
    }
}
""",
    "Batch/Directory.cs": """using System.DirectoryServices;

namespace Batch
{
    public static class Directory
    {
        public static string Mail(string account)
        {
            using (var searcher = new DirectorySearcher("(sAMAccountName=" + account + ")"))
            {
                SearchResult found = searcher.FindOne();
                return found == null ? null : (string)found.Properties["mail"][0];
            }
        }
    }
}
""",
    "Batch/Export.cs": """using System.IO;
using System.Text;

namespace Batch
{
    public static class Export
    {
        public static void Write(string path, string text)
        {
            File.WriteAllText(path, text, Encoding.Default);
        }
    }
}
""",
    "lib/Microsoft.SqlServer.ManagedDTS.dll": "not a real assembly: stands for a DLL kept in the repository\n",
    "packages/Newtonsoft.Json.13.0.1/lib/net45/Newtonsoft.Json.dll": "not a real assembly: a restored package\n",

    # ---- the shared class library
    "Shared/Shared.csproj": _project("Shared", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.Configuration" />', '<Reference Include="System.Data" />',
    ], ["Settings.cs", "Properties\\AssemblyInfo.cs"]),
    "Shared/Settings.cs": """using System.Configuration;

namespace Shared
{
    public static class Settings
    {
        public static string Get(string name) => ConfigurationManager.AppSettings[name];
    }
}
""",
    "Shared/Properties/AssemblyInfo.cs": 'using System.Reflection;\n[assembly: AssemblyTitle("Shared")]\n'
                                         '[assembly: AssemblyVersion("1.0.0.0")]\n',

    # ---- the SSIS package project
    "Etl/Etl.dtproj": """<?xml version="1.0" encoding="utf-8"?>
<Project xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <DeploymentModel>Project</DeploymentModel>
  <Packages><Package Name="Load.dtsx" /></Packages>
</Project>
""",
    "Etl/Load.dtsx": """<?xml version="1.0"?>
<DTS:Executable xmlns:DTS="www.microsoft.com/SqlServer/Dts" DTS:ObjectName="Load">
  <DTS:Executables>
    <DTS:Executable DTS:ObjectName="Clear staging" DTS:ExecutableType="Microsoft.ExecuteSQLTask">
      <DTS:ObjectData><SQLTask:SqlTaskData xmlns:SQLTask="www.microsoft.com/sqlserver/dts/tasks/sqltask"
        SQLTask:SqlStatementSource="delete from dbo.Staging" /></DTS:ObjectData>
    </DTS:Executable>
    <DTS:Executable DTS:ObjectName="Load rows" DTS:ExecutableType="Microsoft.Pipeline">
      <DTS:ObjectData>
        <pipeline>
          <components>
            <component name="Rows file" componentClassID="Microsoft.FlatFileSource">
              <properties><property name="RetainNulls">true</property></properties>
            </component>
            <component name="Short code" componentClassID="Microsoft.DerivedColumn">
              <properties><property name="Expression">SUBSTRING(Col3,1,5)</property></properties>
            </component>
            <component name="Staging table" componentClassID="Microsoft.OLEDBDestination">
              <properties><property name="FastLoadKeepNulls">false</property></properties>
            </component>
          </components>
        </pipeline>
      </DTS:ObjectData>
    </DTS:Executable>
  </DTS:Executables>
</DTS:Executable>
""",

    # ---- the WCF service, hosted in IIS
    "Orders/Orders.csproj": _project("Orders", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.ServiceModel" />',
        '<Reference Include="System.Runtime.Serialization" />',
    ], ["IOrderService.cs", "OrderService.svc.cs"], extra="\n    <ProjectTypeGuids>{349c5851-65df-11da-9384-00065b846f21};{fae04ec0-301f-11d3-bf4b-00c04f79efbc}</ProjectTypeGuids>",
        more='\n  <ItemGroup>\n    <Content Include="OrderService.svc" />\n    <Content Include="Web.config" />\n'
             '    <None Include="packages.config" />\n  </ItemGroup>'),
    "Orders/packages.config": '<?xml version="1.0" encoding="utf-8"?>\n<packages>\n'
                              '  <package id="Newtonsoft.Json" version="13.0.1" targetFramework="net47" />\n</packages>\n',
    "Orders/IOrderService.cs": """using System.Runtime.Serialization;
using System.ServiceModel;

namespace Orders
{
    [ServiceContract]
    public interface IOrderService
    {
        [OperationContract]
        [FaultContract(typeof(OrderFault))]
        OrderReply GetOrder(OrderQuery query);

        [OperationContract]
        int CountOrders(string customer);
    }

    [DataContract]
    public class OrderQuery
    {
        [DataMember] public string Number { get; set; }
    }

    [DataContract]
    public class OrderReply
    {
        [DataMember] public string Number { get; set; }
        [DataMember] public decimal? Total { get; set; }
    }

    [DataContract]
    public class OrderFault
    {
        [DataMember] public string Reason { get; set; }
    }
}
""",
    "Orders/OrderService.svc.cs": """using System.ServiceModel;

namespace Orders
{
    public class OrderService : IOrderService
    {
        public OrderReply GetOrder(OrderQuery query)
        {
            if (string.IsNullOrEmpty(query.Number))
                throw new FaultException<OrderFault>(new OrderFault { Reason = "no number" });
            return new OrderReply { Number = query.Number, Total = null };
        }

        public int CountOrders(string customer) => 0;
    }
}
""",
    "Orders/OrderService.svc": '<%@ ServiceHost Language="C#" Service="Orders.OrderService" CodeBehind="OrderService.svc.cs" %>\n',
    "Orders/Web.config": """<?xml version="1.0"?>
<configuration>
  <system.serviceModel>
    <services>
      <service name="Orders.OrderService">
        <endpoint address="" binding="basicHttpBinding" contract="Orders.IOrderService" />
      </service>
    </services>
  </system.serviceModel>
</configuration>
""",

    # ---- the ASMX service
    "Legacy/Legacy.csproj": _project("Legacy", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.Web" />', '<Reference Include="System.Web.Services" />',
    ], ["Quotes.asmx.cs"], more='\n  <ItemGroup>\n    <Content Include="Quotes.asmx" />\n  </ItemGroup>'),
    "Legacy/Quotes.asmx": '<%@ WebService Language="C#" CodeBehind="Quotes.asmx.cs" Class="Legacy.Quotes" %>\n',
    "Legacy/Quotes.asmx.cs": """using System.Web.Services;

namespace Legacy
{
    [WebService(Namespace = "http://client-a.example/quotes")]
    public class Quotes : WebService
    {
        [WebMethod]
        public decimal Price(string code) => 0m;

        [WebMethod]
        public string[] Codes() => new string[0];
    }
}
""",

    # ---- the classic MVC application
    "Web/Web.csproj": _project("Web", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.Web" />', '<Reference Include="System.Web.Mvc" />',
    ], ["Controllers\\HomeController.cs", "Global.asax.cs"], more='\n  <ItemGroup>\n    <Content Include="Global.asax" />\n  </ItemGroup>'),
    "Web/Controllers/HomeController.cs": """using System.Web.Mvc;

namespace Web.Controllers
{
    public class HomeController : Controller
    {
        public ActionResult Index() => View();
    }
}
""",
    "Web/Global.asax": '<%@ Application Codebehind="Global.asax.cs" Inherits="Web.MvcApplication" Language="C#" %>\n',
    "Web/Global.asax.cs": """using System.Web.Mvc;

namespace Web
{
    public class MvcApplication : System.Web.HttpApplication
    {
        protected void Application_Start()
        {
            AreaRegistration.RegisterAllAreas();
        }
    }
}
""",
}

# The items this repository triggers, and on which projects.
EXPECTED = {
    "ssis-package": {"Etl/Etl.dtproj"},
    "fx47-class-library": {"Shared/Shared.csproj"},
    "wcf-service": {"Orders/Orders.csproj"},
    "wcf-service-host": {"Orders/Orders.csproj"},
    "asmx-service": {"Legacy/Legacy.csproj"},
    "directory-services-usage": {"Batch/Batch.csproj"},
    "encoding-default": {"Batch/Batch.csproj"},
    "fx-aspnet-mvc": {"Web/Web.csproj"},
    "windows-only-assembly-reference": {"Batch/Batch.csproj"},
    "legacy-project-format": {"Batch/Batch.csproj", "Shared/Shared.csproj"},
    "packages-config": {"Batch/Batch.csproj"},
}

# And where they must not be: a classic ASP.NET web project becomes SDK-style in its move to ASP.NET Core, never in a
# project file conversion of its own (2026-11-25); and a project with .svc or .asmx files is a web service project,
# with or without web.config or a web project type GUID (Legacy has neither), never a class library.
NOT_EXPECTED = {
    "legacy-project-format": {"Orders/Orders.csproj", "Legacy/Legacy.csproj", "Web/Web.csproj"},
    "fx47-class-library": {"Orders/Orders.csproj", "Legacy/Legacy.csproj"},
    "packages-config": {"Orders/Orders.csproj"},
}

FEED = "https://feed.client-a.example/{tag}"


def _version(version: str, framework: str, depends: dict[str, str] | None = None) -> dict:
    return {"version": version, "listed": True, "dependencyFrameworks": [framework], "libFrameworks": None,
            "dependencies": [{"framework": framework,
                              "packages": [{"id": i, "range": r} for i, r in sorted((depends or {}).items())]}]}


# What the feed says, per package (lower-case id): {version: its metadata}, newest first.
LOOKUPS = {
    "newtonsoft.json": {"13.0.1": _version("13.0.1", "net45")},
    "system.memory": {"4.5.4": _version("4.5.4", "net461", {"System.Buffers": "[4.5.1, )",
                                                            "System.Numerics.Vectors": "[4.5.0, )",
                                                            "System.Runtime.CompilerServices.Unsafe": "[4.5.3, )"})},
    "system.buffers": {"4.5.1": _version("4.5.1", "net45")},
    "system.numerics.vectors": {"4.5.0": _version("4.5.0", "net45")},
    "system.runtime.compilerservices.unsafe": {"6.0.0": _version("6.0.0", "net461"), "4.5.3": _version("4.5.3", "net45")},
}


def write(root: Path, tag: str = "local") -> None:
    files = {**FILES, "nuget.config": '<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n  <packageSources>\n'
                                      '    <clear />\n'
                                      f'    <add key="client-a" value="{FEED.format(tag=tag)}" />\n'
                                      '  </packageSources>\n</configuration>\n'}
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
