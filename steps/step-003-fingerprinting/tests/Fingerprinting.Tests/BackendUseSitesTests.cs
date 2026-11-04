using Fingerprinting.Analysis;
using Fingerprinting.Outbound;
using Xunit;

namespace Fingerprinting.Tests;

/// <summary>29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md Part C9: <c>BackendReach</c> finds a database or an HTTP client
/// where it is used, not only where it is configured. The fixture has the shape of a layered web API: a controller, a
/// service, a repository over a context registered through a helper taking the connection name as a constant, and
/// clients calling through an HTTP helper and a client factory.</summary>
public class BackendUseSitesTests
{
    private const string Project = "src/Api/Api.csproj";
    private const string File = "src/Api/Code.cs";

    // Line numbers are not asserted: the assertions name the methods walked.
    private const string Code = """
        public class AccountsController
        {
            private readonly IAccountService _service;
            public AccountsController(IAccountService service) { _service = service; }
            public object Get(int id)
            {
                return _service.GetAccount(id);
            }
            public void Notify(object request)
            {
                _service.Welcome(request);
            }
        }
        public interface IAccountService { object GetAccount(int id); void Welcome(object request); }
        public class AccountService : IAccountService
        {
            private readonly IAccountRepository _repository;
            private readonly IVerificationClient _verification;
            private readonly NotificationClient _notification;
            public AccountService(IAccountRepository repository, IVerificationClient verification, NotificationClient notification)
            {
                _repository = repository;
                _verification = verification;
                _notification = notification;
            }
            public object GetAccount(int id)
            {
                _verification.Verify("holder");
                return _repository.GetById(id);
            }
            public void Welcome(object request) => _notification.Send(request);
        }
        public interface IAccountRepository { object GetById(int id); }
        public class AccountRepository : IAccountRepository
        {
            private readonly AccountsDbContext _db;
            private readonly OtherDbContext _other;
            public AccountRepository(AccountsDbContext db, OtherDbContext other) { _db = db; _other = other; }
            public object GetById(int id)
            {
                var other = _other.Things.ToList();
                return _db.Accounts
                    .AsNoTracking()
                    .SingleOrDefault(a => a.Id == id);
            }
            public void Save(object entity) { _db.Accounts.Add(entity); _db.SaveChanges(); }
        }
        public class AccountsDbContext : DbContext
        {
            public DbSet<Account> Accounts { get; set; }
        }
        public class OtherDbContext : DbContext
        {
            public DbSet<Thing> Things { get; set; }
        }
        public class ConnectionStringNames
        {
            public const string AccountsDatabase = "AccountsDatabase";
            public const string OtherDatabase = "OtherDatabase";
        }
        public static class Registration
        {
            public static void Add(IServiceCollection services)
            {
                AddContext<AccountsDbContext>(services, ConnectionStringNames.AccountsDatabase);
                AddContext<OtherDbContext>(services, ConnectionStringNames.OtherDatabase);
            }
            private static void AddContext<T>(IServiceCollection services, string name) { }
        }
        public interface IVerificationClient { void Verify(string holder); }
        public class VerificationClient : IVerificationClient
        {
            public const string ClientName = "VerificationApi";
            private readonly IHttpHelper _http;
            public void Verify(string holder)
            {
                _http.CallAsync<string>(ClientName, "v1/verifications", HttpMethod.Post, holder);
            }
        }
        public class NotificationClient
        {
            public const string ClientName = "NotificationApi";
            private readonly IEnterpriseHttpClientFactory _factory;
            public void Send(object request)
            {
                _factory.CreateClient(ClientName).PostAsJsonAsync("v1/notifications", request);
            }
        }
        """;

    private static Invocation Database(string id, string name) => new()
    {
        InvocationId = id,
        Mechanism = Mechanisms.Database,
        ProjectPath = Project,
        Endpoint = new Endpoint { Resolution = "partial" },
        Database = new DatabaseDetail { Name = name, Authentication = "unknown" },
        LinuxCompatibility = new LinuxCompatibility { Verdict = "unknown" },
        Confidence = 1,
        CallSites = [CallSiteAt("src/Api/appsettings.json", 4)],
    };

    private static Invocation Http(string id, string? clientName, string project = Project) => new()
    {
        InvocationId = id,
        Mechanism = Mechanisms.HttpClient,
        ProjectPath = project,
        Endpoint = new Endpoint { Resolution = "unresolved" },
        Http = new HttpDetail { Library = "IHttpClientFactory", ClientName = clientName },
        LinuxCompatibility = new LinuxCompatibility { Verdict = "unknown" },
        Confidence = 1,
        CallSites = [CallSiteAt("src/Api/Registration.cs", 1)],
    };

    private static CallSite CallSiteAt(string file, int line) => new() { FilePath = file, LineStart = line, LineEnd = line };

    private static EntryPointBackend Reach(string member, params Invocation[] invocations)
    {
        var source = ProjectSource.FromText(Project, new Dictionary<string, string> { [File] = Code });
        var entry = new InboundEntryPoint("ep", Project, "http_action", "AccountsController", member, File, 1);
        return BackendReach.Build([source], invocations, [entry])[Project].Single();
    }

    [Fact]
    public void A_repository_over_a_context_reaches_the_database_the_context_is_registered_with_through_a_helper_and_a_constant()
    {
        var reach = Reach("Get", Database("db-accounts", "AccountsDatabase"), Database("db-other", "OtherDatabase"));

        // Both contexts are used in GetById, each reaching its own database: the connection name is what ties them.
        var accounts = Assert.Single(reach.Calls, c => c.InvocationId == "db-accounts");
        Assert.Equal(["Get", "AccountService.GetAccount", "AccountRepository.GetById"], accounts.Via);
        Assert.Equal("AccountsDatabase: Accounts", accounts.Operation);
        var other = Assert.Single(reach.Calls, c => c.InvocationId == "db-other");
        Assert.Equal("OtherDatabase: Things", other.Operation);
        Assert.Equal(BackendReach.Yes, reach.Status);
    }

    [Fact]
    public void A_context_whose_registration_names_no_known_database_reaches_none()
    {
        var reach = Reach("Get", Database("db-accounts", "AccountsDatabase"));

        Assert.DoesNotContain(reach.Calls, c => c.InvocationId == "db-other");
        Assert.Single(reach.Calls, c => c.InvocationId == "db-accounts");
    }

    [Fact]
    public void A_call_through_an_http_helper_by_a_constant_name_reaches_the_one_unnamed_registration_of_its_project()
    {
        var reach = Reach("Get", Http("http-registration", null), Http("http-tests", null, "tests/Api.Tests/Api.Tests.csproj"));

        var call = Assert.Single(reach.Calls, c => c.Mechanism == Mechanisms.HttpClient);
        Assert.Equal("http-registration", call.InvocationId);
        Assert.Equal(["Get", "AccountService.GetAccount", "VerificationClient.Verify"], call.Via);
        Assert.Equal("POST v1/verifications (VerificationApi)", call.Operation);
    }

    [Fact]
    public void A_client_factory_request_chained_on_CreateClient_names_its_verb_and_path()
    {
        var reach = Reach("Notify", Http("http-registration", null));

        var call = Assert.Single(reach.Calls);
        Assert.Equal(["Notify", "AccountService.Welcome", "NotificationClient.Send"], call.Via);
        Assert.Equal("POST v1/notifications (NotificationApi)", call.Operation);
    }

    [Fact]
    public void A_request_made_on_the_variable_CreateClient_is_assigned_to_names_its_verb_and_path()
    {
        var source = ProjectSource.FromText(Project, new Dictionary<string, string>
        {
            [File] = """
                public class Handler
                {
                    private readonly IHttpClientFactory _factory;
                    public void Run(object request)
                    {
                        var client = _factory.CreateClient("NotificationApi");
                        client.PostAsJsonAsync("v1/notifications", request);
                    }
                }
                """,
        });
        var entry = new InboundEntryPoint("ep", Project, "http_action", "Handler", "Run", File, 1);
        var reach = BackendReach.Build([source], [Http("http-registration", null)], [entry])[Project].Single();

        Assert.Equal("POST v1/notifications (NotificationApi)", Assert.Single(reach.Calls).Operation);
    }

    [Fact]
    public void CreateClient_on_a_WCF_helper_is_not_an_http_call()
    {
        var source = ProjectSource.FromText(Project, new Dictionary<string, string>
        {
            [File] = """
                public class Handler
                {
                    private readonly IWCFClientHelper _wcf;
                    public void Run() { var client = _wcf.CreateClient("CreditCheck"); }
                }
                """,
        });
        var entry = new InboundEntryPoint("ep", Project, "http_action", "Handler", "Run", File, 1);
        var reach = BackendReach.Build([source], [Http("http-registration", null)], [entry])[Project].Single();

        Assert.Empty(reach.Calls);
    }

    [Fact]
    public void A_registration_carrying_the_clients_name_wins_over_the_unnamed_one()
    {
        var reach = Reach("Notify", Http("http-named", "NotificationApi"), Http("http-registration", null));

        Assert.Equal("http-named", Assert.Single(reach.Calls).InvocationId);
    }

    [Fact]
    public void Two_unnamed_registrations_in_the_project_are_not_guessed_between()
    {
        var reach = Reach("Notify", Http("http-a", null), Http("http-b", null));

        Assert.Empty(reach.Calls);
        Assert.Equal(BackendReach.No, reach.Status);
    }
}
