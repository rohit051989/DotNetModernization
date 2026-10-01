using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using static Fingerprinting.Outbound.DetectionSupport;

namespace Fingerprinting.Outbound;

/// <summary>
/// <c>message_producer</c> and <c>message_consumer</c> — Kafka
/// (<c>new ProducerBuilder&lt;K, V&gt;(config)</c>, <c>ConsumerBuilder</c>, the
/// config's <c>BootstrapServers</c>, the topics produced to or subscribed to)
/// and MSMQ (<c>new MessageQueue(path)</c> with <c>Send</c> / <c>Receive</c>).
/// Kafka authentication is the SASL mechanism where code or configuration
/// states it (<see cref="Sasl"/>), <c>unknown</c> only where nothing does.
/// </summary>
public static class MessagingDetector
{
    public static IEnumerable<Detected> Detect(DetectionContext context)
    {
        foreach (var file in context.SourceFiles)
        {
            foreach (var creation in file.Root.DescendantNodes().OfType<ObjectCreationExpressionSyntax>())
            {
                var type = SyntaxHelpers.RightmostTypeName(creation.Type);
                switch (type)
                {
                    case "ProducerBuilder" or "ConsumerBuilder":
                        yield return Kafka(context, file, creation, type == "ProducerBuilder" ? Mechanisms.MessageProducer : Mechanisms.MessageConsumer);
                        break;
                    case "MessageQueue" when creation.ArgumentList?.Arguments.FirstOrDefault()?.Expression is { } path:
                        foreach (var detected in Msmq(context, file, creation, path))
                        {
                            yield return detected;
                        }

                        break;
                }
            }
        }
    }

    private static Detected Kafka(DetectionContext context, ParsedFile file, ObjectCreationExpressionSyntax creation, string mechanism)
    {
        var scope = CallSiteEvaluator.Scope(creation);
        var config = ConfigObject(creation, scope);
        var servers = BootstrapServers(creation, scope, config);
        var (endpoint, bindings, value) = servers is null
            ? (new Endpoint { Scheme = "kafka", Resolution = Resolutions.Unresolved, Placeholder = "BootstrapServers not found" }, [], ResolvedValue.Hole("BootstrapServers"))
            : Evaluate(context.Resolver, r => r.Resolve(servers, CallSiteEvaluator.Empty), BrokerEndpoint);

        // Topics: Produce/ProduceAsync/Subscribe in the enclosing class.
        var type = creation.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault() ?? (SyntaxNode)file.Root;
        var method = mechanism == Mechanisms.MessageProducer ? new[] { "Produce", "ProduceAsync" } : ["Subscribe"];
        var topics = type.DescendantNodes().OfType<InvocationExpressionSyntax>()
            .Where(i => method.Contains(SyntaxHelpers.InvokedName(i)))
            .Select(i => i.ArgumentList.Arguments.FirstOrDefault()?.Expression)
            .OfType<ExpressionSyntax>()
            .Select(t => context.Resolver.Resolve(t, CallSiteEvaluator.Empty).TextValue)
            .OfType<string>()
            .Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToList();

        var sasl = Sasl.Read(context, file, scope, config);
        bindings = Sasl.Bind(context, sasl, endpoint, bindings);

        var reasons = new List<string>();
        if (sasl.Source is not null)
        {
            reasons.Add($"SASL mechanism from {sasl.Source}");
        }

        var brokers = value.TextValue?.Split(',', StringSplitOptions.RemoveEmptyEntries).Length ?? 0;
        if (brokers > 1)
        {
            reasons.Add($"{brokers} bootstrap servers; the first is the endpoint");
        }

        return new Detected(new Invocation
        {
            InvocationId = "",
            Mechanism = mechanism,
            ProjectPath = "",
            Endpoint = endpoint,
            EnvironmentBindings = bindings,
            AuthDeclared = sasl.Mechanism is "unknown" ? AuthDeclared.NotAssessed : sasl.Mechanism is "none" ? AuthDeclared.NoneDeclared : AuthDeclared.Declared,
            Messaging = new MessagingDetail { Transport = "kafka", Topics = topics, Authentication = sasl.Mechanism, AuthenticationSource = sasl.Source },
            CallSites = [CallSiteOf(file, creation)],
            LinuxCompatibility = Pending,
            Confidence = endpoint.Resolution == Resolutions.Resolved ? 0.9 : 0.8,
            ConfidenceReasons = reasons,
        }, string.Join(",", topics));
    }

    private static Endpoint BrokerEndpoint(ResolvedValue value) => value.TextValue is { } text
        ? Endpoints.FromHostPort("kafka", text, value.Parts.OfType<TextPart>().FirstOrDefault()?.Source)
        : new Endpoint { Scheme = "kafka", Resolution = Resolutions.Unresolved, Placeholder = value.Placeholder ?? Label(value) };

    /// <summary>The builder's config object: <c>new ProducerConfig { … }</c>
    /// passed in directly or through a local; null when it comes from
    /// somewhere this step cannot see.</summary>
    public static (string? Variable, ObjectCreationExpressionSyntax? Creation, ExpressionSyntax? Initializer) ConfigObject(
        ObjectCreationExpressionSyntax builder, SyntaxNode scope)
    {
        var argument = builder.ArgumentList?.Arguments.FirstOrDefault()?.Expression;
        if (argument is ObjectCreationExpressionSyntax direct)
        {
            return (null, direct, direct);
        }

        if (argument is IdentifierNameSyntax identifier)
        {
            var initializer = scope.DescendantNodes().OfType<VariableDeclaratorSyntax>()
                .LastOrDefault(v => v.Identifier.Text == identifier.Identifier.Text)?.Initializer?.Value;
            return (identifier.Identifier.Text, initializer as ObjectCreationExpressionSyntax, initializer);
        }

        return (null, null, argument);
    }

    /// <summary><c>new ProducerConfig { BootstrapServers = … }</c> passed in
    /// (directly or through a local), or <c>config.BootstrapServers = …</c>.</summary>
    private static ExpressionSyntax? BootstrapServers(
        ObjectCreationExpressionSyntax builder, SyntaxNode scope, (string? Variable, ObjectCreationExpressionSyntax? Creation, ExpressionSyntax? Initializer) config)
    {
        if (config.Variable is { } variable)
        {
            var assigned = scope.DescendantNodes().OfType<AssignmentExpressionSyntax>()
                .FirstOrDefault(a => a.Left.ToString().Replace(" ", "") == $"{variable}.BootstrapServers");
            if (assigned is not null)
            {
                return assigned.Right;
            }
        }

        return config.Creation?.Initializer?.Expressions.OfType<AssignmentExpressionSyntax>()
            .FirstOrDefault(a => a.Left is IdentifierNameSyntax { Identifier.Text: "BootstrapServers" })?.Right;
    }

    private static IEnumerable<Detected> Msmq(DetectionContext context, ParsedFile file, ObjectCreationExpressionSyntax creation, ExpressionSyntax path)
    {
        var (endpoint, bindings, _) = Evaluate(context.Resolver, r => r.Resolve(path, CallSiteEvaluator.Empty),
            value => value.TextValue is { } text
                ? Endpoints.FromMsmqPath(text) with { Source = value.Parts.OfType<TextPart>().FirstOrDefault()?.Source }
                : new Endpoint { Scheme = "msmq", Resolution = Resolutions.Unresolved, Placeholder = value.Placeholder ?? Label(value) });

        var variable = creation.Ancestors().OfType<VariableDeclaratorSyntax>().FirstOrDefault()?.Identifier.Text;
        var scope = creation.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault() ?? (SyntaxNode)file.Root;
        var calls = scope.DescendantNodes().OfType<InvocationExpressionSyntax>()
            .Where(i => variable is null || SyntaxHelpers.Receiver(i)?.ToString() == variable)
            .Select(SyntaxHelpers.InvokedName).ToHashSet();
        var sends = calls.Contains("Send");
        var receives = calls.Overlaps(["Receive", "BeginReceive", "Peek", "BeginPeek", "ReceiveById"]);

        var mechanisms = new List<string>();
        if (sends || !receives)
        {
            mechanisms.Add(Mechanisms.MessageProducer);
        }

        if (receives)
        {
            mechanisms.Add(Mechanisms.MessageConsumer);
        }

        foreach (var mechanism in mechanisms)
        {
            yield return new Detected(new Invocation
            {
                InvocationId = "",
                Mechanism = mechanism,
                ProjectPath = "",
                Endpoint = endpoint,
                EnvironmentBindings = bindings,
                AuthDeclared = AuthDeclared.NotAssessed,
                Messaging = new MessagingDetail { Transport = "msmq", Authentication = "windows" },
                CallSites = [CallSiteOf(file, creation)],
                LinuxCompatibility = Pending,
                Confidence = sends || receives ? 1.0 : 0.8,
                ConfidenceReasons = sends || receives ? [] : ["no Send or Receive found on the queue; taken as a producer"],
            }, "");
        }
    }
}

/// <summary><c>file_share</c> — step 3's <c>UNC_PATH_LITERAL</c> signals,
/// reduced to <c>\\server\share</c>: deeper path segments are left out, since
/// they can name people and the register needs only the share.</summary>
public static class FileShareDetector
{
    public static IEnumerable<Detected> Detect(DetectionContext context)
    {
        var shares = context.UncLiterals
            .Select(u => (Literal: u, Share: Endpoints.FromUnc(u.MatchedValue)))
            .Where(x => x.Share is not null)
            .GroupBy(x => x.Share!.Value.Share, StringComparer.OrdinalIgnoreCase)
            .OrderBy(g => g.Key, StringComparer.OrdinalIgnoreCase);

        foreach (var group in shares)
        {
            var first = group.First().Share!.Value;
            var callSites = group
                .Select(x => new CallSite { FilePath = x.Literal.FilePath, LineStart = x.Literal.LineStart ?? 0, LineEnd = x.Literal.LineEnd ?? x.Literal.LineStart ?? 0 })
                .DistinctBy(c => (c.FilePath, c.LineStart))
                .OrderBy(c => c.FilePath, StringComparer.Ordinal).ThenBy(c => c.LineStart)
                .ToList();
            yield return new Detected(new Invocation
            {
                InvocationId = "",
                Mechanism = Mechanisms.FileShare,
                ProjectPath = "",
                Endpoint = first.Endpoint,
                AuthDeclared = AuthDeclared.NotAssessed,
                FileShare = new FileShareDetail { Share = first.Share },
                CallSites = callSites,
                LinuxCompatibility = Pending,
                Confidence = 0.9,
                ConfidenceReasons = ["from step 3's UNC_PATH_LITERAL: a literal, which may not be the path used at run time"],
            }, first.Share.ToLowerInvariant());
        }
    }
}

/// <summary><c>smtp</c> — <c>new SmtpClient(host, port)</c>, its <c>Host</c> /
/// <c>Port</c> set after, MailKit's <c>Connect(host, port)</c>, and
/// <c>&lt;system.net&gt;&lt;mailSettings&gt;</c>, which a hostless <c>new SmtpClient()</c> reads.</summary>
public static class SmtpDetector
{
    public static IEnumerable<Detected> Detect(DetectionContext context)
    {
        var mail = context.Config.MailSettings
            .Where(m => context.Config.Governs(context.Project.ProjectDirectory, m.Directory))
            .OrderBy(m => m.Environment == "default" ? 0 : 1).ThenBy(m => m.File, StringComparer.Ordinal)
            .ToList();
        var usedMailSettings = false;

        foreach (var file in context.SourceFiles)
        {
            foreach (var node in file.Root.DescendantNodes())
            {
                ExpressionSyntax? host = null, port = null;
                SyntaxNode? scopeNode = null;
                switch (node)
                {
                    case ObjectCreationExpressionSyntax creation when SyntaxHelpers.RightmostTypeName(creation.Type) == "SmtpClient":
                        var arguments = creation.ArgumentList?.Arguments ?? default;
                        host = arguments.FirstOrDefault()?.Expression ?? Assigned(creation, "Host");
                        port = arguments.ElementAtOrDefault(1)?.Expression ?? Assigned(creation, "Port");
                        scopeNode = creation;
                        if (host is null && IsMailKit(file))
                        {
                            continue;   // MailKit: the endpoint is at Connect(...)
                        }

                        break;
                    case InvocationExpressionSyntax invocation when SyntaxHelpers.InvokedName(invocation) is "Connect" or "ConnectAsync"
                                                                    && IsMailKit(file)
                                                                    && SyntaxHelpers.Receiver(invocation) is { } receiver
                                                                    && ReceiverType(receiver) == "SmtpClient":
                        host = invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression;
                        port = invocation.ArgumentList.Arguments.ElementAtOrDefault(1)?.Expression;
                        scopeNode = invocation;
                        break;
                    default:
                        continue;
                }

                var credentials = Credentials(file, CallSiteEvaluator.Scope(scopeNode));
                Endpoint endpoint;
                IReadOnlyList<EnvironmentBinding> bindings = [];
                var reasons = new List<string>();
                if (host is not null)
                {
                    (endpoint, bindings, _) = Evaluate(context.Resolver, r => r.Resolve(host, CallSiteEvaluator.Empty), value => HostEndpoint(value));
                    if (port is not null && context.Resolver.Resolve(port, CallSiteEvaluator.Empty).TextValue is { } portText && int.TryParse(portText, out var number))
                    {
                        endpoint = endpoint with { Port = number };
                    }
                }
                else if (mail.Count > 0)
                {
                    usedMailSettings = true;
                    (endpoint, bindings) = FromMailSettings(mail);
                    credentials = [.. credentials, .. MailCredentials(mail)];
                    reasons.Add("host from <system.net><mailSettings>");
                }
                else
                {
                    endpoint = new Endpoint { Scheme = "smtp", Resolution = Resolutions.Unresolved, Placeholder = "no host in code or mailSettings" };
                }

                yield return Make(endpoint, bindings, credentials, [CallSiteOf(file, scopeNode)], endpoint.Resolution == Resolutions.Resolved ? 1.0 : 0.8, reasons);
            }
        }

        if (!usedMailSettings && mail.Count > 0)
        {
            var (endpoint, bindings) = FromMailSettings(mail);
            yield return Make(endpoint, bindings, MailCredentials(mail), [CallSiteAt(mail[0].File, mail[0].Line)], 0.7,
                ["declared in <system.net><mailSettings>; no SmtpClient found in code"]);
        }
    }

    private static bool IsMailKit(ParsedFile file) =>
        file.Root.Usings.Any(u => u.Name?.ToString().StartsWith("MailKit", StringComparison.Ordinal) == true);

    private static ExpressionSyntax? Assigned(ObjectCreationExpressionSyntax creation, string member)
    {
        var inInitializer = creation.Initializer?.Expressions.OfType<AssignmentExpressionSyntax>()
            .FirstOrDefault(a => a.Left is IdentifierNameSyntax id && id.Identifier.Text == member)?.Right;
        if (inInitializer is not null)
        {
            return inInitializer;
        }

        var variable = creation.Ancestors().OfType<VariableDeclaratorSyntax>().FirstOrDefault()?.Identifier.Text;
        return variable is null
            ? null
            : CallSiteEvaluator.Scope(creation).DescendantNodes().OfType<AssignmentExpressionSyntax>()
                .FirstOrDefault(a => a.Left.ToString().Replace(" ", "") == $"{variable}.{member}")?.Right;
    }

    private static Endpoint HostEndpoint(ResolvedValue value) => value.TextValue is { } text
        ? Endpoints.FromHostPort("smtp", text, value.Parts.OfType<TextPart>().FirstOrDefault()?.Source)
        : new Endpoint { Scheme = "smtp", Resolution = Resolutions.Unresolved, Placeholder = value.Placeholder ?? Label(value) };

    private static (Endpoint, IReadOnlyList<EnvironmentBinding>) FromMailSettings(IReadOnlyList<MailSettingsEntry> mail)
    {
        var primary = mail[0];
        var endpoint = new Endpoint
        {
            Scheme = "smtp",
            Host = primary.Host,
            Port = primary.Port,
            Resolution = primary.Host is null ? Resolutions.Unresolved : Resolutions.Resolved,
            Placeholder = primary.Host is null ? "mailSettings without a host" : null,
            Source = new ConfigSource { SourceFile = primary.File, KeyPath = "system.net/mailSettings/smtp/network" },
        };
        var bindings = mail.Select(m => new EnvironmentBinding
        {
            Environment = m.Environment,
            SourceFile = m.File,
            KeyPath = "system.net/mailSettings/smtp/network",
            Scheme = "smtp",
            Host = m.Host,
            Port = m.Port,
            Resolution = m.Host is null ? Resolutions.Unresolved : Resolutions.Resolved,
        }).ToList();
        return (endpoint, bindings);
    }

    private static IReadOnlyList<CredentialReference> MailCredentials(IReadOnlyList<MailSettingsEntry> mail)
    {
        var credentials = new List<CredentialReference>();
        if (mail.FirstOrDefault(m => m.HasCredentials) is { } withCredentials)
        {
            credentials.Add(new CredentialReference { Kind = "password", KeyPath = "system.net/mailSettings/smtp/network", SourceFile = withCredentials.File });
        }

        if (mail.FirstOrDefault(m => m.DefaultCredentials) is { } defaults)
        {
            credentials.Add(new CredentialReference { Kind = "windows", KeyPath = "system.net/mailSettings/smtp/network@defaultCredentials", SourceFile = defaults.File });
        }

        return credentials;
    }

    private static IReadOnlyList<CredentialReference> Credentials(ParsedFile file, SyntaxNode scope)
    {
        var found = new SortedDictionary<string, CredentialReference>(StringComparer.Ordinal);
        foreach (var node in scope.DescendantNodes())
        {
            var kind = node switch
            {
                AssignmentExpressionSyntax { Left: MemberAccessExpressionSyntax { Name.Identifier.Text: "UseDefaultCredentials" } } a
                    when a.Right.IsKind(SyntaxKind.TrueLiteralExpression) => "windows",
                AssignmentExpressionSyntax { Left: MemberAccessExpressionSyntax { Name.Identifier.Text: "Credentials" } } a =>
                    a.Right.ToString().Contains("Default", StringComparison.Ordinal) ? "windows" : "password",
                InvocationExpressionSyntax i when SyntaxHelpers.InvokedName(i) is "Authenticate" or "AuthenticateAsync" => "password",
                _ => null,
            };
            if (kind is not null && !found.ContainsKey(kind))
            {
                found[kind] = new CredentialReference { Kind = kind, DeclaredAt = CallSiteEvaluator.Where(file, node) };
            }
        }

        return found.Values.ToList();
    }

    private static Detected Make(
        Endpoint endpoint, IReadOnlyList<EnvironmentBinding> bindings, IReadOnlyList<CredentialReference> credentials, IReadOnlyList<CallSite> callSites,
        double confidence, IReadOnlyList<string> reasons) =>
        new(new Invocation
        {
            InvocationId = "",
            Mechanism = Mechanisms.Smtp,
            ProjectPath = "",
            Endpoint = endpoint,
            EnvironmentBindings = bindings,
            AuthDeclared = credentials.Count > 0 ? AuthDeclared.Declared : AuthDeclared.NotAssessed,
            Credentials = credentials.DistinctBy(c => c.Kind).OrderBy(c => c.Kind, StringComparer.Ordinal).ToList(),
            Smtp = new SmtpDetail { UsesDefaultCredentials = credentials.Any(c => c.Kind == "windows") },
            CallSites = callSites,
            LinuxCompatibility = Pending,
            Confidence = confidence,
            ConfidenceReasons = reasons,
        }, "");
}

/// <summary><c>ldap</c> — <c>DirectoryEntry</c> / <c>DirectorySearcher</c>
/// (System.DirectoryServices, Windows ADSI), <c>PrincipalContext</c>
/// (System.DirectoryServices.AccountManagement), <c>LdapConnection</c>
/// (System.DirectoryServices.Protocols, or Novell's portable client).</summary>
public static class LdapDetector
{
    public const string DirectoryServices = "System.DirectoryServices";
    public const string AccountManagement = "System.DirectoryServices.AccountManagement";
    public const string Protocols = "System.DirectoryServices.Protocols";
    public const string Novell = "Novell.Directory.Ldap";

    public static IEnumerable<Detected> Detect(DetectionContext context)
    {
        foreach (var file in context.SourceFiles)
        {
            var usings = file.Root.DescendantNodes().OfType<UsingDirectiveSyntax>().Select(u => u.Name?.ToString() ?? "").ToHashSet(StringComparer.Ordinal);
            foreach (var creation in file.Root.DescendantNodes().OfType<ObjectCreationExpressionSyntax>())
            {
                var type = SyntaxHelpers.RightmostTypeName(creation.Type);
                var written = creation.Type.ToString();
                var api = type switch
                {
                    "DirectoryEntry" => DirectoryServices,
                    // A searcher over an entry is recorded at the entry.
                    "DirectorySearcher" when creation.ArgumentList?.Arguments.Count is null or 0 => DirectoryServices,
                    "PrincipalContext" => AccountManagement,
                    "LdapConnection" when usings.Contains(Novell) || written.StartsWith("Novell", StringComparison.Ordinal) => Novell,
                    "LdapConnection" => Protocols,
                    _ => null,
                };
                if (api is null)
                {
                    continue;
                }

                var arguments = creation.ArgumentList?.Arguments ?? default;
                var target = api switch
                {
                    DirectoryServices => arguments.FirstOrDefault()?.Expression,
                    AccountManagement => arguments.ElementAtOrDefault(1)?.Expression,
                    Protocols => arguments.FirstOrDefault()?.Expression is ObjectCreationExpressionSyntax { ArgumentList.Arguments: [var server, ..] } ? server.Expression : arguments.FirstOrDefault()?.Expression,
                    _ => null,
                };
                var machine = api == AccountManagement && arguments.FirstOrDefault()?.Expression.ToString().EndsWith("Machine", StringComparison.Ordinal) == true;

                Endpoint endpoint;
                IReadOnlyList<EnvironmentBinding> bindings = [];
                if (machine)
                {
                    endpoint = new Endpoint { Scheme = "ldap", Host = "localhost", Resolution = Resolutions.Resolved };
                }
                else if (target is null)
                {
                    endpoint = new Endpoint { Scheme = "ldap", Resolution = Resolutions.Unresolved, Placeholder = "current domain" };
                }
                else
                {
                    (endpoint, bindings, _) = Evaluate(context.Resolver, r => r.Resolve(target, CallSiteEvaluator.Empty), value => value.TextValue switch
                    {
                        { } text when text.Contains("://", StringComparison.Ordinal) => Endpoints.FromLdapPath(text),
                        { } text => Endpoints.FromHostPort("ldap", text),
                        _ => new Endpoint { Scheme = "ldap", Resolution = Resolutions.Unresolved, Placeholder = value.Placeholder ?? Label(value) },
                    });
                }

                yield return new Detected(new Invocation
                {
                    InvocationId = "",
                    Mechanism = Mechanisms.Ldap,
                    ProjectPath = "",
                    Endpoint = endpoint,
                    EnvironmentBindings = bindings,
                    AuthDeclared = AuthDeclared.NotAssessed,
                    Ldap = new LdapDetail { Api = api },
                    CallSites = [CallSiteOf(file, creation)],
                    LinuxCompatibility = Pending,
                    Confidence = 1.0,
                }, api);
            }
        }
    }
}
