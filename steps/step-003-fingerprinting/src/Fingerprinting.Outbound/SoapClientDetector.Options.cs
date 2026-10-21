using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Outbound;

/// <summary>
/// 1.6.0: a client built by a custom helper from options-bound configuration —
/// AccountsApi's <c>WCFClientHelper</c>:
/// <code>
/// _wcfClientHelper.CreateClient&lt;ICreditCheckService&gt;(ClientName)
///   → _factories.GetOrAdd(clientName, name =&gt; BuildFactory&lt;TChannel&gt;(name))
///     → _settings.Clients.TryGetValue(clientName, out var client)          Wcf:Clients:CreditCheck
///       _settings.Bindings.TryGetValue(client.BindingName, out var binding)  Wcf:Bindings:{BindingName}
///       new ChannelFactory&lt;TChannel&gt;(WcfBindingFactory.Create(client.BindingName, binding), new EndpointAddress(...client.EndpointAddress))
/// </code>
/// Two additions, both syntactic. Call sites are followed up through the
/// helper's own generic callers (<see cref="Lifted"/>), so each
/// <c>CreateClient&lt;I&gt;(name)</c> is its own client with its contract and
/// name bound. The binding and address are then read from the configuration
/// sections the helper looks up by that name, once per environment
/// (<see cref="FromOptionsClient"/>); the binding type, security mode and
/// credential type are read by key name, because the code maps them through a
/// switch this step does not evaluate.
/// </summary>
public static partial class SoapClientDetector
{
    private const int MaxLift = 3;

    private static readonly string[] BindingTypeKeys = ["BindingType", "Binding", "Type"];
    private static readonly string[] SecurityModeKeys = ["BindingMode", "SecurityMode", "Mode"];
    private static readonly string[] CredentialTypeKeys = ["ClientCredentialType", "CredentialType"];

    // ---------- call sites, followed up through generic callers ----------

    /// <summary>
    /// Call sites of a helper, each replaced by the call sites of the method it
    /// sits in when it only forwards that method's own type or value
    /// parameters — <c>BuildFactory&lt;TChannel&gt;(name)</c> inside
    /// <c>CreateClient&lt;TChannel&gt;(clientName)</c>. A parameter of a lambda
    /// handed to <c>GetOrAdd(key, name =&gt; ...)</c> is the key. A method nobody
    /// calls keeps its own call site.
    /// </summary>
    private static List<(ParsedFile File, InvocationExpressionSyntax Call, CallSiteEvaluator.Env Env, bool Lifted)> Lifted(
        ProjectSource project, IEnumerable<(ParsedFile File, InvocationExpressionSyntax Call, CallSiteEvaluator.Env Env)> sites, int depth = 0,
        CancellationToken cancellation = default)
    {
        var result = new List<(ParsedFile, InvocationExpressionSyntax, CallSiteEvaluator.Env, bool)>();
        foreach (var (file, call, env) in sites)
        {
            cancellation.ThrowIfCancellationRequested();   // the project's time limit, inside the fan-out (release 5)
            if (depth < MaxLift && CallSiteEvaluator.Scope(call) is MethodDeclarationSyntax outer && Forwarded(call, env, outer) is { } inner)
            {
                var outerSites = CallSiteEvaluator.CallSites(project, outer);
                if (outerSites.Count > 0)
                {
                    var composed = outerSites.Select(o => (o.File, o.Call, Compose(inner, o.Env)));
                    result.AddRange(Lifted(project, composed, depth + 1, cancellation).Select(s => s with { Lifted = true }));
                    continue;
                }
            }

            result.Add((file, call, env, depth > 0));
        }

        return result;
    }

    /// <summary><paramref name="env"/> with lambda keys substituted, when it
    /// refers to any type or value parameter of <paramref name="outer"/>; else null.</summary>
    private static CallSiteEvaluator.Env? Forwarded(InvocationExpressionSyntax call, CallSiteEvaluator.Env env, MethodDeclarationSyntax outer)
    {
        var typeParameters = outer.TypeParameterList?.Parameters.Select(p => p.Identifier.Text).ToHashSet(StringComparer.Ordinal) ?? [];
        var parameters = outer.ParameterList.Parameters.Select(p => p.Identifier.Text).ToHashSet(StringComparer.Ordinal);
        var arguments = env.Arguments.ToDictionary(a => a.Key, a => LambdaKey(call, a.Value) ?? a.Value, StringComparer.Ordinal);
        var forwards = env.TypeArguments.Values.Any(typeParameters.Contains)
                       || arguments.Values.Any(a => a is IdentifierNameSyntax id && parameters.Contains(id.Identifier.Text));
        return forwards ? env with { Arguments = arguments } : null;
    }

    /// <summary>For a lambda parameter <c>name</c> in <c>dictionary.GetOrAdd(key, name =&gt; ...)</c>: <c>key</c>.</summary>
    private static ExpressionSyntax? LambdaKey(SyntaxNode site, ExpressionSyntax argument)
    {
        if (argument is not IdentifierNameSyntax identifier)
        {
            return null;
        }

        foreach (var lambda in site.AncestorsAndSelf().OfType<LambdaExpressionSyntax>())
        {
            var first = lambda switch
            {
                SimpleLambdaExpressionSyntax simple => simple.Parameter.Identifier.Text,
                ParenthesizedLambdaExpressionSyntax parenthesized => parenthesized.ParameterList.Parameters.FirstOrDefault()?.Identifier.Text,
                _ => null,
            };
            if (first != identifier.Identifier.Text)
            {
                continue;
            }

            return lambda.Parent is ArgumentSyntax { Parent.Parent: InvocationExpressionSyntax owner }
                   && SyntaxHelpers.InvokedName(owner) is "GetOrAdd" or "AddOrUpdate"
                   && owner.ArgumentList.Arguments.Count > 1
                ? owner.ArgumentList.Arguments[0].Expression
                : null;
        }

        return null;
    }

    /// <summary>The inner call's bindings, with every reference to the outer
    /// method's parameters replaced by what the outer call site passes.</summary>
    private static CallSiteEvaluator.Env Compose(CallSiteEvaluator.Env inner, CallSiteEvaluator.Env outer) => new(
        inner.TypeArguments.ToDictionary(t => t.Key, t => outer.TypeArguments.GetValueOrDefault(t.Value, t.Value), StringComparer.Ordinal),
        inner.Arguments.ToDictionary(
            a => a.Key,
            a => a.Value is IdentifierNameSyntax id && outer.Arguments.TryGetValue(id.Identifier.Text, out var passed) ? passed : a.Value,
            StringComparer.Ordinal),
        outer.Via);

    // ---------- options-bound configuration ----------

    /// <summary>A variable holding one entry of an options-bound dictionary:
    /// its configuration section in one environment.</summary>
    private sealed record Section(string Path, ExpressionSyntax At);

    /// <summary>
    /// The client a factory builds from options-bound configuration, or null
    /// when the factory's binding is not read from a configuration section.
    /// Each environment whose files set any key read is one binding with its
    /// own address and security.
    /// </summary>
    private static Found? FromOptionsClient(
        DetectionContext context, ParsedFile file, SyntaxNode scope, string factoryType, string contract, IReadOnlyList<ExpressionSyntax> arguments,
        CallSiteEvaluator.Env env, string? via, string? condition, IReadOnlyList<CallSite> callSites)
    {
        if (arguments.Count < 2)
        {
            return null;
        }

        var directory = context.Project.ProjectDirectory;
        var read = new List<ConfigKey>();
        var primary = Read(context.Resolver, "default");
        if (primary is null)
        {
            return null;
        }

        var environments = context.Config.EnvironmentsFor(directory, read.Distinct().ToList());
        var bindings = new List<EnvironmentBinding>();
        foreach (var environment in environments.Count == 0 ? ["default"] : environments)
        {
            var reading = environment == "default" ? primary : Read(context.Resolver.For(environment), environment);
            if (reading is null)
            {
                continue;
            }

            var (endpoint, entry) = reading.Value.Address;
            bindings.Add(new EnvironmentBinding
            {
                Environment = environment,
                SourceFile = entry?.File ?? "(not set)",
                KeyPath = entry?.KeyPath ?? reading.Value.AddressKey,
                Scheme = endpoint.Scheme,
                Host = endpoint.Host,
                Port = endpoint.Port,
                Path = endpoint.Path,
                Resolution = endpoint.Resolution,
                Placeholder = endpoint.Placeholder,
                HostProject = entry is null ? null : context.Config.HostFor(directory, entry.Directory),
                DeployParameter = entry?.Link?.Parameter,
                LinkMethod = entry?.Link?.Method,
                LinkConfidence = entry?.Link?.Confidence,
                Soap = reading.Value.Security,
            });
        }

        var (binding, mode, transport, message) = primary.Value.Binding;
        var credentials = CodeCredentials(file, scope, env, via, gate => Gate(context.Resolver, primary.Value.Sections, environments, gate));
        var reasons = new List<string>
        {
            $"client built by a helper from options-bound configuration: {primary.Value.ClientSection} -> {primary.Value.BindingSection}",
            $"binding type, security mode and credential type read by key name ({string.Join(", ", primary.Value.KeysUsed)})",
        };
        var confidence = 0.9;
        if (primary.Value.Address.Endpoint.Resolution != Resolutions.Resolved)
        {
            confidence -= 0.1;
            reasons.Add($"address {primary.Value.Address.Endpoint.Resolution}");
        }

        return new Found(contract, factoryType, "hand_written", "config", binding, mode, transport, message,
            primary.Value.Address.Endpoint, bindings, primary.Value.ClientName, condition, via, credentials, callSites, confidence, reasons);

        Reading? Read(ValueResolver resolver, string environment)
        {
            var sections = Sections(resolver, scope, env, read);
            if (AddressMember(arguments[1], scope) is not { } address || !sections.TryGetValue(address.Variable, out var clientSection))
            {
                return null;
            }

            var bindingSection = BindingSection(arguments[0], sections);
            if (bindingSection is null)
            {
                return null;
            }

            var keysUsed = new List<string>();
            string? Value(Section section, string[] names)
            {
                foreach (var name in names)
                {
                    var key = new ConfigKey($"{section.Path}:{name}", "json");
                    read.Add(key);
                    if (resolver.FromConfig(key) is { TextValue: { } configured })
                    {
                        keysUsed.Add(name);
                        return configured;
                    }

                    if (CodeDefault(context, name) is { } coded)
                    {
                        keysUsed.Add($"{name} (code default)");
                        return coded;
                    }
                }

                return null;
            }

            var typeName = Value(bindingSection, BindingTypeKeys);
            var bindingName = typeName is null ? "unknown"
                : WcfSecurity.BindingNames.TryGetValue(typeName, out var known) ? known
                : WcfSecurity.BindingNames.Values.FirstOrDefault(v => v.Equals(typeName, StringComparison.OrdinalIgnoreCase)) ?? typeName;
            var modeName = Value(bindingSection, SecurityModeKeys);
            var credential = Value(bindingSection, CredentialTypeKeys);
            var onMessage = modeName is "Message" or "TransportWithMessageCredential";
            var security = WcfSecurity.Resolve(bindingName, modeName, onMessage ? null : credential, onMessage ? credential : null);

            var addressKey = new ConfigKey($"{clientSection.Path}:{address.Member}", "json");
            read.Add(addressKey);
            var addressValue = resolver.FromConfig(addressKey);
            var source = addressValue.Parts.OfType<TextPart>().Select(p => p.Source).FirstOrDefault(s => s is not null);
            var entry = source is null ? null : resolver.Config.EntryFor(source.SourceFile, source.KeyPath);

            return new Reading(
                sections, clientSection.Path, bindingSection.Path, ClientName(clientSection.Path), keysUsed.Distinct().ToList(),
                (bindingName, modeName, onMessage ? null : credential, onMessage ? credential : null),
                new EnvironmentSoapSecurity
                {
                    Binding = bindingName, SecurityMode = security.SecurityMode,
                    ClientCredentialType = security.ClientCredentialType, SecuritySource = security.SecuritySource,
                },
                (Endpoints.FromValue(addressValue), entry), addressKey.KeyPath);
        }
    }

    private readonly record struct Reading(
        IReadOnlyDictionary<string, Section> Sections,
        string ClientSection,
        string BindingSection,
        string ClientName,
        IReadOnlyList<string> KeysUsed,
        (string Binding, string? Mode, string? Transport, string? Message) Binding,
        EnvironmentSoapSecurity Security,
        (Endpoint Endpoint, ConfigEntry? Entry) Address,
        string AddressKey);

    private static string ClientName(string sectionPath) => sectionPath[(sectionPath.LastIndexOf(':') + 1)..];

    /// <summary>
    /// Variables bound to an entry of an options-bound dictionary in
    /// <paramref name="scope"/>, in source order so one lookup can key the
    /// next: <c>settings.Clients.TryGetValue(name, out var client)</c> and
    /// <c>var client = settings.Clients[name]</c> give <c>client</c> the section
    /// <c>Wcf:Clients:{name}</c>; <c>settings.Bindings.TryGetValue(client.BindingName, ...)</c>
    /// then reads <c>BindingName</c> from that section.
    /// </summary>
    private static Dictionary<string, Section> Sections(ValueResolver resolver, SyntaxNode scope, CallSiteEvaluator.Env env, List<ConfigKey> read)
    {
        var sections = new Dictionary<string, Section>(StringComparer.Ordinal);
        foreach (var node in scope.DescendantNodes())
        {
            (ExpressionSyntax Dictionary, ExpressionSyntax Key, string Variable)? lookup = node switch
            {
                InvocationExpressionSyntax { Expression: MemberAccessExpressionSyntax { Name.Identifier.Text: "TryGetValue" } access } call
                    when call.ArgumentList.Arguments is [var key, { RefKindKeyword.RawKind: (int)SyntaxKind.OutKeyword } output]
                         && OutVariable(output.Expression) is { } variable =>
                    (access.Expression, key.Expression, variable),
                VariableDeclaratorSyntax { Initializer.Value: ElementAccessExpressionSyntax { ArgumentList.Arguments: [var key] } element } declarator =>
                    (element.Expression, key.Expression, declarator.Identifier.Text),
                _ => null,
            };
            if (lookup is not { } found)
            {
                continue;
            }

            var dictionary = found.Dictionary is MemberAccessExpressionSyntax { Expression: IdentifierNameSyntax owner } member
                             && sections.TryGetValue(owner.Identifier.Text, out var parent)
                ? $"{parent.Path}:{member.Name.Identifier.Text}"
                : resolver.Resolve(found.Dictionary, env) is { IsText: false, Keys: [var dictionaryKey] } ? dictionaryKey.KeyPath : null;
            var name = KeyText(resolver, found.Key, sections, env, read);
            if (dictionary is not null && name is not null)
            {
                sections[found.Variable] = new Section($"{dictionary}:{name}", found.Key);
            }
        }

        return sections;
    }

    private static string? OutVariable(ExpressionSyntax expression) => expression switch
    {
        DeclarationExpressionSyntax { Designation: SingleVariableDesignationSyntax single } => single.Identifier.Text,
        IdentifierNameSyntax identifier => identifier.Identifier.Text,
        _ => null,
    };

    /// <summary>A dictionary key: <c>section.Member</c> read from configuration, else the value as resolved.</summary>
    private static string? KeyText(ValueResolver resolver, ExpressionSyntax key, IReadOnlyDictionary<string, Section> sections, CallSiteEvaluator.Env env, List<ConfigKey> read)
    {
        if (key is MemberAccessExpressionSyntax { Expression: IdentifierNameSyntax owner } member && sections.TryGetValue(owner.Identifier.Text, out var section))
        {
            var configKey = new ConfigKey($"{section.Path}:{member.Name.Identifier.Text}", "json");
            read.Add(configKey);
            return resolver.FromConfig(configKey).TextValue;
        }

        return resolver.Resolve(key, env).TextValue;
    }

    /// <summary>The section variable and member an address is read from:
    /// <c>new EndpointAddress(uri)</c> where <c>Uri.TryCreate(client.EndpointAddress, ..., out var uri)</c>,
    /// <c>new EndpointAddress(client.Url)</c>, <c>new Uri(client.Url)</c>.</summary>
    private static (string Variable, string Member)? AddressMember(ExpressionSyntax expression, SyntaxNode scope, int depth = 0)
    {
        if (depth > 4)
        {
            return null;
        }

        switch (expression)
        {
            case MemberAccessExpressionSyntax { Expression: IdentifierNameSyntax owner } member:
                return (owner.Identifier.Text, member.Name.Identifier.Text);
            case ObjectCreationExpressionSyntax { ArgumentList.Arguments.Count: > 0 } creation
                when SyntaxHelpers.RightmostTypeName(creation.Type) is "Uri" or "EndpointAddress":
                return AddressMember(creation.ArgumentList.Arguments[0].Expression, scope, depth + 1);
            case IdentifierNameSyntax identifier:
            {
                var name = identifier.Identifier.Text;
                if (scope.DescendantNodes().OfType<VariableDeclaratorSyntax>()
                        .LastOrDefault(v => v.Identifier.Text == name && v.Initializer is not null && v.SpanStart < expression.SpanStart) is { } declarator)
                {
                    return AddressMember(declarator.Initializer!.Value, scope, depth + 1);
                }

                var tryCreate = scope.DescendantNodes().OfType<InvocationExpressionSyntax>().FirstOrDefault(i =>
                    SyntaxHelpers.InvokedName(i) == "TryCreate"
                    && i.ArgumentList.Arguments.LastOrDefault() is { RefKindKeyword.RawKind: (int)SyntaxKind.OutKeyword } output
                    && OutVariable(output.Expression) == name);
                return tryCreate is null ? null : AddressMember(tryCreate.ArgumentList.Arguments[0].Expression, scope, depth + 1);
            }

            default:
                return null;
        }
    }

    /// <summary>The section a binding is built from: the binding argument
    /// itself, or a section variable passed to the method that builds it
    /// (<c>WcfBindingFactory.Create(client.BindingName, bindingSettings)</c>).</summary>
    private static Section? BindingSection(ExpressionSyntax binding, IReadOnlyDictionary<string, Section> sections)
    {
        if (binding is IdentifierNameSyntax identifier)
        {
            return sections.GetValueOrDefault(identifier.Identifier.Text);
        }

        return binding is InvocationExpressionSyntax call
            ? call.ArgumentList.Arguments.Select(a => a.Expression).OfType<IdentifierNameSyntax>()
                .Select(a => sections.GetValueOrDefault(a.Identifier.Text)).FirstOrDefault(s => s is not null)
            : null;
    }

    /// <summary>A settings property's initializer, when every declaration of
    /// that property name in the repository agrees on one string or enum value:
    /// <c>public string BindingMode { get; set; } = "Transport";</c>.</summary>
    private static string? CodeDefault(DetectionContext context, string property)
    {
        var values = context.Index.InitializedProperties[property]
            .Select(p => SyntaxHelpers.StringValue(p.Initializer!.Value) ?? (p.Initializer.Value as MemberAccessExpressionSyntax)?.Name.Identifier.Text)
            .Distinct(StringComparer.Ordinal)
            .ToList();
        return values is [{ } single] ? single : null;
    }

    /// <summary>
    /// A credential gated on a configured value —
    /// <c>if (!string.IsNullOrWhiteSpace(client.CertificateName))</c> — is
    /// attached when any environment sets the value, and carries its key.
    /// </summary>
    private static (bool? Truth, string? KeyPath) Gate(
        ValueResolver resolver, IReadOnlyDictionary<string, Section> sections, IReadOnlyList<string> environments, ExpressionSyntax condition)
    {
        var negated = false;
        while (condition is PrefixUnaryExpressionSyntax { RawKind: (int)SyntaxKind.LogicalNotExpression } not)
        {
            negated = !negated;
            condition = not.Operand;
        }

        var (operand, presentWhenTrue) = condition switch
        {
            InvocationExpressionSyntax { ArgumentList.Arguments: [var argument] } call
                when SyntaxHelpers.InvokedName(call) is "IsNullOrWhiteSpace" or "IsNullOrEmpty" => (argument.Expression, false),
            BinaryExpressionSyntax { RawKind: (int)SyntaxKind.NotEqualsExpression, Right: LiteralExpressionSyntax { RawKind: (int)SyntaxKind.NullLiteralExpression } } b =>
                (b.Left, true),
            IsPatternExpressionSyntax { Pattern: UnaryPatternSyntax { Pattern: ConstantPatternSyntax { Expression: LiteralExpressionSyntax { RawKind: (int)SyntaxKind.NullLiteralExpression } } } } p =>
                (p.Expression, true),
            _ => ((ExpressionSyntax?)null, false),
        };
        if (operand is not MemberAccessExpressionSyntax { Expression: IdentifierNameSyntax owner } member
            || !sections.TryGetValue(owner.Identifier.Text, out var section))
        {
            return (null, null);
        }

        var key = new ConfigKey($"{section.Path}:{member.Name.Identifier.Text}", "json");
        var present = (environments.Count == 0 ? ["default"] : environments)
            .Any(e => !string.IsNullOrWhiteSpace(resolver.For(e).FromConfig(key).TextValue));
        return (present == presentWhenTrue ^ negated, key.KeyPath);
    }
}
