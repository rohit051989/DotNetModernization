using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Outbound;

/// <summary>
/// A Kafka client's SASL mechanism, where it is stated — Part C6. Read from
/// code (<c>SaslMechanism = SaslMechanism.Gssapi</c>, <c>config.Set("sasl.mechanism", "GSSAPI")</c>,
/// a <c>{ "sasl.mechanism", "GSSAPI" }</c> dictionary entry) or from
/// configuration (<c>sasl.mechanism</c>, <c>SaslMechanism</c>, under any
/// section, per environment file). A SASL security protocol with no
/// mechanism stated is GSSAPI: librdkafka's default. A client whose config
/// is built entirely in code with no SASL at all uses none. Anything else —
/// a config object supplied from elsewhere — is <c>unknown</c>.
/// </summary>
public static class Sasl
{
    /// <param name="Mechanism"><c>gssapi</c>, <c>plain</c>, <c>scram</c>,
    /// <c>oauthbearer</c>, <c>none</c> or <c>unknown</c> — the default
    /// environment's.</param>
    /// <param name="ByEnvironment">When read from configuration: each
    /// environment file's own mechanism.</param>
    public sealed record Result(string Mechanism, string? Source, IReadOnlyDictionary<string, string>? ByEnvironment);

    private static readonly string[] MechanismKeys = ["saslmechanism", "saslmechanisms"];
    private static readonly string[] ProtocolKeys = ["securityprotocol"];

    public static Result Read(
        DetectionContext context, ParsedFile file, SyntaxNode scope,
        (string? Variable, ObjectCreationExpressionSyntax? Creation, ExpressionSyntax? Initializer) config)
    {
        // 1. Stated in code.
        var (mechanism, protocol, where) = FromCode(context, file, scope, config);
        if (mechanism is not null)
        {
            return new Result(mechanism, where, null);
        }

        // 2. Stated in configuration — per environment.
        var fromConfig = FromConfiguration(context);
        if (fromConfig is not null)
        {
            return fromConfig;
        }

        if (protocol is not null)
        {
            return protocol.Contains("sasl", StringComparison.OrdinalIgnoreCase)
                ? new Result("gssapi", $"{where} (SASL with no mechanism stated: librdkafka's default is GSSAPI)", null)
                : new Result("none", where, null);
        }

        // 3. Built entirely in code, nothing bound from configuration: no SASL.
        // A local can be bound from configuration after it is created.
        var bound = config.Variable is { } variable
                    && scope.DescendantNodes().OfType<InvocationExpressionSyntax>().Any(i =>
                        SyntaxHelpers.InvokedName(i) is "Bind" or "Get" && i.ToString().Contains(variable, StringComparison.Ordinal));
        var builtInCode = config.Creation is not null && !bound && config.Creation.ArgumentList?.Arguments.Count is null or 0;
        return builtInCode
            ? new Result("none", $"{CallSiteEvaluator.Where(file, config.Creation!)} (config built in code with no SASL settings)", null)
            : new Result("unknown", null, null);
    }

    /// <summary>The SASL mechanism and security protocol set on the config
    /// object, or as librdkafka string properties anywhere in scope.</summary>
    private static (string? Mechanism, string? Protocol, string? Where) FromCode(
        DetectionContext context, ParsedFile file, SyntaxNode scope,
        (string? Variable, ObjectCreationExpressionSyntax? Creation, ExpressionSyntax? Initializer) config)
    {
        string? mechanism = null, protocol = null, where = null;

        void Take(string property, ExpressionSyntax value, SyntaxNode at)
        {
            var text = CallSiteEvaluator.EnumName(value, CallSiteEvaluator.Empty)
                       ?? context.Resolver.Resolve(value, CallSiteEvaluator.Empty).TextValue;
            if (text is null)
            {
                return;
            }

            var key = Normalise(property);
            if (MechanismKeys.Contains(key))
            {
                mechanism ??= MechanismName(text);
                where ??= CallSiteEvaluator.Where(file, at);
            }
            else if (ProtocolKeys.Contains(key))
            {
                protocol ??= text;
                where ??= CallSiteEvaluator.Where(file, at);
            }
        }

        foreach (var assignment in config.Creation?.Initializer?.Expressions.OfType<AssignmentExpressionSyntax>() ?? [])
        {
            if (assignment.Left is IdentifierNameSyntax property)
            {
                Take(property.Identifier.Text, assignment.Right, assignment);
            }
            else if (assignment.Left is ImplicitElementAccessSyntax { ArgumentList.Arguments: [var index] } && SyntaxHelpers.StringValue(index.Expression) is { } name)
            {
                Take(name, assignment.Right, assignment);   // ["sasl.mechanism"] = "GSSAPI"
            }
        }

        foreach (var node in scope.DescendantNodes())
        {
            switch (node)
            {
                case AssignmentExpressionSyntax { Left: MemberAccessExpressionSyntax member } assignment
                    when config.Variable is not null && member.Expression.ToString() == config.Variable:
                    Take(member.Name.Identifier.Text, assignment.Right, assignment);
                    break;
                // config.Set("sasl.mechanism", "GSSAPI")
                case InvocationExpressionSyntax invocation when SyntaxHelpers.InvokedName(invocation) == "Set"
                                                                && invocation.ArgumentList.Arguments.Count == 2
                                                                && SyntaxHelpers.StringValue(invocation.ArgumentList.Arguments[0].Expression) is { } name:
                    Take(name, invocation.ArgumentList.Arguments[1].Expression, invocation);
                    break;
                // { "sasl.mechanism", "GSSAPI" } in a dictionary initializer
                case InitializerExpressionSyntax { Expressions: [var keyExpression, var valueExpression] } pair
                    when pair.Parent is InitializerExpressionSyntax && SyntaxHelpers.StringValue(keyExpression) is { } name:
                    Take(name, valueExpression, pair);
                    break;
            }
        }

        return (mechanism, protocol, where);
    }

    /// <summary>A SASL mechanism or security protocol key in the project's
    /// configuration, read per environment file with the default layered under.</summary>
    private static Result? FromConfiguration(DetectionContext context)
    {
        var entries = context.Config.Entries
            .Where(e => e.Value is not null && context.Config.Governs(context.Project.ProjectDirectory, e.Directory))
            .Select(e => (Entry: e, Key: Normalise(e.KeyPath.Split(':')[^1])))
            .ToList();
        var mechanisms = entries.Where(e => MechanismKeys.Contains(e.Key)).Select(e => e.Entry).ToList();
        var protocols = entries.Where(e => ProtocolKeys.Contains(e.Key) && e.Entry.Value!.Contains("sasl", StringComparison.OrdinalIgnoreCase)).Select(e => e.Entry).ToList();
        if (mechanisms.Count == 0 && protocols.Count == 0)
        {
            return null;
        }

        var environments = mechanisms.Concat(protocols).Select(e => e.Environment).Append("default").Distinct(StringComparer.Ordinal).ToList();
        var byEnvironment = new SortedDictionary<string, string>(StringComparer.Ordinal);
        foreach (var environment in environments)
        {
            var stated = mechanisms.FirstOrDefault(e => e.Environment == environment) ?? mechanisms.FirstOrDefault(e => e.Environment == "default");
            var sasl = protocols.FirstOrDefault(e => e.Environment == environment) ?? protocols.FirstOrDefault(e => e.Environment == "default");
            byEnvironment[environment] = stated is not null ? MechanismName(stated.Value!) : sasl is not null ? "gssapi" : "unknown";
        }

        var source = mechanisms.FirstOrDefault(e => e.Environment == "default") ?? mechanisms.FirstOrDefault() ?? protocols.First();
        var note = mechanisms.Count == 0 ? " (SASL with no mechanism stated: librdkafka's default is GSSAPI)" : "";
        return new Result(byEnvironment["default"], $"{source.File} {source.KeyPath}{note}", byEnvironment);
    }

    /// <summary>Gives every environment binding its SASL mechanism, adding a
    /// binding for an environment whose file sets only the mechanism.</summary>
    public static IReadOnlyList<EnvironmentBinding> Bind(
        DetectionContext context, Result sasl, Endpoint endpoint, IReadOnlyList<EnvironmentBinding> bindings)
    {
        if (sasl.ByEnvironment is null)
        {
            return bindings.Select(b => b with { Authentication = sasl.Mechanism }).ToList();
        }

        var byEnvironment = bindings.ToDictionary(b => b.Environment, StringComparer.Ordinal);
        var result = new List<EnvironmentBinding>();
        foreach (var environment in byEnvironment.Keys.Concat(sasl.ByEnvironment.Keys).Distinct(StringComparer.Ordinal)
                     .OrderBy(e => e == "default" ? 0 : 1).ThenBy(e => e, StringComparer.Ordinal))
        {
            var mechanism = sasl.ByEnvironment.GetValueOrDefault(environment) ?? sasl.ByEnvironment.GetValueOrDefault("default") ?? sasl.Mechanism;
            var binding = byEnvironment.GetValueOrDefault(environment)
                          ?? byEnvironment.GetValueOrDefault("default")
                          ?? new EnvironmentBinding
                          {
                              Environment = environment,
                              SourceFile = endpoint.Source?.SourceFile ?? "(code)",
                              KeyPath = endpoint.Source?.KeyPath ?? "BootstrapServers",
                              Scheme = endpoint.Scheme,
                              Host = endpoint.Host,
                              Port = endpoint.Port,
                              Path = endpoint.Path,
                              Resolution = endpoint.Resolution,
                              Placeholder = endpoint.Placeholder,
                          };
            result.Add(binding with { Environment = environment, Authentication = mechanism });
        }

        return result;
    }

    private static string Normalise(string key) => new(key.ToLowerInvariant().Where(char.IsLetterOrDigit).ToArray());

    /// <summary><c>GSSAPI</c>, <c>Gssapi</c> → gssapi; <c>SCRAM-SHA-512</c>,
    /// <c>ScramSha256</c> → scram; <c>OAUTHBEARER</c> → oauthbearer.</summary>
    public static string MechanismName(string text)
    {
        var name = Normalise(text);
        return name switch
        {
            "gssapi" => "gssapi",
            "plain" => "plain",
            _ when name.StartsWith("scram", StringComparison.Ordinal) => "scram",
            "oauthbearer" => "oauthbearer",
            _ => "unknown",
        };
    }
}
