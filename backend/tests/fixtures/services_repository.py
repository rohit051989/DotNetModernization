"""A small, made-up .NET Framework repository of web services that share a class library (tests/test_plan_order.py): the
second repository of the 2026-11-25 review hand-off, gap 1. Nothing here comes from a client's code.

    Common/     old-style class library on .NET Framework 4.7
    Portal/     a classic ASP.NET MVC application (the MVC project type GUID, web.config, Global.asax), referencing Common
    Quotes/     a classic ASP.NET WCF service (the web application project type GUID, web.config, a .svc file),
                referencing Common

The libraries come first: the bridge on Common before the MVC move and the WCF rewrite that both reference it.
"""
from pathlib import Path

from tests.fixtures.guidance_repository import _project

WEB_GUIDS = "\n    <ProjectTypeGuids>{349c5851-65df-11da-9384-00065b846f21};{fae04ec0-301f-11d3-bf4b-00c04f79efbc}</ProjectTypeGuids>"
MVC_GUIDS = "\n    <ProjectTypeGuids>{E3E379DF-F4C6-4180-9B81-6769533ABE47};{349c5851-65df-11da-9384-00065b846f21};{fae04ec0-301f-11d3-bf4b-00c04f79efbc}</ProjectTypeGuids>"
COMMON = '<ProjectReference Include="..\\Common\\Common.csproj"><Name>Common</Name></ProjectReference>'

FILES = {
    "Common/Common.csproj": _project("Common", "Library", ['<Reference Include="System" />'], ["Money.cs"]),
    "Common/Money.cs": """namespace Common
{
    public static class Money
    {
        public static decimal Round(decimal value) => decimal.Round(value, 2);
    }
}
""",

    "Portal/Portal.csproj": _project("Portal", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.Web" />', '<Reference Include="System.Web.Mvc" />', COMMON,
    ], ["Controllers\\PricesController.cs", "Global.asax.cs"], extra=MVC_GUIDS,
        more='\n  <ItemGroup>\n    <Content Include="Global.asax" />\n    <Content Include="Web.config" />\n  </ItemGroup>'),
    "Portal/Controllers/PricesController.cs": """using System.Web.Mvc;
using Common;

namespace Portal.Controllers
{
    public class PricesController : Controller
    {
        public ActionResult Index(decimal value) => Content(Money.Round(value).ToString());
    }
}
""",
    "Portal/Global.asax": '<%@ Application Codebehind="Global.asax.cs" Inherits="Portal.MvcApplication" Language="C#" %>\n',
    "Portal/Global.asax.cs": """using System.Web.Mvc;

namespace Portal
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
    "Portal/Web.config": '<?xml version="1.0"?>\n<configuration>\n  <system.web>\n    <compilation targetFramework="4.7" />\n'
                         '  </system.web>\n</configuration>\n',

    "Quotes/Quotes.csproj": _project("Quotes", "Library", [
        '<Reference Include="System" />', '<Reference Include="System.ServiceModel" />',
        '<Reference Include="System.Runtime.Serialization" />', COMMON,
    ], ["IQuoteService.cs", "QuoteService.svc.cs"], extra=WEB_GUIDS,
        more='\n  <ItemGroup>\n    <Content Include="QuoteService.svc" />\n    <Content Include="Web.config" />\n  </ItemGroup>'),
    "Quotes/IQuoteService.cs": """using System.Runtime.Serialization;
using System.ServiceModel;

namespace Quotes
{
    [ServiceContract]
    public interface IQuoteService
    {
        [OperationContract]
        QuoteReply GetQuote(string code);
    }

    [DataContract]
    public class QuoteReply
    {
        [DataMember] public decimal Price { get; set; }
    }
}
""",
    "Quotes/QuoteService.svc.cs": """using Common;

namespace Quotes
{
    public class QuoteService : IQuoteService
    {
        public QuoteReply GetQuote(string code) => new QuoteReply { Price = Money.Round(1.005m) };
    }
}
""",
    "Quotes/QuoteService.svc": '<%@ ServiceHost Language="C#" Service="Quotes.QuoteService" CodeBehind="QuoteService.svc.cs" %>\n',
    "Quotes/Web.config": """<?xml version="1.0"?>
<configuration>
  <system.serviceModel>
    <services>
      <service name="Quotes.QuoteService">
        <endpoint address="" binding="basicHttpBinding" contract="Quotes.IQuoteService" />
      </service>
    </services>
  </system.serviceModel>
</configuration>
""",
}

EXPECTED = {
    "legacy-project-format": {"Common/Common.csproj"},
    "fx47-class-library": {"Common/Common.csproj"},
    "fx-aspnet-mvc": {"Portal/Portal.csproj"},
    "wcf-service": {"Quotes/Quotes.csproj"},
}


def write(root: Path) -> None:
    for rel, body in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
