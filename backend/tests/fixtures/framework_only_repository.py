"""A small, made-up .NET Framework repository whose class libraries use APIs that exist only on .NET Framework
(tests/test_framework_only_apis.py): the 2026-11-26 hand-off "framework-only APIs not detected". Nothing here comes from a
client's code.

    Data/       old-style class library: LINQ to SQL (a DataContext subclass, Table<T>, a .dbml file), and a package built
                only for .NET Framework referenced by path (lib/NET45 only)
    WebKit/     old-style class library using System.Web: HttpContext.Current, an IHttpModule, and a Web API exception
                handler (System.Web.Http): a library, never the classic MVC / Web API application item
    Identity/   old-style class library: Windows Identity Foundation (FederatedAuthentication), the signed-in user's
                checks (UserPrincipal.Current, IsInRole), a directory lookup of other users, a claim-type constant and
                an endpoint on an unqualified host
    Flow/       old-style class library: Windows Workflow Foundation (a CodeActivity and a .xaml workflow)
    Web/        a classic ASP.NET WCF service (the web application project type GUID, web.config, a .svc file) on .NET
                Framework, referencing every library
    Tool/       an old-style console tool referencing Flow only: left out of the scope, it keeps Flow on .NET Framework

ENTLIB is what the lookup cache says about the package referenced by path: its only assets are .NET Framework ones, and
its dependencies have no framework groups (recorded as `any`).
"""
from pathlib import Path

from tests.fixtures.guidance_repository import _project
from tests.fixtures.services_repository import WEB_GUIDS

ENTLIB = {"6.0.1304": {"dependencyFrameworks": ["any"], "libFrameworks": ["net45"]}}


def _ref(name: str) -> str:
    return f'<ProjectReference Include="..\\{name}\\{name}.csproj"><Name>{name}</Name></ProjectReference>'


FILES = {
    # ---- LINQ to SQL, and a package built only for .NET Framework
    "Data/Data.csproj": _project("Data", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.Core" />', '<Reference Include="System.Data" />',
        '<Reference Include="System.Data.Linq" />',
        '<Reference Include="Microsoft.Practices.EnterpriseLibrary.Data, Version=6.0.0.0">'
        '<HintPath>..\\packages\\EnterpriseLibrary.Data.6.0.1304\\lib\\NET45\\Microsoft.Practices.EnterpriseLibrary.Data.dll'
        '</HintPath></Reference>',
    ], ["OrdersContext.cs", "OrderRepository.cs"], more='\n  <ItemGroup>\n    <None Include="Orders.dbml" />\n  </ItemGroup>'),
    "Data/Orders.dbml": """<?xml version="1.0" encoding="utf-8"?>
<Database Name="Orders" Class="OrdersContext" xmlns="http://schemas.microsoft.com/linqtosql/dbml/2007">
  <Table Name="dbo.Orders" Member="Orders">
    <Type Name="Order">
      <Column Name="Id" Type="System.Int32" DbType="Int NOT NULL" IsPrimaryKey="true" CanBeNull="false" />
      <Column Name="Total" Type="System.Decimal" DbType="Money NOT NULL" CanBeNull="false" />
    </Type>
  </Table>
</Database>
""",
    "Data/OrdersContext.cs": """using System.Data.Linq;
using System.Data.Linq.Mapping;

namespace Data
{
    public class OrdersContext : DataContext
    {
        public OrdersContext(string connection) : base(connection) { }

        public Table<Order> Orders => GetTable<Order>();
    }

    [Table(Name = "dbo.Orders")]
    public class Order
    {
        [Column(IsPrimaryKey = true)] public int Id { get; set; }
        [Column] public decimal Total { get; set; }
    }
}
""",
    "Data/OrderRepository.cs": """using System.Configuration;
using System.Data.Linq;
using System.Linq;

namespace Data
{
    public class OrderRepository
    {
        public decimal TotalOf(int id)
        {
            using (var db = new OrdersContext(ConfigurationManager.ConnectionStrings["Orders"].ConnectionString))
            {
                return db.Orders.Where(o => o.Id == id).Select(o => o.Total).Single();
            }
        }
    }
}
""",

    # ---- System.Web in a library
    "WebKit/WebKit.csproj": _project("WebKit", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.Web" />', '<Reference Include="System.Web.Http" />',
    ], ["RequestInfo.cs", "AuditModule.cs", "ErrorHandler.cs"]),
    "WebKit/RequestInfo.cs": """using System.Web;

namespace WebKit
{
    public static class RequestInfo
    {
        public static string ClientAddress() => HttpContext.Current.Request.UserHostAddress;
    }
}
""",
    "WebKit/AuditModule.cs": """using System;
using System.Web;

namespace WebKit
{
    public class AuditModule : IHttpModule
    {
        public void Init(HttpApplication application)
        {
            application.BeginRequest += (sender, e) => Console.Error.WriteLine("request");
        }

        public void Dispose() { }
    }
}
""",
    "WebKit/ErrorHandler.cs": """using System.Web.Http.ExceptionHandling;

namespace WebKit
{
    public class ErrorHandler : ExceptionHandler
    {
        public override void Handle(ExceptionHandlerContext context) { }
    }
}
""",

    # ---- WIF, the signed-in user's checks, a directory lookup of others, a claim type, an endpoint
    "Identity/Identity.csproj": _project("Identity", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.IdentityModel" />',
        '<Reference Include="System.IdentityModel.Services" />', '<Reference Include="System.DirectoryServices" />',
        '<Reference Include="System.DirectoryServices.AccountManagement" />',
    ], ["SignIn.cs", "Access.cs", "People.cs", "AppClaimTypes.cs", "Endpoints.cs"]),
    "Identity/SignIn.cs": """using System.IdentityModel.Services;

namespace Identity
{
    public static class SignIn
    {
        public static void SignOut() => FederatedAuthentication.SessionAuthenticationModule.SignOut();
    }
}
""",
    "Identity/Access.cs": """using System.DirectoryServices.AccountManagement;
using System.Threading;

namespace Identity
{
    public static class Access
    {
        public static bool IsAdmin() => Thread.CurrentPrincipal.IsInRole("APPDOMAIN\\\\OrderAdmins");

        public static string CurrentName() => UserPrincipal.Current.DisplayName;
    }
}
""",
    "Identity/People.cs": """using System.DirectoryServices;
using System.DirectoryServices.AccountManagement;

namespace Identity
{
    public static class People
    {
        public static string NameOf(string login)
        {
            using (var context = new PrincipalContext(ContextType.Domain))
            {
                return UserPrincipal.FindByIdentity(context, login)?.DisplayName;
            }
        }

        public static int Count()
        {
            using (var searcher = new DirectorySearcher("(objectClass=user)"))
            {
                return searcher.FindAll().Count;
            }
        }
    }
}
""",
    "Identity/AppClaimTypes.cs": """namespace Identity
{
    public static class AppClaimTypes
    {
        public const string Region = "http://idsrv/claims/region";
    }
}
""",
    "Identity/Endpoints.cs": """namespace Identity
{
    public static class Endpoints
    {
        public const string Pricing = "http://pricing/api/prices";
    }
}
""",

    # ---- Windows Workflow
    "Flow/Flow.csproj": _project("Flow", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.Activities" />', '<Reference Include="System.Xaml" />',
    ], ["ApproveOrder.cs"], more='\n  <ItemGroup>\n    <XamlAppDef Include="Approval.xaml" />\n  </ItemGroup>'),
    "Flow/ApproveOrder.cs": """using System.Activities;

namespace Flow
{
    public sealed class ApproveOrder : CodeActivity<bool>
    {
        public InArgument<decimal> Total { get; set; }

        protected override bool Execute(CodeActivityContext context) => Total.Get(context) < 1000m;
    }
}
""",
    "Flow/Approval.xaml": """<Activity x:Class="Flow.Approval"
          xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities"
          xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
  <Sequence>
    <WriteLine Text="approved" />
  </Sequence>
</Activity>
""",

    # ---- the WCF service on .NET Framework that references every library
    "Web/Web.csproj": _project("Web", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.ServiceModel" />',
        '<Reference Include="System.Runtime.Serialization" />',
        _ref("Data"), _ref("WebKit"), _ref("Identity"), _ref("Flow"),
    ], ["IOrderService.cs", "OrderService.svc.cs"], extra=WEB_GUIDS,
        more='\n  <ItemGroup>\n    <Content Include="OrderService.svc" />\n    <Content Include="Web.config" />\n  </ItemGroup>'),
    "Web/IOrderService.cs": """using System.Runtime.Serialization;
using System.ServiceModel;

namespace Web
{
    [ServiceContract]
    public interface IOrderService
    {
        [OperationContract]
        OrderReply GetOrder(int id);
    }

    [DataContract]
    public class OrderReply
    {
        [DataMember] public decimal Total { get; set; }
    }
}
""",
    "Web/OrderService.svc.cs": """using Data;

namespace Web
{
    public class OrderService : IOrderService
    {
        public OrderReply GetOrder(int id) => new OrderReply { Total = new OrderRepository().TotalOf(id) };
    }
}
""",
    "Web/OrderService.svc": '<%@ ServiceHost Language="C#" Service="Web.OrderService" CodeBehind="OrderService.svc.cs" %>\n',
    "Web/Web.config": """<?xml version="1.0"?>
<configuration>
  <system.serviceModel>
    <services>
      <service name="Web.OrderService">
        <endpoint address="" binding="basicHttpBinding" contract="Web.IOrderService" />
      </service>
    </services>
  </system.serviceModel>
</configuration>
""",

    # ---- a console tool that references Flow only
    "Tool/Tool.csproj": _project("Tool", "Exe", ['<Reference Include="System" />', _ref("Flow")], ["Program.cs"]),
    "Tool/Program.cs": """using System;

namespace Tool
{
    public static class Program
    {
        public static int Main(string[] args)
        {
            Console.WriteLine(new Flow.ApproveOrder() != null);
            return 0;
        }
    }
}
""",
}

LIBRARIES = ("Data/Data.csproj", "WebKit/WebKit.csproj", "Identity/Identity.csproj", "Flow/Flow.csproj")

EXPECTED = {
    "linq-to-sql-usage": {"Data/Data.csproj"},
    "system-web-in-library": {"WebKit/WebKit.csproj"},
    "wif-usage": {"Identity/Identity.csproj"},
    "windows-workflow-usage": {"Flow/Flow.csproj"},
    "directory-services-usage": {"Identity/Identity.csproj"},
    "fx47-class-library": set(LIBRARIES),
    "wcf-service": {"Web/Web.csproj"},
    "missing-dockerfile": {"Web/Web.csproj"},
    "missing-ocp4-manifests": {"Web/Web.csproj"},
    "unqualified-hostname": {"Identity/Identity.csproj"},
}

# The four removals and the library each changes.
REMOVALS = {
    "linq-to-sql-usage": "Data/Data.csproj",
    "system-web-in-library": "WebKit/WebKit.csproj",
    "wif-usage": "Identity/Identity.csproj",
    "windows-workflow-usage": "Flow/Flow.csproj",
}


def write(root: Path) -> None:
    for rel, body in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
