using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Outbound;

/// <summary>
/// Part C4, from code: what a URL, host or connection string argument
/// evaluates to. Follows call-site arguments (step 4's <see cref="CallSiteEvaluator"/>
/// environment, so a value passed into a generic helper resolves per call),
/// locals, constants, member assignments, <c>ConfigurationManager.AppSettings</c>
/// and <c>IConfiguration</c> reads, options binding, and environment
/// variables — which become named placeholders. Anything else is a hole,
/// recorded as such; nothing is guessed. Configuration is read as
/// <see cref="Environment"/> sees it: that environment's file over the default.
/// </summary>
public sealed partial class ValueResolver(ProjectSource project, SymbolIndex symbols, RepositoryConfig config, string environment = "default")
{
    private const int MaxDepth = 8;

    [System.Text.RegularExpressions.GeneratedRegex(@"@?\$?""(?:[^""\\]|\\.)*""")]
    private static partial System.Text.RegularExpressions.Regex StringLiteral();

    public string Environment => environment;

    public ProjectSource Project => project;

    public RepositoryConfig Config => config;

    public ValueResolver For(string otherEnvironment) =>
        otherEnvironment == environment ? this : new ValueResolver(project, symbols, config, otherEnvironment);

    public ResolvedValue Resolve(ExpressionSyntax expression, CallSiteEvaluator.Env env) => Resolve(expression, env, 0);

    private ResolvedValue Resolve(ExpressionSyntax expression, CallSiteEvaluator.Env env, int depth)
    {
        if (depth > MaxDepth)
        {
            return ResolvedValue.Hole(Label(expression));
        }

        switch (expression)
        {
            case LiteralExpressionSyntax literal when literal.IsKind(SyntaxKind.StringLiteralExpression):
                return ResolvedValue.Text(literal.Token.ValueText);
            case LiteralExpressionSyntax literal when literal.IsKind(SyntaxKind.NumericLiteralExpression):
                return ResolvedValue.Text(literal.Token.Text);
            case LiteralExpressionSyntax literal when literal.IsKind(SyntaxKind.TrueLiteralExpression) || literal.IsKind(SyntaxKind.FalseLiteralExpression):
                return ResolvedValue.Text(literal.Token.Text);
            case LiteralExpressionSyntax literal when literal.IsKind(SyntaxKind.NullLiteralExpression):
                return ResolvedValue.Hole("null");

            case InterpolatedStringExpressionSyntax interpolated:
                return ResolvedValue.Join(interpolated.Contents.Select(c => c switch
                {
                    InterpolatedStringTextSyntax text => ResolvedValue.Text(text.TextToken.ValueText),
                    InterpolationSyntax hole => Resolve(hole.Expression, env, depth + 1),
                    _ => new ResolvedValue([]),
                }));

            case BinaryExpressionSyntax binary when binary.IsKind(SyntaxKind.AddExpression):
                return Resolve(binary.Left, env, depth + 1).Concat(Resolve(binary.Right, env, depth + 1));

            case BinaryExpressionSyntax binary when binary.IsKind(SyntaxKind.CoalesceExpression):
            {
                var left = Resolve(binary.Left, env, depth + 1);
                if (left.IsText || left.Facts is not null)
                {
                    return left;
                }

                // The configured value is in no file; the code's own default
                // is what runs, and it is written, not guessed.
                var fallback = Resolve(binary.Right, env, depth + 1);
                if (fallback.TextValue is { Length: > 0 } text)
                {
                    var source = left.WholeConfig is { } key ? new ConfigSource { SourceFile = "(code default)", KeyPath = key.KeyPath } : null;
                    return ResolvedValue.Text(text, source) with { Keys = left.Keys };
                }

                return left;
            }

            case ParenthesizedExpressionSyntax parenthesized:
                return Resolve(parenthesized.Expression, env, depth + 1);
            case CastExpressionSyntax cast:
                return Resolve(cast.Expression, env, depth + 1);
            case PostfixUnaryExpressionSyntax { RawKind: (int)SyntaxKind.SuppressNullableWarningExpression } bang:
                return Resolve(bang.Operand, env, depth + 1);
            case ConditionalAccessExpressionSyntax { WhenNotNull: MemberBindingExpressionSyntax binding } conditional:
                // settings?.Url reads settings.Url.
                return ResolveMemberOf(conditional.Expression, binding.Name.Identifier.Text, conditional, env, depth);

            case ObjectCreationExpressionSyntax creation when SyntaxHelpers.RightmostTypeName(creation.Type) is "Uri" or "EndpointAddress":
            {
                var arguments = creation.ArgumentList?.Arguments ?? default;
                if (arguments.Count == 0)
                {
                    return ResolvedValue.Hole(Label(expression));
                }

                var first = Resolve(arguments[0].Expression, env, depth + 1);
                // new Uri(baseUri, "relative") — the relative part appends.
                return arguments.Count > 1 && SyntaxHelpers.RightmostTypeName(creation.Type) == "Uri"
                       && arguments[1].Expression is not MemberAccessExpressionSyntax { Name.Identifier.Text: "Absolute" or "Relative" or "RelativeOrAbsolute" }
                    ? first.Concat(Resolve(arguments[1].Expression, env, depth + 1))
                    : first;
            }

            case InvocationExpressionSyntax invocation:
                return ResolveInvocation(invocation, env, depth);

            case ElementAccessExpressionSyntax element:
                return ResolveElementAccess(element, env, depth);

            case IdentifierNameSyntax identifier:
                return ResolveIdentifier(identifier, env, depth);

            case MemberAccessExpressionSyntax member:
                return ResolveMember(member, env, depth);

            default:
                return ResolvedValue.Hole(Label(expression));
        }
    }

    private ResolvedValue ResolveInvocation(InvocationExpressionSyntax invocation, CallSiteEvaluator.Env env, int depth)
    {
        var name = SyntaxHelpers.InvokedName(invocation);
        var firstArgument = invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression;
        var receiver = SyntaxHelpers.Receiver(invocation);

        switch (name)
        {
            case "GetConnectionString" when firstArgument is not null:
                return symbols.Constant(firstArgument) is { } connectionName
                    ? FromConfig(new ConfigKey($"ConnectionStrings:{connectionName}", "connection_string"))
                    : ResolvedValue.Hole(Label(invocation), $"config:ConnectionStrings:[{Label(firstArgument)}]");
            case "GetValue" when symbols.Constant(firstArgument) is { } key:
                return FromConfig(new ConfigKey(Prefix(receiver) + key, "json"));
            case "GetEnvironmentVariable" when symbols.Constant(firstArgument) is { } variable:
                return ResolvedValue.Hole(variable, $"env:{variable}");
            case "Parse" or "ToInt32" or "ToBoolean"
                when firstArgument is not null && receiver is PredefinedTypeSyntax or IdentifierNameSyntax { Identifier.Text: "Convert" or "Int32" or "Boolean" }:
                // int.Parse(x), Convert.ToInt32(x): the value of x.
                return Resolve(firstArgument, env, depth + 1);
            case "ToString" or "Trim" or "TrimEnd" or "TrimStart" or "ToLowerInvariant" or "ToLower"
                when receiver is not null && invocation.ArgumentList.Arguments.Count == 0:
                return Resolve(receiver, env, depth + 1);
            default:
                return ResolvedValue.Hole(Label(invocation));
        }
    }

    /// <summary><c>ConfigurationManager.AppSettings["k"]</c> (or a local
    /// holding it), <c>ConfigurationManager.ConnectionStrings["X"]</c>,
    /// <c>configuration["a:b"]</c>, <c>GetSection("a")["b"]</c>.</summary>
    private ResolvedValue ResolveElementAccess(ElementAccessExpressionSyntax element, CallSiteEvaluator.Env env, int depth)
    {
        var keyExpression = element.ArgumentList.Arguments.FirstOrDefault()?.Expression;
        var key = symbols.Constant(keyExpression);
        var receiver = element.Expression;
        var receiverText = receiver.ToString().Replace(" ", "");

        if (key is null)
        {
            // configuration[configuration["X_KEY"]]: the key is itself
            // configuration — name the one it waits on.
            var inner = keyExpression is null ? null : Resolve(keyExpression, env, depth + 1);
            var named = inner?.TextValue ?? inner?.Placeholder?.Replace("config:", "") ?? (keyExpression is null ? "?" : Label(keyExpression));
            return ResolvedValue.Hole(Label(element), $"config:[{named}]") with { Keys = inner?.Keys ?? [] };
        }

        if (receiverText.EndsWith("AppSettings", StringComparison.Ordinal) || HoldsAppSettings(receiver))
        {
            return FromConfig(new ConfigKey(key, "app_setting"));
        }

        if (receiverText.EndsWith("ConnectionStrings", StringComparison.Ordinal))
        {
            return FromConfig(new ConfigKey($"ConnectionStrings:{key}", "connection_string"));
        }

        return FromConfig(new ConfigKey(Prefix(receiver) + key, "json"));
    }

    /// <summary>A local assigned <c>ConfigurationManager.AppSettings</c>.</summary>
    private static bool HoldsAppSettings(ExpressionSyntax receiver)
    {
        if (receiver is not IdentifierNameSyntax identifier)
        {
            return false;
        }

        var initializer = CallSiteEvaluator.Scope(receiver).DescendantNodes().OfType<VariableDeclaratorSyntax>()
            .FirstOrDefault(v => v.Identifier.Text == identifier.Identifier.Text)?.Initializer?.Value;
        return initializer?.ToString().Replace(" ", "").EndsWith("AppSettings", StringComparison.Ordinal) == true;
    }

    /// <summary>The section prefix of a receiver: <c>config.GetSection("a")</c>
    /// is <c>a:</c>, as is a local holding it; a plain configuration object
    /// is the root.</summary>
    private string Prefix(ExpressionSyntax? receiver)
    {
        if (receiver is IdentifierNameSyntax identifier)
        {
            var initializer = CallSiteEvaluator.Scope(receiver).DescendantNodes().OfType<VariableDeclaratorSyntax>()
                .FirstOrDefault(v => v.Identifier.Text == identifier.Identifier.Text)?.Initializer?.Value;
            if (initializer is InvocationExpressionSyntax)
            {
                receiver = initializer;
            }
        }

        return receiver is InvocationExpressionSyntax call && SyntaxHelpers.InvokedName(call) is "GetSection" or "GetRequiredSection"
               && symbols.Constant(call.ArgumentList.Arguments.FirstOrDefault()?.Expression) is { } section
            ? Prefix(SyntaxHelpers.Receiver(call)) + section + ":"
            : "";
    }

    private ResolvedValue ResolveIdentifier(IdentifierNameSyntax identifier, CallSiteEvaluator.Env env, int depth)
    {
        var name = identifier.Identifier.Text;
        if (env.Arguments.TryGetValue(name, out var argument))
        {
            // Bound at a helper's call site: resolve in the caller.
            return Resolve(argument, CallSiteEvaluator.Empty, depth + 1);
        }

        var scope = CallSiteEvaluator.Scope(identifier);
        var local = scope.DescendantNodes().OfType<VariableDeclaratorSyntax>()
            .LastOrDefault(v => v.Identifier.Text == name && v.Initializer is not null && v.SpanStart < identifier.SpanStart);
        if (local is not null)
        {
            return Resolve(local.Initializer!.Value, env, depth + 1);
        }

        if (symbols.Constant(identifier) is { } constant)
        {
            return ResolvedValue.Text(constant);
        }

        if (scope is BaseMethodDeclarationSyntax method && method.ParameterList.Parameters.Any(p => p.Identifier.Text == name))
        {
            // A parameter nothing bound: supplied by the caller at run time.
            return ResolvedValue.Hole(name, $"runtime:{name}");
        }

        return FromAssignments(name, identifier, depth);
    }

    private ResolvedValue ResolveMember(MemberAccessExpressionSyntax member, CallSiteEvaluator.Env env, int depth) =>
        symbols.Constant(member) is { } constant
            ? ResolvedValue.Text(constant)
            : ResolveMemberOf(member.Expression, member.Name.Identifier.Text, member, env, depth);

    /// <summary><c>receiver.memberName</c>, written as a member access or as
    /// <c>receiver?.memberName</c>; <paramref name="site"/> is the whole expression.</summary>
    private ResolvedValue ResolveMemberOf(ExpressionSyntax receiver, string memberName, ExpressionSyntax site, CallSiteEvaluator.Env env, int depth)
    {
        // ConfigurationManager.ConnectionStrings["X"].ConnectionString
        if (memberName == "ConnectionString" && receiver is ElementAccessExpressionSyntax element)
        {
            return ResolveElementAccess(element, env, depth);
        }

        if (memberName == "BaseAddress" && receiver.ToString().Replace(" ", "").EndsWith("HostEnvironment", StringComparison.Ordinal))
        {
            return ResolvedValue.Hole(memberName, "runtime:host base address");
        }

        // Options binding: opts.Value.ApiBase, _options.ApiBase, config!.WebBase.
        var optionsType = OptionsTypeOf(receiver);
        if (optionsType is not null && symbols.OptionsSection(optionsType) is { } section)
        {
            return FromConfig(new ConfigKey($"{section}:{memberName}", "json"));
        }

        return FromAssignments(memberName, site, depth);
    }

    /// <summary>A member assigned in one place (a field set in a
    /// constructor, a property set in an object initializer) resolves to
    /// what it is assigned; several differing assignments do not.</summary>
    private ResolvedValue FromAssignments(string name, ExpressionSyntax site, int depth)
    {
        var assigned = symbols.AssignmentsTo(project, name).Where(a => !a.Span.Contains(site.Span) || a.SyntaxTree != site.SyntaxTree).ToList();
        if (assigned.Count == 0)
        {
            return ResolvedValue.Hole(name);
        }

        var values = assigned.Select(a => Resolve(a, CallSiteEvaluator.Empty, depth + 1)).ToList();
        var distinct = values.Select(v => v.TextValue ?? v.WholeConfig?.KeyPath ?? v.Placeholder ?? "\u0000" + name).Distinct().Count();
        return distinct == 1 ? values[0] : ResolvedValue.Hole(name) with { Keys = values.SelectMany(v => v.Keys).Distinct().ToList() };
    }

    /// <summary>The options class behind a receiver: <c>x.Value</c> where x
    /// is an <c>IOptions&lt;T&gt;</c>, a field, property, local or parameter
    /// declared as T, or a local assigned <c>section.Get&lt;T&gt;()</c>.</summary>
    private static string? OptionsTypeOf(ExpressionSyntax receiver)
    {
        while (receiver is PostfixUnaryExpressionSyntax { RawKind: (int)SyntaxKind.SuppressNullableWarningExpression } bang)
        {
            receiver = bang.Operand;
        }

        if (receiver is MemberAccessExpressionSyntax { Name.Identifier.Text: "Value" or "CurrentValue" } value)
        {
            receiver = value.Expression;
        }

        if (receiver is not IdentifierNameSyntax identifier)
        {
            return null;
        }

        var local = CallSiteEvaluator.Scope(identifier).DescendantNodes().OfType<VariableDeclaratorSyntax>()
            .FirstOrDefault(v => v.Identifier.Text == identifier.Identifier.Text);
        if (local is not null)
        {
            if (local.Initializer?.Value is InvocationExpressionSyntax
                {
                    Expression: MemberAccessExpressionSyntax { Name: GenericNameSyntax { Identifier.Text: "Get", TypeArgumentList.Arguments: [var bound] } },
                })
            {
                return SyntaxHelpers.RightmostTypeName(bound);
            }

            if (local.Parent is VariableDeclarationSyntax { Type: { IsVar: false } localType })
            {
                return Unwrap(localType);
            }
        }

        var type = DeclaredType(identifier);
        return type is null ? null : Unwrap(type);

        static string? Unwrap(TypeSyntax type) => type switch
        {
            GenericNameSyntax { Identifier.Text: "IOptions" or "IOptionsSnapshot" or "IOptionsMonitor", TypeArgumentList.Arguments: [var inner] } =>
                SyntaxHelpers.RightmostTypeName(inner),
            QualifiedNameSyntax { Right: GenericNameSyntax { Identifier.Text: "IOptions" or "IOptionsSnapshot" or "IOptionsMonitor", TypeArgumentList.Arguments: [var inner] } } =>
                SyntaxHelpers.RightmostTypeName(inner),
            NullableTypeSyntax nullable => SyntaxHelpers.RightmostTypeName(nullable.ElementType),
            _ => SyntaxHelpers.RightmostTypeName(type),
        };
    }

    /// <summary>The declared type of a field, property, parameter or
    /// primary-constructor parameter named by <paramref name="identifier"/>.</summary>
    public static TypeSyntax? DeclaredType(IdentifierNameSyntax identifier)
    {
        var name = identifier.Identifier.Text;
        foreach (var ancestor in identifier.Ancestors())
        {
            switch (ancestor)
            {
                case BaseMethodDeclarationSyntax method when method.ParameterList.Parameters.FirstOrDefault(p => p.Identifier.Text == name) is { Type: { } parameterType }:
                    return parameterType;
                case TypeDeclarationSyntax type:
                    foreach (var fieldOrProperty in type.Members)
                    {
                        if (fieldOrProperty is FieldDeclarationSyntax field && field.Declaration.Variables.Any(v => v.Identifier.Text == name))
                        {
                            return field.Declaration.Type;
                        }

                        if (fieldOrProperty is PropertyDeclarationSyntax property && property.Identifier.Text == name)
                        {
                            return property.Type;
                        }
                    }

                    if (type.ParameterList is { } primary
                        && primary.Parameters.FirstOrDefault(p => p.Identifier.Text == name) is { Type: { } primaryType })
                    {
                        return primaryType;
                    }

                    return null;
            }
        }

        return null;
    }

    /// <summary>A configuration read, as this resolver's environment sees
    /// it — with its file and key — or a named placeholder when no file
    /// has it. A connection string contributes its facts, never its value;
    /// a sensitive key contributes nothing but its name.</summary>
    public ResolvedValue FromConfig(ConfigKey key)
    {
        var entry = config.Effective(project.ProjectDirectory, key, environment);
        if (entry is null)
        {
            return new ResolvedValue([new HolePart(key.KeyPath, $"config:{key.KeyPath}")], key);
        }

        var source = new ConfigSource { SourceFile = entry.File, KeyPath = entry.KeyPath };
        if (entry.Facts is not null)
        {
            return new ResolvedValue([new TextPart("", source)], key) { Facts = entry.Facts };
        }

        if (entry.Value is null)
        {
            return new ResolvedValue([new HolePart(key.KeyPath, $"config:{key.KeyPath} (sensitive: value not read)")], key);
        }

        return new ResolvedValue([new TextPart(entry.Value, source)], key);
    }

    /// <summary>A hole's label: the expression as written, with every
    /// string literal's content removed — a label names code, and a
    /// literal inside it could be a secret (Part C5).</summary>
    public static string Label(SyntaxNode node)
    {
        var text = StringLiteral().Replace(SyntaxHelpers.Collapse(node.ToString()), "\"…\"");
        return text.Length > 60 ? text[..57] + "..." : text;
    }
}
