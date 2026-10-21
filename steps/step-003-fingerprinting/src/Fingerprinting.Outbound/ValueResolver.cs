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
///
/// release 5: what keeps it from growing with the code. A member read follows the assignments to that member; a
/// mapping layer that copies one member name between types (<c>new Entity { Name = dto.Name }</c> in fifteen
/// classes) made that exponential, bounded only by <see cref="MaxDepth"/>. Now:
/// (a) a name being resolved further up is not resolved again — the re-read is a copy, which adds no value of its
/// own — and each name's result is remembered per environment;
/// (b) a name with more than <see cref="MaxAssignments"/> assignments is unresolved, with that reason, without
/// resolving each one;
/// (c) a concatenation (or interpolation) is resolved left to right and stops at a base that names nothing — nothing
/// appended to an unresolvable base makes a usable endpoint; literal text after it is still kept;
/// (d) where the type owning a member is written (a parameter's declared type), only assignments to that type's
/// member (or of a type the code does not show) are weighed.
/// And the work is bounded and stoppable: at most <see cref="MaxSteps"/> steps per value, and the project's time
/// limit is checked at every step.
/// One resolver per project's detection, not shared between threads.
/// </summary>
public sealed partial class ValueResolver(ProjectSource project, SymbolIndex symbols, RepositoryConfig config, string environment = "default")
{
    private const int MaxDepth = 8;

    /// <summary>(b): more assignments than this to one name are not weighed one by one.</summary>
    public const int MaxAssignments = 8;

    /// <summary>The most resolution steps one value may take, whatever its shape.</summary>
    public const int MaxSteps = 20_000;

    private static readonly AsyncLocal<bool> Unguarded = new();

    /// <summary>State the resolvers of one project's detection share, across environments.</summary>
    private sealed class Shared
    {
        public long Calls;
        public CancellationToken Cancellation;
        public readonly Dictionary<string, ValueResolver> ByEnvironment = new(StringComparer.Ordinal);
        public readonly Dictionary<string, IReadOnlySet<string>> Related = new(StringComparer.Ordinal);
    }

    private Shared _shared = new();
    private readonly Dictionary<(string Name, string? Owner, ExpressionSyntax? Excluded), ResolvedValue> _memo = new();
    private readonly List<(string Name, string? Owner)> _resolving = [];
    private int _repeatFloor = int.MaxValue;
    private int _truncations;
    private int _steps;
    private bool _guarded = true;

    /// <summary>How many times the resolver has been asked to evaluate an expression, across environments.</summary>
    public long Calls => _shared.Calls;

    /// <summary>The project's time limit: checked at every resolution step, so one long resolution stops in time.</summary>
    public CancellationToken Cancellation
    {
        get => _shared.Cancellation;
        set => _shared.Cancellation = value;
    }

    /// <summary>For tests only: resolution exactly as before release 5's fixes (a) to (d), to reproduce the explosion
    /// and prove the time limits stop it.</summary>
    public static IDisposable WithoutSafeguards()
    {
        Unguarded.Value = true;
        return new Restore();
    }

    private sealed class Restore : IDisposable
    {
        public void Dispose() => Unguarded.Value = false;
    }

    [System.Text.RegularExpressions.GeneratedRegex(@"@?\$?""(?:[^""\\]|\\.)*""")]
    private static partial System.Text.RegularExpressions.Regex StringLiteral();

    public string Environment => environment;

    public ProjectSource Project => project;

    public RepositoryConfig Config => config;

    /// <summary>This resolver as another environment sees configuration; one per environment, so each remembers its
    /// own results.</summary>
    public ValueResolver For(string otherEnvironment)
    {
        if (otherEnvironment == environment)
        {
            return this;
        }

        if (!_shared.ByEnvironment.TryGetValue(otherEnvironment, out var other))
        {
            other = new ValueResolver(project, symbols, config, otherEnvironment) { _shared = _shared };
            _shared.ByEnvironment[otherEnvironment] = other;
        }

        return other;
    }

    public ResolvedValue Resolve(ExpressionSyntax expression, CallSiteEvaluator.Env env)
    {
        _guarded = !Unguarded.Value;
        _steps = 0;
        return Resolve(expression, env, 0);
    }

    private ResolvedValue Resolve(ExpressionSyntax expression, CallSiteEvaluator.Env env, int depth)
    {
        _shared.Calls++;
        _shared.Cancellation.ThrowIfCancellationRequested();
        if (depth > MaxDepth)
        {
            _truncations++;
            return ResolvedValue.Hole(Label(expression));
        }

        if (_guarded && ++_steps > MaxSteps)
        {
            _truncations++;
            return new ResolvedValue([new HolePart(Label(expression), null, $"more than {MaxSteps} resolution steps")]);
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
            {
                // (c) Left to right: once the base names nothing, the rest is not resolved.
                var parts = new List<ResolvedValue>();
                foreach (var content in interpolated.Contents)
                {
                    var stopped = _guarded && parts.Count > 0 && parts[0].HasUnresolvableBase;
                    parts.Add(content switch
                    {
                        InterpolatedStringTextSyntax text => ResolvedValue.Text(text.TextToken.ValueText),
                        InterpolationSyntax hole when stopped => Unevaluated(hole.Expression),
                        InterpolationSyntax hole => Resolve(hole.Expression, env, depth + 1),
                        _ => new ResolvedValue([]),
                    });
                }

                return ResolvedValue.Join(parts);
            }

            case BinaryExpressionSyntax binary when binary.IsKind(SyntaxKind.AddExpression):
            {
                // (c) The left operand first; an unresolvable base ends the resolution.
                var left = Resolve(binary.Left, env, depth + 1);
                return left.Concat(_guarded && left.HasUnresolvableBase ? Unevaluated(binary.Right) : Resolve(binary.Right, env, depth + 1));
            }

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
                    ? first.Concat(_guarded && first.HasUnresolvableBase ? Unevaluated(arguments[1].Expression) : Resolve(arguments[1].Expression, env, depth + 1))
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

        // (d) The receiver's written type, where there is one: only that type's member (and its relatives').
        return FromAssignments(memberName, site, depth, _guarded ? SymbolIndex.ReceiverType(receiver) : null);
    }

    /// <summary>A member assigned in one place (a field set in a
    /// constructor, a property set in an object initializer) resolves to
    /// what it is assigned; several differing assignments do not.</summary>
    private ResolvedValue FromAssignments(string name, ExpressionSyntax site, int depth, string? owner = null)
    {
        var all = symbols.AssignmentsTo(project, name, owner is null ? null : RelatedTypes(owner));
        var excluded = all.FirstOrDefault(a => a.Value.Span.Contains(site.Span) && a.Value.SyntaxTree == site.SyntaxTree);
        var assigned = excluded is null ? all : all.Where(a => a != excluded).ToList();
        if (assigned.Count == 0)
        {
            return ResolvedValue.Hole(name);
        }

        if (!_guarded)
        {
            return Weigh(name, assigned.Select(a => Resolve(a.Value, CallSiteEvaluator.Empty, depth + 1)).ToList(), keepRepeats: true);
        }

        // (b) Too many to weigh: unresolved, with the reason.
        if (assigned.Count > MaxAssignments)
        {
            return new ResolvedValue([new HolePart(name, null, $"{name} is assigned in {assigned.Count} places; more than {MaxAssignments} are not weighed")]);
        }

        // (a) Remembered, and never resolved twice at once.
        var key = (name, owner, excluded?.Value);
        if (_memo.TryGetValue(key, out var known))
        {
            return known;
        }

        var guard = (name, owner);
        var at = _resolving.IndexOf(guard);
        if (at >= 0)
        {
            _repeatFloor = Math.Min(_repeatFloor, at);
            return new ResolvedValue([new HolePart(name, null, $"{name} is read while it is being resolved", Repeat: true)]);
        }

        var position = _resolving.Count;
        _resolving.Add(guard);
        var outerFloor = _repeatFloor;
        var truncations = _truncations;
        _repeatFloor = int.MaxValue;
        try
        {
            var result = Weigh(name, assigned.Select(a => Resolve(a.Value, CallSiteEvaluator.Empty, depth + 1)).ToList(), keepRepeats: false);
            // Kept only when it does not depend on where it was asked from: no repeat of a name further up, and
            // nothing cut short by the depth or step limit.
            if (_repeatFloor >= position && _truncations == truncations)
            {
                _memo[key] = result;
            }

            return result;
        }
        finally
        {
            _resolving.RemoveAt(position);
            _repeatFloor = Math.Min(outerFloor, _repeatFloor);
        }
    }

    /// <summary>The value of a name from the values of its assignments: the one value they agree on, or a hole. A
    /// re-read of the name itself (a copy between members of that name) adds no value of its own, and is left out.</summary>
    private static ResolvedValue Weigh(string name, IReadOnlyList<ResolvedValue> values, bool keepRepeats)
    {
        var own = keepRepeats ? values : values.Where(v => !v.IsRepeat).ToList();
        if (own.Count == 0)
        {
            return new ResolvedValue([new HolePart(name, null, $"{name} is only copied from members of the same name")]);
        }

        var distinct = own.Select(v => v.TextValue ?? v.WholeConfig?.KeyPath ?? v.Placeholder ?? "\u0000" + name).Distinct().Count();
        return distinct == 1 ? own[0] : ResolvedValue.Hole(name) with { Keys = own.SelectMany(v => v.Keys).Distinct().ToList() };
    }

    /// <summary>(c) What follows an unresolvable base: literal text as written, anything else a hole, not resolved.</summary>
    private static ResolvedValue Unevaluated(ExpressionSyntax expression) =>
        expression is LiteralExpressionSyntax literal && literal.IsKind(SyntaxKind.StringLiteralExpression)
            ? ResolvedValue.Text(literal.Token.ValueText)
            : ResolvedValue.Hole(Label(expression));

    /// <summary>(d) A type and the types related to it by inheritance, as the project declares them: its bases and
    /// interfaces, and what derives from it. An assignment through a base or a derived type is the same member.</summary>
    private IReadOnlySet<string> RelatedTypes(string type)
    {
        if (_shared.Related.TryGetValue(type, out var known))
        {
            return known;
        }

        var related = new HashSet<string>(StringComparer.Ordinal) { type };
        var up = new Queue<string>([type]);
        while (up.Count > 0)
        {
            foreach (var declared in project.TypesByName[up.Dequeue()])
            {
                foreach (var baseName in declared.BaseNames.Where(related.Add))
                {
                    up.Enqueue(baseName);
                }
            }
        }

        var down = new Queue<string>([type]);
        var derived = new HashSet<string>(StringComparer.Ordinal) { type };
        while (down.Count > 0)
        {
            var current = down.Dequeue();
            foreach (var declared in project.Types.Where(t => t.BaseNames.Contains(current) && derived.Add(t.Name)))
            {
                related.Add(declared.Name);
                down.Enqueue(declared.Name);
            }
        }

        _shared.Related[type] = related;
        return related;
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
