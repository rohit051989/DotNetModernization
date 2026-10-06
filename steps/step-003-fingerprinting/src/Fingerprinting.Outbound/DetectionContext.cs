using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Outbound;

/// <summary>A <c>UNC_PATH_LITERAL</c> from step 3's fingerprint: where, and
/// the matched text (which this step reduces to <c>\\server\share</c>).</summary>
public sealed record UncLiteral(string FilePath, int? LineStart, int? LineEnd, string MatchedValue);

/// <summary>What one detector sees for one project.</summary>
public sealed class DetectionContext
{
    public required ProjectSource Project { get; init; }
    public required ValueResolver Resolver { get; init; }
    public required SymbolIndex Symbols { get; init; }
    public required RepositoryConfig Config { get; init; }

    /// <summary>Every loaded project — a client class can be declared in one
    /// project and constructed in another, and a connection string named in
    /// a library is configured in the host.</summary>
    public required IReadOnlyList<ProjectSource> Repository { get; init; }

    public IReadOnlyList<UncLiteral> UncLiterals { get; init; } = [];

    /// <summary>WCF client endpoint entries a client has claimed, shared by
    /// every project's context (1.3.0): a class library's client claims the
    /// entry in its host's configuration.</summary>
    public HashSet<string> ClaimedEndpoints { get; init; } = new(StringComparer.OrdinalIgnoreCase);

    /// <summary>Hand-written source. Generated files are loaded only so
    /// the SOAP detector can read a service reference's binding (Part C2).</summary>
    public IEnumerable<ParsedFile> SourceFiles => Project.Files.Where(f => !f.IsGenerated);
}

/// <summary>An invocation as a detector finds it, before the pipeline
/// derives its id, applies the verdict and merges duplicates.</summary>
/// <param name="Identity">What, beyond the endpoint, makes it distinct:
/// the SOAP contract, the connection-string name, the topic.</param>
public sealed record Detected(Invocation Record, string Identity);

public static class DetectionSupport
{
    public static readonly LinuxCompatibility Pending = new() { Verdict = Verdicts.Unknown };

    public static CallSite CallSiteOf(ParsedFile file, SyntaxNode node)
    {
        var (start, end) = SyntaxHelpers.Lines(node);
        return new CallSite { FilePath = file.RelativePath, LineStart = start, LineEnd = end };
    }

    public static CallSite CallSiteAt(string file, int line) => new() { FilePath = file, LineStart = line, LineEnd = line };

    /// <summary>
    /// The <c>if</c> conditions a client is created under — at its own
    /// call site and, one level up, where its enclosing method is called.
    /// A condition reading configuration is annotated with the configured
    /// value, so <c>settings.EnableHttpEndpoints</c> reads as off when
    /// App.config says <c>false</c>.
    /// </summary>
    public static string? ConditionChain(DetectionContext context, SyntaxNode node)
    {
        var conditions = new List<string>();
        if (CallSiteEvaluator.Condition(node) is { } own)
        {
            conditions.Add(own);
        }

        if (CallSiteEvaluator.Scope(node) is MethodDeclarationSyntax method)
        {
            var callers = CallSiteEvaluator.CallSites(context.Project, method)
                .Select(c => CallSiteEvaluator.Condition(c.Call)).Distinct().ToList();
            if (callers.Count == 1 && callers[0] is { } outer)
            {
                conditions.Insert(0, outer);
                var site = CallSiteEvaluator.CallSites(context.Project, method)[0].Call;
                var ifStatement = site.Ancestors().OfType<IfStatementSyntax>().FirstOrDefault();
                if (ifStatement?.Condition is MemberAccessExpressionSyntax or IdentifierNameSyntax)
                {
                    var value = context.Resolver.Resolve(ifStatement.Condition, CallSiteEvaluator.Empty);
                    if (value.TextValue is { } text && value.Parts.OfType<TextPart>().FirstOrDefault()?.Source is { } source)
                    {
                        conditions[0] = $"{outer} [{source.KeyPath} = {text} in {source.SourceFile}]";
                    }
                }
            }
        }

        return conditions.Count == 0 ? null : string.Join(" && ", conditions);
    }

    /// <summary>
    /// Evaluates a value once per environment whose files set any key it
    /// reads (Part C4): the default environment gives the primary endpoint;
    /// every environment — the default included — becomes a binding with the
    /// file and key it came from.
    /// </summary>
    public static (Endpoint Endpoint, IReadOnlyList<EnvironmentBinding> Bindings, ResolvedValue Value) Evaluate(
        ValueResolver resolver, Func<ValueResolver, ResolvedValue> evaluate, Func<ResolvedValue, Endpoint> normalise)
    {
        var value = evaluate(resolver);
        var endpoint = normalise(value);
        var environments = resolver.Config.EnvironmentsFor(resolver.Project.ProjectDirectory, value.Keys);
        if (environments.Count == 0)
        {
            return (endpoint, [], value);
        }

        var bindings = new List<EnvironmentBinding>();
        foreach (var environment in environments)
        {
            var environmentValue = environment == resolver.Environment ? value : evaluate(resolver.For(environment));
            var environmentEndpoint = environment == resolver.Environment ? endpoint : normalise(environmentValue);
            var source = environmentValue.Parts.OfType<TextPart>().Select(p => p.Source)
                             .FirstOrDefault(s => s is not null && s.SourceFile != "(code default)")
                         ?? environmentValue.Parts.OfType<TextPart>().Select(p => p.Source).FirstOrDefault(s => s is not null);
            var entry = source is null ? null : resolver.Config.EntryFor(source.SourceFile, source.KeyPath);
            bindings.Add(new EnvironmentBinding
            {
                Environment = environment,
                SourceFile = source?.SourceFile ?? "(not set)",
                KeyPath = source?.KeyPath ?? value.Keys[0].KeyPath,
                Scheme = environmentEndpoint.Scheme,
                Host = environmentEndpoint.Host,
                Port = environmentEndpoint.Port,
                Path = environmentEndpoint.Path,
                Resolution = environmentEndpoint.Resolution,
                Placeholder = environmentEndpoint.Placeholder,
                Authentication = environmentValue.Facts is { } facts ? Authentication(facts) : null,
                HostProject = entry is null ? null : resolver.Config.HostFor(resolver.Project.ProjectDirectory, entry.Directory),
                DeployParameter = entry?.Link?.Parameter,
                LinkMethod = entry?.Link?.Method,
                LinkConfidence = entry?.Link?.Confidence,
            });
        }

        return (endpoint, bindings, value);
    }

    public static string Authentication(ConnectionFacts facts) => facts.Authentication switch
    {
        ConnectionAuthentication.Integrated => "integrated",
        ConnectionAuthentication.Credentials => "credentials",
        _ => "unknown",
    };

    /// <summary>A connection string's facts as an endpoint: host and port
    /// only, the provider as the scheme.</summary>
    public static Endpoint FromFacts(ResolvedValue value)
    {
        var source = value.Parts.OfType<TextPart>().Select(p => p.Source).FirstOrDefault(s => s is not null);
        if (value.Facts is not { } facts)
        {
            return value.TextValue is { } text && Secrets.LooksLikeConnectionString(text)
                ? FromFacts(new ResolvedValue(value.Parts) { Facts = Secrets.ReadConnectionFacts(text) })
                : new Endpoint { Resolution = Resolutions.Unresolved, Placeholder = value.Placeholder ?? Label(value), Source = source };
        }

        return new Endpoint
        {
            Scheme = facts.Provider,
            Host = facts.Host,
            Port = int.TryParse(facts.Port, out var port) ? port : null,
            Resolution = facts.Host is null ? Resolutions.Partial : Resolutions.Resolved,
            Source = source,
        };
    }

    public static string Label(ResolvedValue value) =>
        string.Join(" + ", value.Parts.Select(p => p is HolePart h ? h.Placeholder ?? h.Label : "…"));

    /// <summary>A generic type's single type argument, as written:
    /// <c>ChannelFactory&lt;IFoo&gt;</c>, <c>System.ServiceModel.ClientBase&lt;IFoo&gt;</c>.</summary>
    public static TypeSyntax? SingleTypeArgument(TypeSyntax type) => type switch
    {
        GenericNameSyntax { TypeArgumentList.Arguments: [var argument] } => argument,
        QualifiedNameSyntax { Right: GenericNameSyntax { TypeArgumentList.Arguments: [var argument] } } => argument,
        AliasQualifiedNameSyntax { Name: GenericNameSyntax { TypeArgumentList.Arguments: [var argument] } } => argument,
        _ => null,
    };

    /// <summary>The declared type of a receiver — a local's initializer
    /// type or explicit type, or a field, property or parameter's type.</summary>
    public static string? ReceiverType(ExpressionSyntax receiver)
    {
        while (receiver is MemberAccessExpressionSyntax { Expression: ThisExpressionSyntax } self)
        {
            receiver = self.Name;
        }

        if (receiver is not IdentifierNameSyntax identifier)
        {
            return null;
        }

        var local = CallSiteEvaluator.Scope(identifier).DescendantNodes().OfType<VariableDeclaratorSyntax>()
            .LastOrDefault(v => v.Identifier.Text == identifier.Identifier.Text && v.SpanStart < identifier.SpanStart);
        if (local?.Parent is VariableDeclarationSyntax declaration)
        {
            if (!declaration.Type.IsVar)
            {
                return SyntaxHelpers.RightmostTypeName(declaration.Type);
            }

            return local.Initializer?.Value switch
            {
                ObjectCreationExpressionSyntax creation => SyntaxHelpers.RightmostTypeName(creation.Type),
                _ => null,
            };
        }

        var declared = ValueResolver.DeclaredType(identifier);
        return declared is null ? null : SyntaxHelpers.RightmostTypeName(declared is NullableTypeSyntax n ? n.ElementType : declared);
    }
}
