using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using static Fingerprinting.Outbound.DetectionSupport;

namespace Fingerprinting.Outbound;

/// <summary>A place code names a connection string: <c>GetConnectionString("X")</c>,
/// <c>ConnectionStrings["X"]</c>, <c>configuration["ConnectionStrings:X"]</c>, an
/// EF6 <c>: base("name=X")</c>.</summary>
/// <param name="Provider">The provider of the database API the name is
/// handed to (<c>UseSqlServer</c> → sqlserver), when that is visible.</param>
public sealed record ConnectionReference(
    ProjectSource Project, ParsedFile File, SyntaxNode Node, string Name, IReadOnlyList<CredentialReference> Credentials, string? Provider);

/// <summary>
/// <c>database</c> — Part C1, C4, C5. Anchored on configuration: each named
/// connection string an application's config declares is one invocation,
/// with a binding per environment file (web.config and its Release
/// transform, appsettings.json and appsettings.Docker.json). The code that
/// names it — anywhere in the repository, since a data library is
/// configured by its host — supplies the call sites. A connection a
/// database API is given from somewhere else (an environment variable, a
/// literal, a key named at run time) is recorded from the code. Only the
/// name, provider, server host, port and kind of authentication are kept.
/// </summary>
public static class DatabaseDetector
{
    private static readonly IReadOnlyDictionary<string, string> ProviderByApi = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["UseSqlServer"] = "sqlserver", ["UseAzureSql"] = "sqlserver", ["SqlConnection"] = "sqlserver", ["SqlCeConnection"] = "sqlserver",
        ["UseNpgsql"] = "postgresql", ["NpgsqlConnection"] = "postgresql",
        ["UseMySql"] = "mysql", ["UseMySQL"] = "mysql", ["MySqlConnection"] = "mysql",
        ["UseSqlite"] = "sqlite", ["SqliteConnection"] = "sqlite", ["SQLiteConnection"] = "sqlite",
        ["UseOracle"] = "oracle", ["OracleConnection"] = "oracle",
        ["OleDbConnection"] = "oledb", ["OdbcConnection"] = "odbc",
    };

    private static readonly HashSet<string> ContextBases = new(StringComparer.Ordinal)
    {
        "DbContext", "IdentityDbContext", "ObjectContext",
    };

    // ---------- the repository-wide reference index ----------

    public static ILookup<string, ConnectionReference> IndexReferences(IEnumerable<DetectionContext> contexts)
    {
        var references = new List<ConnectionReference>();
        foreach (var context in contexts)
        {
            foreach (var file in context.SourceFiles)
            {
                foreach (var node in file.Root.DescendantNodes())
                {
                    var name = node switch
                    {
                        InvocationExpressionSyntax invocation when SyntaxHelpers.InvokedName(invocation) == "GetConnectionString" =>
                            context.Symbols.Constant(invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression),
                        ElementAccessExpressionSyntax element when element.Expression.ToString().EndsWith("ConnectionStrings", StringComparison.Ordinal) =>
                            context.Symbols.Constant(element.ArgumentList.Arguments.FirstOrDefault()?.Expression),
                        ElementAccessExpressionSyntax element when context.Symbols.Constant(element.ArgumentList.Arguments.FirstOrDefault()?.Expression) is { } key
                                                                   && key.StartsWith("ConnectionStrings:", StringComparison.OrdinalIgnoreCase) =>
                            key["ConnectionStrings:".Length..],
                        ConstructorInitializerSyntax { RawKind: (int)SyntaxKind.BaseConstructorInitializer } initializer
                            when IsContext(initializer) && context.Symbols.Constant(initializer.ArgumentList.Arguments.FirstOrDefault()?.Expression) is { } argument =>
                            argument.StartsWith("name=", StringComparison.OrdinalIgnoreCase) ? argument["name=".Length..].Trim() : argument,
                        _ => null,
                    };
                    if (name is not null && name.Length > 0)
                    {
                        references.Add(new ConnectionReference(context.Project, file, node, name, TokenCredentials(file, node), ApiProvider(node)));
                    }
                }
            }
        }

        return references.ToLookup(r => r.Name, StringComparer.OrdinalIgnoreCase);
    }

    /// <summary>The database API a reference is passed to: directly
    /// (<c>UseSqlServer(c.GetConnectionString("X"))</c>), through a local
    /// (<c>var cs = …; UseSqlServer(cs)</c>), or as a DbContext base
    /// argument (EF6, SQL Server unless the config says otherwise).</summary>
    private static string? ApiProvider(SyntaxNode node)
    {
        foreach (var ancestor in node.Ancestors())
        {
            switch (ancestor)
            {
                case InvocationExpressionSyntax invocation when SyntaxHelpers.InvokedName(invocation) is { } name && ProviderByApi.TryGetValue(name, out var provider):
                    return provider;
                case ObjectCreationExpressionSyntax creation when SyntaxHelpers.RightmostTypeName(creation.Type) is { } type && ProviderByApi.TryGetValue(type, out var provider):
                    return provider;
                case VariableDeclaratorSyntax local:
                    var use = CallSiteEvaluator.Scope(local).DescendantNodes().OfType<IdentifierNameSyntax>()
                        .Where(i => i.Identifier.Text == local.Identifier.Text && i.SpanStart > local.Span.End)
                        .Select(i => i.Ancestors().OfType<InvocationExpressionSyntax>()
                            .Select(SyntaxHelpers.InvokedName).FirstOrDefault(n => n is not null && ProviderByApi.ContainsKey(n)))
                        .FirstOrDefault(n => n is not null);
                    return use is null ? null : ProviderByApi[use];
                case StatementSyntax or MemberDeclarationSyntax:
                    return null;
            }
        }

        return null;
    }

    private static bool IsContext(ConstructorInitializerSyntax initializer) =>
        initializer.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault()?.BaseList?.Types
            .Any(b => SyntaxHelpers.RightmostTypeName(b.Type) is { } name && ContextBases.Contains(name)) == true;

    /// <summary><c>new SqlConnection { AccessToken = …, ConnectionString = … }</c>:
    /// an Azure AD token, recorded as configured.</summary>
    private static IReadOnlyList<CredentialReference> TokenCredentials(ParsedFile file, SyntaxNode node)
    {
        var initializer = node.Ancestors().OfType<InitializerExpressionSyntax>().FirstOrDefault();
        var token = initializer?.Expressions.OfType<AssignmentExpressionSyntax>()
            .FirstOrDefault(a => a.Left is IdentifierNameSyntax { Identifier.Text: "AccessToken" });
        return token is null ? [] : [new CredentialReference { Kind = "token", DeclaredAt = CallSiteEvaluator.Where(file, token) }];
    }

    // ---------- detection ----------

    public static IEnumerable<Detected> Detect(DetectionContext context, ILookup<string, ConnectionReference> references)
    {
        foreach (var detected in FromConfiguration(context, references))
        {
            yield return detected;
        }

        foreach (var detected in FromCode(context))
        {
            yield return detected;
        }
    }

    private static IEnumerable<Detected> FromConfiguration(DetectionContext context, ILookup<string, ConnectionReference> references)
    {
        var groups = context.Config.Entries
            .Where(e => e.Facts is not null && context.Config.Governs(context.Project.ProjectDirectory, e.Directory))
            .GroupBy(e => e.KeyPath, StringComparer.OrdinalIgnoreCase)
            .OrderBy(g => g.Key, StringComparer.OrdinalIgnoreCase);

        foreach (var group in groups)
        {
            var entries = group
                .OrderBy(e => e.Environment == "default" ? 0 : 1).ThenBy(e => e.Environment, StringComparer.Ordinal).ThenBy(e => e.File, StringComparer.Ordinal)
                .ToList();
            var primary = entries[0];
            var name = primary.KeyPath.StartsWith("ConnectionStrings:", StringComparison.OrdinalIgnoreCase)
                ? primary.KeyPath["ConnectionStrings:".Length..]
                : primary.KeyPath;

            // A library names the connection; its host configures it.
            var linked = references[name]
                .Where(r => r.Project == context.Project || !DefinesConnection(context, r.Project, name))
                .OrderBy(r => r.File.RelativePath, StringComparer.Ordinal).ThenBy(r => r.Node.SpanStart)
                .ToList();
            var callSites = linked.Count > 0
                ? linked.Select(r => CallSiteOf(r.File, r.Node)).ToList()
                : [CallSiteAt(primary.File, primary.Line)];

            var bindings = entries.Select(e => new EnvironmentBinding
            {
                Environment = e.Environment,
                SourceFile = e.File,
                KeyPath = e.KeyPath,
                Scheme = e.Facts!.Provider,
                Host = e.Facts.Host,
                Port = int.TryParse(e.Facts.Port, out var port) ? port : null,
                Resolution = e.Facts.Host is null ? Resolutions.Partial : Resolutions.Resolved,
                Authentication = Authentication(e.Facts),
            }).ToList();

            var facts = primary.Facts!;
            var reasons = new List<string>();
            var confidence = 1.0;
            if (linked.Count == 0)
            {
                confidence = 0.8;
                reasons.Add("declared in configuration; no code reference to it found");
            }

            if (entries.Select(e => e.ConfigBuilders).FirstOrDefault(b => b is not null) is { } builders)
            {
                confidence = Math.Min(confidence, 0.8);
                reasons.Add($"connectionStrings uses configuration builders ({builders}): the value may be replaced at run time");
            }

            var credentials = new List<CredentialReference>();
            if (entries.FirstOrDefault(e => e.Facts!.Authentication == ConnectionAuthentication.Credentials) is { } withCredentials)
            {
                credentials.Add(new CredentialReference { Kind = "password", KeyPath = withCredentials.KeyPath, SourceFile = withCredentials.File });
            }

            if (entries.FirstOrDefault(e => e.Facts!.Authentication == ConnectionAuthentication.Integrated) is { } integrated)
            {
                credentials.Add(new CredentialReference { Kind = "windows", KeyPath = integrated.KeyPath, SourceFile = integrated.File });
            }

            credentials.AddRange(linked.SelectMany(r => r.Credentials).GroupBy(c => c.Kind).Select(g => g.First()));

            // The connection string's own provider, else the API it is handed to.
            var provider = facts.Provider ?? entries.Select(e => e.Facts!.Provider).FirstOrDefault(p => p is not null)
                           ?? linked.Select(r => r.Provider).FirstOrDefault(p => p is not null);
            if (facts.Provider is null && provider is not null)
            {
                bindings = bindings.Select(b => b with { Scheme = b.Scheme ?? provider }).ToList();
            }

            var endpoint = new Endpoint
            {
                Scheme = provider,
                Host = facts.Host,
                Port = int.TryParse(facts.Port, out var primaryPort) ? primaryPort : null,
                Resolution = facts.Host is null ? Resolutions.Partial : Resolutions.Resolved,
                Source = new ConfigSource { SourceFile = primary.File, KeyPath = primary.KeyPath },
            };

            if (facts.Provider == "redis")
            {
                yield return CacheDetector.Make(endpoint with { Scheme = "redis" }, bindings, credentials, callSites, "redis", confidence, reasons, name);
                continue;
            }

            yield return new Detected(new Invocation
            {
                InvocationId = "",
                Mechanism = Mechanisms.Database,
                ProjectPath = "",
                Endpoint = endpoint,
                EnvironmentBindings = bindings,
                AuthDeclared = credentials.Count > 0 ? AuthDeclared.Declared : AuthDeclared.NotAssessed,
                Credentials = credentials.OrderBy(c => c.Kind, StringComparer.Ordinal).ToList(),
                Database = new DatabaseDetail
                {
                    Name = name,
                    Provider = provider,
                    Authentication = Authentication(facts),
                    LocalDb = facts.LocalDb,
                },
                CallSites = callSites,
                LinuxCompatibility = Pending,
                Confidence = confidence,
                ConfidenceReasons = reasons,
            }, name);
        }
    }

    private static bool DefinesConnection(DetectionContext context, ProjectSource project, string name) =>
        context.Config.Entries.Any(e => e.Facts is not null && context.Config.Governs(project.ProjectDirectory, e.Directory)
                                        && (e.KeyPath.Equals($"ConnectionStrings:{name}", StringComparison.OrdinalIgnoreCase)
                                            || e.KeyPath.Equals(name, StringComparison.OrdinalIgnoreCase)));

    private static bool DefinedAnywhere(DetectionContext context, ConfigKey key) =>
        context.Config.Entries.Any(e => e.Facts is not null && e.KeyPath.Equals(key.KeyPath, StringComparison.OrdinalIgnoreCase));

    /// <summary>A database API given a connection that is not a configured
    /// connection string: an environment variable, a literal, a key named
    /// at run time.</summary>
    private static IEnumerable<Detected> FromCode(DetectionContext context)
    {
        foreach (var file in context.SourceFiles)
        {
            foreach (var node in file.Root.DescendantNodes())
            {
                var (api, argument) = node switch
                {
                    InvocationExpressionSyntax invocation when SyntaxHelpers.InvokedName(invocation) is { } name && ProviderByApi.ContainsKey(name) && name.StartsWith("Use", StringComparison.Ordinal) =>
                        (name, invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression),
                    ObjectCreationExpressionSyntax creation when SyntaxHelpers.RightmostTypeName(creation.Type) is { } type && ProviderByApi.ContainsKey(type) =>
                        (type, creation.ArgumentList?.Arguments.FirstOrDefault()?.Expression
                               ?? creation.Initializer?.Expressions.OfType<AssignmentExpressionSyntax>()
                                   .FirstOrDefault(a => a.Left is IdentifierNameSyntax { Identifier.Text: "ConnectionString" })?.Right),
                    _ => (null, null),
                };
                if (api is null || argument is null || argument is LambdaExpressionSyntax)
                {
                    continue;
                }

                var value = context.Resolver.Resolve(argument, CallSiteEvaluator.Empty);
                if (value.Facts is not null || (value.WholeConfig is { } key && DefinedAnywhere(context, key)))
                {
                    continue;   // a configured connection string: recorded from configuration
                }

                // A connection string passed through a parameter or member
                // this step cannot follow is recorded where it is configured,
                // if anywhere; a runtime hole alone is not a new dependency.
                if (value.Parts is [HolePart { Placeholder: null }])
                {
                    continue;
                }

                var provider = ProviderByApi[api];
                Endpoint endpoint;
                string authentication;
                var localDb = false;
                if (value.TextValue is { } text && Secrets.LooksLikeConnectionString(text))
                {
                    var facts = Secrets.ReadConnectionFacts(text);
                    endpoint = FromFacts(new ResolvedValue([new TextPart("")]) { Facts = facts }) with { Scheme = facts.Provider ?? provider };
                    authentication = Authentication(facts);
                    localDb = facts.LocalDb;
                }
                else
                {
                    endpoint = new Endpoint { Scheme = provider, Resolution = Resolutions.Unresolved, Placeholder = value.Placeholder ?? Label(value) };
                    authentication = "unknown";
                }

                var identity = value.WholeConfig?.KeyPath ?? endpoint.Placeholder ?? "";
                yield return new Detected(new Invocation
                {
                    InvocationId = "",
                    Mechanism = Mechanisms.Database,
                    ProjectPath = "",
                    Endpoint = endpoint,
                    AuthDeclared = authentication == "unknown" ? AuthDeclared.NotAssessed : AuthDeclared.Declared,
                    Database = new DatabaseDetail
                    {
                        Name = value.WholeConfig?.KeyPath is { } path && path.StartsWith("ConnectionStrings:", StringComparison.OrdinalIgnoreCase)
                            ? path["ConnectionStrings:".Length..]
                            : null,
                        Provider = provider,
                        Authentication = authentication,
                        LocalDb = localDb,
                    },
                    CallSites = [CallSiteOf(file, node)],
                    LinuxCompatibility = Pending,
                    Confidence = endpoint.Resolution == Resolutions.Unresolved ? 0.8 : 1.0,
                    ConfidenceReasons = endpoint.Resolution == Resolutions.Unresolved ? ["connection string not in any configuration file"] : ["connection string written in code"],
                }, identity);
            }
        }
    }
}

/// <summary><c>cache</c> — Redis: <c>ConnectionMultiplexer.Connect(…)</c>,
/// <c>AddStackExchangeRedisCache(o =&gt; o.Configuration = …)</c>, and a
/// Redis-shaped connection string in configuration. Host and port only:
/// a Redis configuration string's <c>password=</c> is never read into the result.</summary>
public static class CacheDetector
{
    public static IEnumerable<Detected> Detect(DetectionContext context)
    {
        foreach (var file in context.SourceFiles)
        {
            foreach (var invocation in file.Root.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var name = SyntaxHelpers.InvokedName(invocation);
                ExpressionSyntax? configuration = name switch
                {
                    "Connect" or "ConnectAsync" when SyntaxHelpers.Receiver(invocation)?.ToString() is "ConnectionMultiplexer" or "StackExchange.Redis.ConnectionMultiplexer" =>
                        invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression,
                    "AddStackExchangeRedisCache" or "AddDistributedRedisCache" =>
                        invocation.ArgumentList.Arguments
                            .SelectMany(a => a.Expression.DescendantNodesAndSelf().OfType<AssignmentExpressionSyntax>())
                            .FirstOrDefault(a => a.Left is MemberAccessExpressionSyntax { Name.Identifier.Text: "Configuration" })?.Right,
                    _ => null,
                };
                if (configuration is null)
                {
                    continue;
                }

                var value = context.Resolver.Resolve(configuration, CallSiteEvaluator.Empty);
                if (value.Facts is not null && value.WholeConfig is not null)
                {
                    continue;   // a configured connection string: DatabaseDetector records it as a cache
                }

                var (endpoint, bindings, resolved) = Evaluate(context.Resolver, r => r.Resolve(configuration, CallSiteEvaluator.Empty), RedisEndpoint);
                var credentials = new List<CredentialReference>();
                if (resolved.TextValue is { } text && text.Split(',').Any(o => o.Trim().StartsWith("password=", StringComparison.OrdinalIgnoreCase)))
                {
                    credentials.Add(new CredentialReference { Kind = "password", KeyPath = resolved.WholeConfig?.KeyPath, DeclaredAt = CallSiteEvaluator.Where(file, invocation) });
                }

                yield return Make(endpoint, bindings, credentials, [CallSiteOf(file, invocation)], "redis",
                    endpoint.Resolution == Resolutions.Resolved ? 1.0 : 0.9, endpoint.Resolution == Resolutions.Resolved ? [] : [$"endpoint {endpoint.Resolution}"],
                    resolved.WholeConfig?.KeyPath ?? "");
            }
        }
    }

    private static Endpoint RedisEndpoint(ResolvedValue value) => value switch
    {
        { Facts: { } } => FromFacts(value) with { Scheme = "redis" },
        { TextValue: { } text } => Endpoints.FromHostPort("redis", text, value.Parts.OfType<TextPart>().FirstOrDefault()?.Source),
        _ => new Endpoint { Scheme = "redis", Resolution = Resolutions.Unresolved, Placeholder = value.Placeholder ?? Label(value) },
    };

    public static Detected Make(
        Endpoint endpoint, IReadOnlyList<EnvironmentBinding> bindings, IReadOnlyList<CredentialReference> credentials, IReadOnlyList<CallSite> callSites,
        string provider, double confidence, IReadOnlyList<string> reasons, string identity) =>
        new(new Invocation
        {
            InvocationId = "",
            Mechanism = Mechanisms.Cache,
            ProjectPath = "",
            Endpoint = endpoint,
            EnvironmentBindings = bindings,
            AuthDeclared = credentials.Count > 0 ? AuthDeclared.Declared : AuthDeclared.NotAssessed,
            Credentials = credentials,
            Cache = new ProviderDetail { Provider = provider },
            CallSites = callSites,
            LinuxCompatibility = Pending,
            Confidence = confidence,
            ConfidenceReasons = reasons,
        }, identity);
}

/// <summary><c>secret_store</c> — Azure Key Vault (<c>AddAzureKeyVault(uri, …)</c>,
/// <c>new SecretClient(uri, …)</c>, a .NET Framework Key Vault configuration
/// builder) and HashiCorp Vault (<c>new VaultClientSettings(url, auth)</c>).
/// The credential kind the client authenticates with, never a value.</summary>
public static class SecretStoreDetector
{
    public static IEnumerable<Detected> Detect(DetectionContext context)
    {
        foreach (var file in context.SourceFiles)
        {
            foreach (var node in file.Root.DescendantNodes())
            {
                var (provider, address, credential) = node switch
                {
                    InvocationExpressionSyntax invocation when SyntaxHelpers.InvokedName(invocation) is "AddAzureKeyVault" =>
                        ("azure_key_vault", invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression, invocation.ArgumentList.Arguments.ElementAtOrDefault(1)?.Expression),
                    ObjectCreationExpressionSyntax creation when SyntaxHelpers.RightmostTypeName(creation.Type) is "SecretClient" or "KeyClient" or "CertificateClient" =>
                        ("azure_key_vault", creation.ArgumentList?.Arguments.FirstOrDefault()?.Expression, creation.ArgumentList?.Arguments.ElementAtOrDefault(1)?.Expression),
                    ObjectCreationExpressionSyntax creation when SyntaxHelpers.RightmostTypeName(creation.Type) is "VaultClientSettings" =>
                        ("vault", creation.ArgumentList?.Arguments.FirstOrDefault()?.Expression, creation.ArgumentList?.Arguments.ElementAtOrDefault(1)?.Expression),
                    _ => ((string?)null, (ExpressionSyntax?)null, (ExpressionSyntax?)null),
                };
                if (provider is null || address is null)
                {
                    continue;
                }

                // AddAzureKeyVault(IConfigurationBuilder, …) extension call
                // written as a static — rare; the first argument is then not the vault.
                var (endpoint, bindings, value) = Evaluate(context.Resolver, r => r.Resolve(address, CallSiteEvaluator.Empty), Endpoints.FromValue);
                var credentials = CredentialOf(context, file, credential);
                yield return new Detected(Record(endpoint, bindings, credentials, [CallSiteOf(file, node)], provider,
                    endpoint.Resolution == Resolutions.Resolved ? 1.0 : 0.9, endpoint.Resolution == Resolutions.Resolved ? [] : [$"endpoint {endpoint.Resolution}"]),
                    value.WholeConfig?.KeyPath ?? "");
            }
        }

        foreach (var builder in context.Config.KeyVaultBuilders.Where(b => context.Config.Governs(context.Project.ProjectDirectory, b.Directory)))
        {
            Endpoint endpoint;
            var reasons = new List<string> { $"configuration builder '{builder.Name}' in {builder.File}" };
            if (builder.Uri is { } uri)
            {
                endpoint = Endpoints.FromUrl(uri) ?? new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = Endpoints.Placeholder(uri) ?? "uri" };
            }
            else if (builder.VaultName is { } vault && Endpoints.Placeholder(vault) is null)
            {
                // The builder builds exactly this URI from the vault name.
                endpoint = new Endpoint { Scheme = "https", Host = $"{vault.ToLowerInvariant()}.vault.azure.net", Port = 443, Path = "/", Resolution = Resolutions.Resolved };
                reasons.Add("host is the builder's https://{vaultName}.vault.azure.net");
            }
            else
            {
                endpoint = new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = builder.VaultName is { } v ? Endpoints.Placeholder(v) : "vaultName not set" };
            }

            endpoint = endpoint with { Source = new ConfigSource { SourceFile = builder.File, KeyPath = $"configBuilders/builders/{builder.Name}" } };
            yield return new Detected(Record(endpoint, [], [], [CallSiteAt(builder.File, builder.Line)], "azure_key_vault", 0.9, reasons), builder.Name);
        }
    }

    private static IReadOnlyList<CredentialReference> CredentialOf(DetectionContext context, ParsedFile file, ExpressionSyntax? credential)
    {
        if (credential is null)
        {
            return [];
        }

        // Follow a local to its creation: var credential = new DefaultAzureCredential();
        var written = credential;
        if (credential is IdentifierNameSyntax identifier)
        {
            written = CallSiteEvaluator.Scope(identifier).DescendantNodes().OfType<VariableDeclaratorSyntax>()
                .LastOrDefault(v => v.Identifier.Text == identifier.Identifier.Text && v.SpanStart < identifier.SpanStart)?.Initializer?.Value ?? credential;
        }

        var text = written.ToString();
        var kind = text switch
        {
            _ when text.Contains("ClientSecretCredential", StringComparison.Ordinal) => "client_secret",
            _ when text.Contains("ClientCertificateCredential", StringComparison.Ordinal) || text.Contains("CertAuthMethodInfo", StringComparison.Ordinal) => "certificate",
            _ when text.Contains("Credential", StringComparison.Ordinal) || text.Contains("Token", StringComparison.Ordinal) => "token",
            _ when text.Contains("UserPass", StringComparison.Ordinal) || text.Contains("AppRole", StringComparison.Ordinal) => "password",
            _ => null,
        };
        return kind is null ? [] : [new CredentialReference { Kind = kind, DeclaredAt = CallSiteEvaluator.Where(file, credential) }];
    }

    private static Invocation Record(
        Endpoint endpoint, IReadOnlyList<EnvironmentBinding> bindings, IReadOnlyList<CredentialReference> credentials, IReadOnlyList<CallSite> callSites,
        string provider, double confidence, IReadOnlyList<string> reasons) => new()
    {
        InvocationId = "",
        Mechanism = Mechanisms.SecretStore,
        ProjectPath = "",
        Endpoint = endpoint,
        EnvironmentBindings = bindings,
        AuthDeclared = credentials.Count > 0 ? AuthDeclared.Declared : AuthDeclared.NotAssessed,
        Credentials = credentials,
        SecretStore = new ProviderDetail { Provider = provider },
        CallSites = callSites,
        LinuxCompatibility = Pending,
        Confidence = confidence,
        ConfidenceReasons = reasons,
    };
}
