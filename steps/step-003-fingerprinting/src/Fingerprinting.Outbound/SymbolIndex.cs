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
/// each host), and, per project, the assignments to each member.
/// </summary>
public sealed class SymbolIndex
{
    private readonly Dictionary<string, string> _constants = new(StringComparer.Ordinal);
    private readonly HashSet<string> _ambiguous = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> _optionsSections = new(StringComparer.Ordinal);
    private readonly Dictionary<string, List<(ProjectSource Project, ExpressionSyntax Value)>> _assignments = new(StringComparer.Ordinal);

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

                                    index.AddAssignment(project, variable.Identifier.Text, value);
                                }
                            }

                            break;

                        case PropertyDeclarationSyntax { Initializer.Value: { } initial } property:
                            index.AddAssignment(project, property.Identifier.Text, initial);
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
                                index.AddAssignment(project, name, assignment.Right);
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

    private void AddAssignment(ProjectSource project, string name, ExpressionSyntax value)
    {
        if (!_assignments.TryGetValue(name, out var list))
        {
            _assignments[name] = list = [];
        }

        list.Add((project, value));
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
        IdentifierNameSyntax id => ConstantNamed(id.Identifier.Text),
        MemberAccessExpressionSyntax { Expression: NameSyntax owner } member =>
            ConstantNamed($"{SyntaxHelpers.RightmostTypeName(owner)}.{member.Name.Identifier.Text}"),
        _ => null,
    };

    public string? OptionsSection(string typeName) => _optionsSections.GetValueOrDefault(typeName);

    public IReadOnlyList<ExpressionSyntax> AssignmentsTo(ProjectSource project, string member) =>
        _assignments.TryGetValue(member, out var list) ? list.Where(x => x.Project == project).Select(x => x.Value).ToList() : [];
}
