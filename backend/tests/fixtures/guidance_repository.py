"""A small, made-up .NET Framework repository that triggers, through a real scan, each catalog item whose engine
guidance was written on 2026-11-24 (tests/test_guidance_fixtures.py). Nothing here comes from a client's code.

    Batch/      old-style console job on .NET Framework 4.7: packages.config with HintPath references into packages/,
                the SSIS runtime referenced by path (Windows-only), Encoding.Default, a directory lookup
    Shared/     old-style class library on .NET Framework 4.7, referenced by Batch
    Etl/        an SSIS package project: an Execute SQL task, a ragged-right flat file source, a derived column and an
                OLE DB destination
    Orders/     a WCF service hosted in IIS through a .svc file: two operations, two data contracts, one fault
    Legacy/     an ASMX web service with two web methods
    Web/        a classic ASP.NET MVC controller with Global.asax
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
        '<ProjectReference Include="..\\Shared\\Shared.csproj"><Name>Shared</Name></ProjectReference>',
    ], ["Program.cs", "Directory.cs", "Export.cs"]),
    "Batch/packages.config": '<?xml version="1.0" encoding="utf-8"?>\n<packages>\n'
                             '  <package id="Newtonsoft.Json" version="13.0.1" targetFramework="net47" />\n</packages>\n',
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
        more='\n  <ItemGroup>\n    <Content Include="OrderService.svc" />\n    <Content Include="Web.config" />\n  </ItemGroup>'),
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

# The items this repository triggers, and on which project.
EXPECTED = {
    "ssis-package": "Etl/Etl.dtproj",
    "fx47-class-library": "Shared/Shared.csproj",
    "wcf-service": "Orders/Orders.csproj",
    "wcf-service-host": "Orders/Orders.csproj",
    "asmx-service": "Legacy/Legacy.csproj",
    "directory-services-usage": "Batch/Batch.csproj",
    "encoding-default": "Batch/Batch.csproj",
    "fx-aspnet-mvc": "Web/Web.csproj",
    "windows-only-assembly-reference": "Batch/Batch.csproj",
    "legacy-project-format": "Batch/Batch.csproj",
    "packages-config": "Batch/Batch.csproj",
}


def write(root: Path) -> None:
    for rel, body in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
