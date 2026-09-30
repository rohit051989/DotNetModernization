using System.Text.RegularExpressions;
using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.EntryPoints;

/// <summary>Syntax-only helpers shared by the detectors. Values are read as
/// written; nothing is bound (29-STEPS-004-005-INVENTORIES.md Part A2).</summary>
public static partial class SyntaxHelpers
{
    [GeneratedRegex(@"\s+")]
    private static partial Regex Whitespace();

    public static string? RightmostTypeName(TypeSyntax type) => type switch
    {
        AliasQualifiedNameSyntax a => a.Name.Identifier.Text,
        _ => RoslynNameHelpers.RightmostIdentifier(type),
    };

    /// <summary>The enclosing namespace, dotted, outermost first; null for
    /// the global namespace.</summary>
    public static string? NamespaceOf(SyntaxNode node)
    {
        var parts = node.Ancestors()
            .OfType<BaseNamespaceDeclarationSyntax>()
            .Select(n => n.Name.ToString())
            .Reverse()
            .ToList();
        return parts.Count == 0 ? null : string.Join('.', parts);
    }

    /// <summary>Attributes on a declaration, with their simple names —
    /// <c>[Microsoft.AspNetCore.Mvc.HttpGetAttribute]</c> is <c>HttpGet</c>.
    /// Skips <c>return:</c>, <c>assembly:</c> and <c>module:</c> targets.</summary>
    public static IEnumerable<(AttributeSyntax Attribute, string Name)> Attributes(SyntaxList<AttributeListSyntax> lists)
    {
        foreach (var list in lists)
        {
            if (list.Target is { } target && target.Identifier.Text is "return" or "assembly" or "module")
            {
                continue;
            }

            foreach (var attribute in list.Attributes)
            {
                var name = RoslynNameHelpers.AttributeSimpleName(attribute.Name);
                if (name is not null)
                {
                    yield return (attribute, name);
                }
            }
        }
    }

    public static bool HasAttribute(SyntaxList<AttributeListSyntax> lists, string name) =>
        Attributes(lists).Any(a => a.Name == name);

    /// <summary>An attribute exactly as written, in brackets, with runs of
    /// whitespace collapsed so a multi-line attribute reads on one line.</summary>
    public static string AsWritten(AttributeSyntax attribute) => $"[{Collapse(attribute.ToString())}]";

    public static string Collapse(string text) => Whitespace().Replace(text.Trim(), " ");

    /// <summary>A string literal's value, or a concatenation of literals
    /// folded; null for anything that needs evaluating.</summary>
    public static string? StringValue(ExpressionSyntax? expression) => expression switch
    {
        LiteralExpressionSyntax literal when literal.IsKind(SyntaxKind.StringLiteralExpression) => literal.Token.ValueText,
        InterpolatedStringExpressionSyntax interpolated when interpolated.Contents.All(c => c is InterpolatedStringTextSyntax) =>
            string.Concat(interpolated.Contents.Cast<InterpolatedStringTextSyntax>().Select(t => t.TextToken.ValueText)),
        BinaryExpressionSyntax binary when binary.IsKind(SyntaxKind.AddExpression) =>
            StringValue(binary.Left) is { } left && StringValue(binary.Right) is { } right ? left + right : null,
        ParenthesizedExpressionSyntax parenthesized => StringValue(parenthesized.Expression),
        _ => null,
    };

    /// <summary>A string argument of an attribute — the first positional
    /// argument, or the named one. <c>Present</c> is false when the
    /// attribute has no such argument; <c>Value</c> is null when it is not a
    /// literal, and <c>Expression</c> then carries it as written.</summary>
    public static (bool Present, string? Value, string? Expression) AttributeStringArgument(
        AttributeSyntax attribute, params string[] names)
    {
        var arguments = attribute.ArgumentList?.Arguments ?? default;
        foreach (var argument in arguments)
        {
            var named = argument.NameEquals?.Name.Identifier.Text ?? argument.NameColon?.Name.Identifier.Text;
            if (named is not null && names.Any(n => string.Equals(n, named, StringComparison.OrdinalIgnoreCase)))
            {
                return Describe(argument.Expression);
            }
        }

        var positional = arguments.FirstOrDefault(a => a.NameEquals is null && a.NameColon is null);
        return positional is null ? (false, null, null) : Describe(positional.Expression);

        static (bool, string?, string?) Describe(ExpressionSyntax expression) =>
            StringValue(expression) is { } value ? (true, value, null) : (true, null, Collapse(expression.ToString()));
    }

    /// <summary>1-based first and last line of <paramref name="node"/>,
    /// starting at <paramref name="fromPosition"/> when given (to leave out
    /// leading attribute lists).</summary>
    public static (int Start, int End) Lines(SyntaxNode node, int? fromPosition = null)
    {
        var tree = node.SyntaxTree;
        var start = tree.GetLineSpan(new Microsoft.CodeAnalysis.Text.TextSpan(fromPosition ?? node.SpanStart, 0)).StartLinePosition.Line + 1;
        var end = tree.GetLineSpan(node.Span).EndLinePosition.Line + 1;
        return (start, end);
    }

    /// <summary>A member's lines from its modifiers or return type, not its
    /// attributes — where a reader lands to read the handler.</summary>
    public static (int Start, int End) MemberLines(MemberDeclarationSyntax member)
    {
        var first = member.Modifiers.Count > 0
            ? member.Modifiers.First().SpanStart
            : member.ChildNodes().FirstOrDefault(n => n is not AttributeListSyntax)?.SpanStart ?? member.SpanStart;
        return Lines(member, first);
    }

    public static bool HasModifier(MemberDeclarationSyntax member, string modifier) =>
        member.Modifiers.Any(m => m.Text == modifier);

    /// <summary>Method parameter types joined, for a handler identity that
    /// tells overloads apart.</summary>
    public static string ParameterSignature(BaseParameterListSyntax? parameters) =>
        parameters is null
            ? ""
            : string.Join(",", parameters.Parameters.Select(p => p.Type is null ? "" : Collapse(p.Type.ToString())));

    /// <summary>The invoked member's simple name: <c>app.MapGet</c> is
    /// <c>MapGet</c>, <c>MapGet&lt;T&gt;</c> too.</summary>
    public static string? InvokedName(InvocationExpressionSyntax invocation) => invocation.Expression switch
    {
        MemberAccessExpressionSyntax member => member.Name.Identifier.Text,
        MemberBindingExpressionSyntax binding => binding.Name.Identifier.Text,
        SimpleNameSyntax simple => simple.Identifier.Text,
        _ => null,
    };

    /// <summary>The receiver of <c>x.Method(...)</c>, or null.</summary>
    public static ExpressionSyntax? Receiver(InvocationExpressionSyntax invocation) =>
        invocation.Expression is MemberAccessExpressionSyntax member ? member.Expression : null;

    /// <summary>The calls chained after <paramref name="invocation"/>:
    /// <c>app.MapGet(...).RequireAuthorization().WithName("x")</c> yields
    /// RequireAuthorization then WithName.</summary>
    public static IEnumerable<InvocationExpressionSyntax> ChainedCalls(InvocationExpressionSyntax invocation)
    {
        SyntaxNode current = invocation;
        while (current.Parent is MemberAccessExpressionSyntax member
               && member.Expression == current
               && member.Parent is InvocationExpressionSyntax next)
        {
            yield return next;
            current = next;
        }
    }

    /// <summary>The type and member a node sits in. Top-level statements are
    /// <c>Program</c> / <c>&lt;top-level statements&gt;</c>.</summary>
    public static (string Type, string? Namespace, string Member) EnclosingMember(SyntaxNode node)
    {
        var type = node.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault();
        var member = node.Ancestors().FirstOrDefault(a => a is BaseMethodDeclarationSyntax or LocalFunctionStatementSyntax or PropertyDeclarationSyntax);
        var memberName = member switch
        {
            MethodDeclarationSyntax m => m.Identifier.Text,
            ConstructorDeclarationSyntax => ".ctor",
            LocalFunctionStatementSyntax l => l.Identifier.Text,
            PropertyDeclarationSyntax p => p.Identifier.Text,
            _ => type is null ? "<top-level statements>" : "<member>",
        };
        return (type?.Identifier.Text ?? "Program", type is null ? null : NamespaceOf(type), memberName);
    }
}
