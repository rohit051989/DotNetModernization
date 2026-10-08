using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.TestCoverage;

/// <summary>
/// Part D: does a source file have anything to test? It does when it
/// declares at least one member with a non-trivial body — a method, a
/// constructor, a non-auto property, indexer or event accessor, an operator,
/// or top-level statements.
///
/// A body is <b>trivial</b> when it is empty, or only assigns plain values
/// (<c>Name = name;</c>, <c>this._x = x;</c>) and/or returns one
/// (<c>return _items;</c>, <c>=> _name</c>). A plain value is a name, a
/// member access chain, a literal, <c>this</c>, <c>default</c>, or a
/// parameterless <c>new()</c>. So a DTO, an enum, an interface, a record
/// and a class of auto-properties have no testable logic, and neither does a
/// constructor that only stores its parameters; a guard clause, a
/// calculation or a call is logic.
/// </summary>
public static class TestableLogic
{
    public sealed record DeclaredType(string Name, string QualifiedName, string? Namespace, int LineStart);

    public sealed record FileAnalysis(int TestableMembers, IReadOnlyList<DeclaredType> Types);

    public static FileAnalysis Analyze(SyntaxNode root)
    {
        var count = 0;
        if (root.DescendantNodes().OfType<GlobalStatementSyntax>().Any()) count++;

        foreach (var member in root.DescendantNodes().OfType<MemberDeclarationSyntax>())
        {
            switch (member)
            {
                case BaseMethodDeclarationSyntax method:   // methods, constructors, destructors, operators
                    if (HasLogic(method.Body, method.ExpressionBody) || ConstructorChainsWithArguments(method)) count++;
                    break;
                case BasePropertyDeclarationSyntax property:   // properties, indexers, events
                    if (property is PropertyDeclarationSyntax { ExpressionBody: { } arrow } && !IsPlainValue(arrow.Expression)) count++;
                    else if (property is IndexerDeclarationSyntax { ExpressionBody: { } indexerArrow } && !IsPlainValue(indexerArrow.Expression)) count++;
                    else if (property.AccessorList?.Accessors.Any(a => HasLogic(a.Body, a.ExpressionBody)) == true) count++;
                    break;
            }
        }

        var types = root.DescendantNodes().OfType<BaseTypeDeclarationSyntax>()
            .Select(t => new DeclaredType(t.Identifier.Text, TestDiscovery.QualifiedClassName(t), TestDiscovery.NamespaceOf(t),
                t.GetLocation().GetLineSpan().StartLinePosition.Line + 1))
            .ToList();
        return new FileAnalysis(count, types);
    }

    private static bool ConstructorChainsWithArguments(BaseMethodDeclarationSyntax method) =>
        method is ConstructorDeclarationSyntax { Initializer.ArgumentList.Arguments.Count: > 0 } ctor
        && ctor.Initializer.ArgumentList.Arguments.Any(a => !IsPlainValue(a.Expression));

    private static bool HasLogic(BlockSyntax? body, ArrowExpressionClauseSyntax? arrow)
    {
        if (arrow is not null) return !IsPlainValue(arrow.Expression) && !IsPlainAssignment(arrow.Expression);
        if (body is null) return false;   // abstract, extern, partial, auto accessor
        return body.Statements.Any(statement => !IsTrivialStatement(statement));
    }

    private static bool IsTrivialStatement(StatementSyntax statement) => statement switch
    {
        ExpressionStatementSyntax { Expression: var expression } => IsPlainAssignment(expression),
        ReturnStatementSyntax { Expression: var returned } => returned is null || IsPlainValue(returned),
        EmptyStatementSyntax => true,
        _ => false,
    };

    private static bool IsPlainAssignment(ExpressionSyntax expression) =>
        expression is AssignmentExpressionSyntax { RawKind: (int)SyntaxKind.SimpleAssignmentExpression } assignment
        && IsPlainValue(assignment.Left) && IsPlainValue(assignment.Right);

    private static bool IsPlainValue(ExpressionSyntax expression) => expression switch
    {
        IdentifierNameSyntax or LiteralExpressionSyntax or ThisExpressionSyntax or BaseExpressionSyntax or DefaultExpressionSyntax => true,
        MemberAccessExpressionSyntax access => IsPlainValue(access.Expression),
        ParenthesizedExpressionSyntax parenthesized => IsPlainValue(parenthesized.Expression),
        ImplicitObjectCreationExpressionSyntax { ArgumentList.Arguments.Count: 0, Initializer: null } => true,
        ObjectCreationExpressionSyntax { ArgumentList: null or { Arguments.Count: 0 }, Initializer: null } => true,
        _ => false,
    };
}
