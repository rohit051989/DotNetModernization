using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Extractors;

/// <summary>
/// Syntax-only name matching shared by AttributeExtractor, InheritanceExtractor
/// and EntryPointExtractor. No semantic binding (Part A4) — matches on the
/// rightmost identifier as written, which is why e.g. a user-defined
/// "Controller" base class is indistinguishable from
/// System.Web.Mvc.Controller. Accepted precision loss per Part A4.
/// </summary>
internal static class RoslynNameHelpers
{
    /// <summary>The rightmost identifier of a (possibly qualified, possibly
    /// generic) type or attribute name — "System.Web.Mvc.Controller" and
    /// "Controller" both yield "Controller".</summary>
    public static string? RightmostIdentifier(TypeSyntax type) => type switch
    {
        QualifiedNameSyntax q => q.Right.Identifier.Text,
        SimpleNameSyntax s => s.Identifier.Text,
        _ => null,
    };

    /// <summary>Same as <see cref="RightmostIdentifier(TypeSyntax)"/> but for
    /// an attribute's <c>NameSyntax</c>, with the "Attribute" suffix stripped
    /// when present — "[ServiceContract]" and "[ServiceContractAttribute]"
    /// both yield "ServiceContract".</summary>
    public static string? AttributeSimpleName(NameSyntax name)
    {
        var identifier = name switch
        {
            QualifiedNameSyntax q => q.Right.Identifier.Text,
            SimpleNameSyntax s => s.Identifier.Text,
            _ => null,
        };

        if (identifier is null)
        {
            return null;
        }

        return identifier.EndsWith("Attribute", StringComparison.Ordinal)
            ? identifier[..^"Attribute".Length]
            : identifier;
    }

    /// <summary>True if <paramref name="invocation"/> is a call
    /// <c>typeSimpleName.methodName(...)</c> — e.g. "WebApplication" /
    /// "CreateBuilder" matches <c>WebApplication.CreateBuilder(args)</c>.
    /// Only matches the simple (unqualified) receiver name, consistent with
    /// syntax-only analysis.</summary>
    public static bool IsStaticCallOn(InvocationExpressionSyntax invocation, string typeSimpleName, string methodName)
    {
        return invocation.Expression is MemberAccessExpressionSyntax
        {
            Name.Identifier.Text: var calledMethod,
            Expression: IdentifierNameSyntax { Identifier.Text: var receiver },
        }
        && calledMethod == methodName
        && receiver == typeSimpleName;
    }

    /// <summary>True if <paramref name="invocation"/> calls a member named
    /// <paramref name="methodName"/>, regardless of receiver — used for
    /// extension-method calls like <c>services.AddHostedService&lt;T&gt;()</c>
    /// where the receiver's static type cannot be recovered without semantic
    /// binding.</summary>
    public static bool IsMethodCallNamed(InvocationExpressionSyntax invocation, string methodName) =>
        invocation.Expression switch
        {
            MemberAccessExpressionSyntax { Name: var name } => name.Identifier.Text == methodName,
            SimpleNameSyntax { Identifier.Text: var name } => name == methodName,
            _ => false,
        };
}
