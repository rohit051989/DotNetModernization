using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Analysis;

/// <summary>
/// Syntax-only evaluation of the values a hosting or client call is built
/// from — a WCF binding and its security, an address — including through a
/// generic helper (<c>Build&lt;TService, TContract&gt;(...)</c>): the helper's
/// call sites bind its type arguments and literal arguments, so each call
/// resolves on its own. Shared by step 4 (service hosts) and step 5 (clients).
/// </summary>
public static class CallSiteEvaluator
{
    public sealed record Env(
        IReadOnlyDictionary<string, string> TypeArguments,
        IReadOnlyDictionary<string, ExpressionSyntax> Arguments,
        string? Via);

    public static readonly Env Empty = new(new Dictionary<string, string>(), new Dictionary<string, ExpressionSyntax>(), null);

    // ---------- evaluation ----------

    public sealed record BindingValue(string Binding, string? Mode, string? Transport, string? Message);

    public static BindingValue EvaluateBinding(ExpressionSyntax expression, SyntaxNode scope, Env env, int depth)
    {
        if (depth > 4)
        {
            return new BindingValue("unknown", null, null, null);
        }

        switch (expression)
        {
            case IdentifierNameSyntax identifier when env.Arguments.TryGetValue(identifier.Identifier.Text, out var argument):
                return EvaluateBinding(argument, argument, Empty, depth + 1);

            case IdentifierNameSyntax identifier:
            {
                var declarator = scope.DescendantNodes().OfType<VariableDeclaratorSyntax>()
                    .LastOrDefault(v => v.Identifier.Text == identifier.Identifier.Text && v.Initializer is not null && v.SpanStart < expression.SpanStart);
                if (declarator is null)
                {
                    return new BindingValue("unknown", null, null, null);
                }

                var value = EvaluateBinding(declarator.Initializer!.Value, scope, env, depth + 1);
                return ApplyAssignments(value, identifier.Identifier.Text, scope, env);
            }

            case BaseObjectCreationExpressionSyntax creation:
            {
                var typeName = creation is ObjectCreationExpressionSyntax explicitType ? SyntaxHelpers.RightmostTypeName(explicitType.Type) : null;
                var binding = typeName is not null && WcfSecurity.BindingNames.TryGetValue(typeName, out var configName) ? configName : typeName ?? "unknown";
                string? mode = null, transport = null, message = null;

                if (creation.ArgumentList?.Arguments.FirstOrDefault()?.Expression is { } first
                    && EnumName(first, env) is { } modeName)
                {
                    mode = modeName;
                }

                if (creation.Initializer is not null)
                {
                    ReadInitializer(creation.Initializer, "", env, ref mode, ref transport, ref message);
                }

                return new BindingValue(binding, mode, transport, message);
            }

            default:
                return new BindingValue("unknown", null, null, null);
        }
    }

    /// <summary><c>binding.Security.Mode = X;</c> and friends, written as
    /// statements after the binding is created.</summary>
    public static BindingValue ApplyAssignments(BindingValue value, string variable, SyntaxNode scope, Env env)
    {
        var (mode, transport, message) = (value.Mode, value.Transport, value.Message);
        foreach (var assignment in scope.DescendantNodes().OfType<AssignmentExpressionSyntax>())
        {
            var target = assignment.Left.ToString().Replace(" ", "");
            if (!target.StartsWith(variable + ".Security", StringComparison.Ordinal))
            {
                continue;
            }

            Assign(target[(variable.Length + ".Security".Length)..], assignment.Right, env, ref mode, ref transport, ref message);
        }

        return value with { Mode = mode, Transport = transport, Message = message };
    }

    /// <summary><c>new NetTcpBinding { Security = { Mode = ..., Transport = { ClientCredentialType = ... } } }</c>.</summary>
    public static void ReadInitializer(InitializerExpressionSyntax initializer, string path, Env env, ref string? mode, ref string? transport, ref string? message)
    {
        foreach (var assignment in initializer.Expressions.OfType<AssignmentExpressionSyntax>())
        {
            var name = assignment.Left is IdentifierNameSyntax id ? id.Identifier.Text : assignment.Left.ToString();
            var nested = $"{path}.{name}";
            if (assignment.Right is InitializerExpressionSyntax inner)
            {
                ReadInitializer(inner, nested, env, ref mode, ref transport, ref message);
            }
            else if (nested.StartsWith(".Security", StringComparison.Ordinal))
            {
                Assign(nested[".Security".Length..], assignment.Right, env, ref mode, ref transport, ref message);
            }
        }
    }

    public static void Assign(string member, ExpressionSyntax value, Env env, ref string? mode, ref string? transport, ref string? message)
    {
        switch (member)
        {
            case ".Mode":
                mode = EnumName(value, env) ?? mode;
                break;
            case ".Transport.ClientCredentialType":
                transport = EnumName(value, env) ?? transport;
                break;
            case ".Message.ClientCredentialType":
                message = EnumName(value, env) ?? message;
                break;
        }
    }

    /// <summary><c>SecurityMode.Transport</c> → <c>Transport</c>; a
    /// conditional on a bound boolean argument picks its branch; an unbound
    /// one yields both, <c>Certificate|None</c>.</summary>
    public static string? EnumName(ExpressionSyntax expression, Env env) => expression switch
    {
        MemberAccessExpressionSyntax member => member.Name.Identifier.Text,
        ParenthesizedExpressionSyntax parenthesized => EnumName(parenthesized.Expression, env),
        IdentifierNameSyntax identifier when env.Arguments.TryGetValue(identifier.Identifier.Text, out var argument) => EnumName(argument, Empty),
        ConditionalExpressionSyntax conditional => Truth(conditional.Condition, env) switch
        {
            true => EnumName(conditional.WhenTrue, env),
            false => EnumName(conditional.WhenFalse, env),
            null => EnumName(conditional.WhenTrue, env) is { } a && EnumName(conditional.WhenFalse, env) is { } b ? $"{a}|{b}" : null,
        },
        _ => null,
    };

    public static bool? Truth(ExpressionSyntax condition, Env env) => condition switch
    {
        LiteralExpressionSyntax literal when literal.IsKind(SyntaxKind.TrueLiteralExpression) => true,
        LiteralExpressionSyntax literal when literal.IsKind(SyntaxKind.FalseLiteralExpression) => false,
        IdentifierNameSyntax identifier when env.Arguments.TryGetValue(identifier.Identifier.Text, out var argument) => Truth(argument, Empty),
        PrefixUnaryExpressionSyntax { OperatorToken.Text: "!" } not => Truth(not.Operand, env) is { } value ? !value : null,
        _ => null,
    };

    /// <summary>An address as written, with bound literal arguments
    /// substituted into an interpolated string and the rest left as
    /// <c>{hole}</c>.</summary>
    public static string? EvaluateAddress(ExpressionSyntax expression, SyntaxNode scope, Env env)
    {
        switch (expression)
        {
            case IdentifierNameSyntax identifier when env.Arguments.TryGetValue(identifier.Identifier.Text, out var argument):
                return SyntaxHelpers.StringValue(argument) ?? SyntaxHelpers.Collapse(argument.ToString());
            case IdentifierNameSyntax identifier:
                var declarator = scope.DescendantNodes().OfType<VariableDeclaratorSyntax>()
                    .LastOrDefault(v => v.Identifier.Text == identifier.Identifier.Text && v.Initializer is not null);
                return declarator is null ? identifier.Identifier.Text : EvaluateAddress(declarator.Initializer!.Value, scope, env);
            case ObjectCreationExpressionSyntax { ArgumentList.Arguments.Count: > 0 } creation
                when SyntaxHelpers.RightmostTypeName(creation.Type) is "Uri" or "EndpointAddress":
                return EvaluateAddress(creation.ArgumentList.Arguments[0].Expression, scope, env);
            case InterpolatedStringExpressionSyntax interpolated:
                return string.Concat(interpolated.Contents.Select(c => c switch
                {
                    InterpolatedStringTextSyntax text => text.TextToken.ValueText,
                    InterpolationSyntax { Expression: IdentifierNameSyntax hole } when env.Arguments.TryGetValue(hole.Identifier.Text, out var bound)
                        && SyntaxHelpers.StringValue(bound) is { } literal => literal,
                    InterpolationSyntax hole => $"{{{SyntaxHelpers.Collapse(hole.Expression.ToString())}}}",
                    _ => "",
                }));
            default:
                return SyntaxHelpers.StringValue(expression) ?? SyntaxHelpers.Collapse(expression.ToString());
        }
    }

    public static string? Bound(string? typeName, Env env) =>
        typeName is not null && env.TypeArguments.TryGetValue(typeName, out var bound) ? bound : typeName;

    // ---------- call sites and context ----------

    /// <summary>Calls to <paramref name="method"/> anywhere in the project,
    /// each with its type and value arguments bound to the method's
    /// parameters.</summary>
    public static List<(ParsedFile File, InvocationExpressionSyntax Call, Env Env)> CallSites(ProjectSource project, MethodDeclarationSyntax method)
    {
        var name = method.Identifier.Text;
        var typeParameters = method.TypeParameterList?.Parameters.Select(p => p.Identifier.Text).ToList() ?? [];
        var parameters = method.ParameterList.Parameters.Select(p => p.Identifier.Text).ToList();
        var sites = new List<(ParsedFile, InvocationExpressionSyntax, Env)>();

        foreach (var file in project.Files)
        {
            foreach (var call in file.Root.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var callee = call.Expression switch
                {
                    GenericNameSyntax g => g,
                    MemberAccessExpressionSyntax { Name: GenericNameSyntax g } => g,
                    _ => (SimpleNameSyntax?)(call.Expression as IdentifierNameSyntax ?? (call.Expression as MemberAccessExpressionSyntax)?.Name as IdentifierNameSyntax),
                };
                if (callee?.Identifier.Text != name || call.Ancestors().Contains(method))
                {
                    continue;
                }

                var typeArguments = new Dictionary<string, string>(StringComparer.Ordinal);
                if (callee is GenericNameSyntax genericCallee)
                {
                    if (genericCallee.TypeArgumentList.Arguments.Count != typeParameters.Count)
                    {
                        continue;
                    }

                    for (var i = 0; i < typeParameters.Count; i++)
                    {
                        typeArguments[typeParameters[i]] = SyntaxHelpers.RightmostTypeName(genericCallee.TypeArgumentList.Arguments[i])
                                                           ?? genericCallee.TypeArgumentList.Arguments[i].ToString();
                    }
                }
                else if (typeParameters.Count > 0)
                {
                    continue;
                }

                var arguments = new Dictionary<string, ExpressionSyntax>(StringComparer.Ordinal);
                var position = 0;
                foreach (var argument in call.ArgumentList.Arguments)
                {
                    var parameter = argument.NameColon?.Name.Identifier.Text ?? (position < parameters.Count ? parameters[position] : null);
                    position++;
                    if (parameter is not null)
                    {
                        arguments[parameter] = argument.Expression;
                    }
                }

                sites.Add((file, call, new Env(typeArguments, arguments, Where(file, call))));
            }
        }

        return sites;
    }

    public static SyntaxNode Scope(SyntaxNode node) =>
        node.Ancestors().FirstOrDefault(a => a is BaseMethodDeclarationSyntax or LocalFunctionStatementSyntax)
        ?? node.Ancestors().OfType<CompilationUnitSyntax>().First();

    /// <summary>The <c>if</c> conditions a node sits under, as written.
    /// An endpoint added behind a feature flag is still recorded — it is
    /// configured — with the condition that gates it.</summary>
    public static string? Condition(SyntaxNode node)
    {
        var conditions = new List<string>();
        foreach (var ancestor in node.Ancestors())
        {
            if (ancestor is BaseMethodDeclarationSyntax)
            {
                break;
            }

            if (ancestor is IfStatementSyntax ifStatement)
            {
                var written = SyntaxHelpers.Collapse(ifStatement.Condition.ToString());
                conditions.Add(ifStatement.Statement.Span.Contains(node.Span) ? written : $"!({written})");
            }
        }

        conditions.Reverse();
        return conditions.Count == 0 ? null : string.Join(" && ", conditions);
    }

    public static string Where(ParsedFile file, SyntaxNode node) => $"{file.RelativePath}:{SyntaxHelpers.Lines(node).Start}";
}
