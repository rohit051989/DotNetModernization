using Fingerprinting.Analysis;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Outbound;

/// <summary>
/// Repository-wide facts the resolver needs across projects: constants
/// (<c>BaseUrlConfiguration.CONFIG_NAME</c> lives in a shared library), the
/// configuration section each options type is bound to
/// (<c>Configure&lt;BaseUrlConfiguration&gt;(GetSection("baseUrls"))</c> sits in
/// each host), and, per project, the assignments to each member — with the type that owns the member, where the
/// code shows it (rbc-release-5: <c>new Entity { Name = … }</c> assigns Entity's Name, not a DTO's).
/// </summary>
public sealed class SymbolIndex
{
    private readonly Dictionary<string, string> _constants = new(StringComparer.Ordinal);
    private readonly HashSet<string> _ambiguous = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> _optionsSections = new(StringComparer.Ordinal);
    private readonly Dictionary<string, List<Assignment>> _assignments = new(StringComparer.Ordinal);

    /// <summary>One assignment to a member: its value, and the type owning the member when the code shows it — the
    /// type of an object initializer, of the field or property's declaring class, or of a receiver whose declared
    /// type is written. Null when it cannot be seen.</summary>
    public sealed record Assignment(ProjectSource Project, ExpressionSyntax Value, string? Owner);

    public static SymbolIndex Build(IReadOnlyList<ProjectSource> projects)
    {
        var index = new SymbolIndex();
        foreach (var project in projects)
        {
            foreach (var file in project.Files.Where(f => !f.IsGenerated))
            {
                foreach (var node in file.Root.DescendantNodes())
                {
                    switch (node)
                    {
                        case FieldDeclarationSyntax field:
                            foreach (var variable in field.Declaration.Variables)
                            {
                                var owner = field.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault()?.Identifier.Text;
                                if (variable.Initializer?.Value is { } value)
                                {
                                    if (SyntaxHelpers.StringValue(value) is { } literal
                                        && (field.Modifiers.Any(m => m.Text == "const") || field.Modifiers.Any(m => m.Text == "readonly")))
                                    {
                                        index.AddConstant(variable.Identifier.Text, literal);
                                        if (owner is not null)
                                        {
                                            index.AddConstant($"{owner}.{variable.Identifier.Text}", literal);
                                        }
                                    }

                                    index.AddAssignment(project, variable.Identifier.Text, value, owner);
                                }
                            }

                            break;

                        case PropertyDeclarationSyntax { Initializer.Value: { } initial } property:
                            index.AddAssignment(project, property.Identifier.Text, initial,
                                property.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault()?.Identifier.Text);
                            break;

                        case AssignmentExpressionSyntax { RawKind: (int)SyntaxKind.SimpleAssignmentExpression } assignment:
                            var name = assignment.Left switch
                            {
                                IdentifierNameSyntax id => id.Identifier.Text,
                                MemberAccessExpressionSyntax member => member.Name.Identifier.Text,
                                _ => null,
                            };
                            if (name is not null)
                            {
                                index.AddAssignment(project, name, assignment.Right, OwnerOfTarget(assignment));
                            }

                            break;

                        case InvocationExpressionSyntax invocation:
                            index.ReadOptionsBinding(invocation);
                            break;
                    }
                }
            }
        }

        return index;
    }

    /// <summary>Two constants of one name with different values (in
    /// different classes) resolve to neither: nothing is guessed.</summary>
    private void AddConstant(string name, string value)
    {
        if (_constants.TryGetValue(name, out var existing) && existing != value)
        {
            _ambiguous.Add(name);
        }

        _constants[name] = value;
    }

    private string? ConstantNamed(string name) => _ambiguous.Contains(name) ? null : _constants.GetValueOrDefault(name);

    private void AddAssignment(ProjectSource project, string name, ExpressionSyntax value, string? owner)
    {
        if (!_assignments.TryGetValue(name, out var list))
        {
            _assignments[name] = list = [];
        }

        list.Add(new Assignment(project, value, owner));
    }

    /// <summary>The type owning an assignment's target, where the code shows it: <c>new T { X = … }</c> is T's;
    /// <c>x.X = …</c> is the declared type of x (a parameter, field, property or typed local); <c>this.X</c> and a
    /// bare <c>X</c> outside an initializer are the enclosing class's. Null otherwise.</summary>
    private static string? OwnerOfTarget(AssignmentExpressionSyntax assignment)
    {
        if (assignment.Parent is InitializerExpressionSyntax { RawKind: (int)SyntaxKind.ObjectInitializerExpression } initializer)
        {
            return initializer.Parent is ObjectCreationExpressionSyntax creation ? SyntaxHelpers.RightmostTypeName(creation.Type) : null;
        }

        return assignment.Left switch
        {
            IdentifierNameSyntax => assignment.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault()?.Identifier.Text,
            MemberAccessExpressionSyntax { Expression: var receiver } => ReceiverType(receiver),
            _ => null,
        };
    }

    /// <summary>The type a receiver is declared as, where written: <c>this</c>, a parameter, field or property, or
    /// a local declared with its type or initialised with <c>new T(…)</c>. Null for anything else.</summary>
    public static string? ReceiverType(ExpressionSyntax receiver)
    {
        switch (receiver)
        {
            case ThisExpressionSyntax:
                return receiver.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault()?.Identifier.Text;
            case IdentifierNameSyntax identifier:
            {
                var local = CallSiteEvaluator.Scope(identifier).DescendantNodes().OfType<VariableDeclaratorSyntax>()
                    .LastOrDefault(v => v.Identifier.Text == identifier.Identifier.Text && v.SpanStart < identifier.SpanStart);
                if (local?.Parent is VariableDeclarationSyntax declaration)
                {
                    if (!declaration.Type.IsVar)
                    {
                        return TypeName(declaration.Type);
                    }

                    return local.Initializer?.Value is ObjectCreationExpressionSyntax creation ? TypeName(creation.Type) : null;
                }

                return ValueResolver.DeclaredType(identifier) is { } declared ? TypeName(declared) : null;
            }

            default:
                return null;
        }

        static string? TypeName(TypeSyntax type) =>
            SyntaxHelpers.RightmostTypeName(type is NullableTypeSyntax nullable ? nullable.ElementType : type);
    }

    /// <summary><c>Configure&lt;T&gt;(x)</c>, <c>AddOptions&lt;T&gt;().Bind(x)</c>,
    /// <c>BindConfiguration("s")</c> and <c>x.Get&lt;T&gt;()</c>, where x is (or
    /// is a local holding) <c>GetSection(...)</c> / <c>GetRequiredSection(...)</c>.</summary>
    private void ReadOptionsBinding(InvocationExpressionSyntax invocation)
    {
        GenericNameSyntax? generic = invocation.Expression switch
        {
            MemberAccessExpressionSyntax { Name: GenericNameSyntax g } => g,
            GenericNameSyntax g => g,
            _ => null,
        };
        if (generic is null || generic.TypeArgumentList.Arguments.Count != 1)
        {
            return;
        }

        var typeName = SyntaxHelpers.RightmostTypeName(generic.TypeArgumentList.Arguments[0]);
        if (typeName is null)
        {
            return;
        }

        ExpressionSyntax? sectionExpression = generic.Identifier.Text switch
        {
            "Configure" => invocation.ArgumentList.Arguments.FirstOrDefault()?.Expression,
            "Get" => SyntaxHelpers.Receiver(invocation),
            "AddOptions" => SyntaxHelpers.ChainedCalls(invocation)
                .FirstOrDefault(c => SyntaxHelpers.InvokedName(c) is "Bind" or "BindConfiguration")?.ArgumentList.Arguments.FirstOrDefault()?.Expression,
            _ => null,
        };
        if (sectionExpression is null)
        {
            return;
        }

        if (SectionName(sectionExpression, invocation) is { } section)
        {
            _optionsSections.TryAdd(typeName, section);
        }
    }

    private string? SectionName(ExpressionSyntax expression, SyntaxNode site)
    {
        switch (expression)
        {
            case InvocationExpressionSyntax call when SyntaxHelpers.InvokedName(call) is "GetSection" or "GetRequiredSection":
                return Constant(call.ArgumentList.Arguments.FirstOrDefault()?.Expression);
            case IdentifierNameSyntax identifier:
                var scope = CallSiteEvaluator.Scope(site);
                var initializer = scope.DescendantNodes().OfType<VariableDeclaratorSyntax>()
                    .FirstOrDefault(v => v.Identifier.Text == identifier.Identifier.Text)?.Initializer?.Value;
                return initializer is null ? null : SectionName(initializer, site);
            default:
                return Constant(expression);
        }
    }

    /// <summary>A literal, or a constant written as <c>NAME</c> or <c>Type.NAME</c>.</summary>
    public string? Constant(ExpressionSyntax? expression) => expression switch
    {
        null => null,
        _ when SyntaxHelpers.StringValue(expression) is { } literal => literal,
        // An unqualified name is its own type's constant first, as C# scopes it:
        // five clients each declaring ClientName are not ambiguous to themselves.
        IdentifierNameSyntax id => (id.Ancestors().OfType<TypeDeclarationSyntax>().FirstOrDefault() is { } owner
                                       ? ConstantNamed($"{owner.Identifier.Text}.{id.Identifier.Text}") : null)
                                   ?? ConstantNamed(id.Identifier.Text),
        MemberAccessExpressionSyntax { Expression: NameSyntax owner } member =>
            ConstantNamed($"{SyntaxHelpers.RightmostTypeName(owner)}.{member.Name.Identifier.Text}"),
        _ => null,
    };

    public string? OptionsSection(string typeName) => _optionsSections.GetValueOrDefault(typeName);

    /// <summary>The assignments to <paramref name="member"/> in <paramref name="project"/>. With
    /// <paramref name="owners"/> (the type a read is seen to be on, and the types related to it), only assignments
    /// to that member of one of those types, or of a type the code does not show.</summary>
    public IReadOnlyList<Assignment> AssignmentsTo(ProjectSource project, string member, IReadOnlySet<string>? owners = null) =>
        _assignments.TryGetValue(member, out var list)
            ? list.Where(x => x.Project == project && (owners is null || x.Owner is null || owners.Contains(x.Owner))).ToList()
            : [];
}
