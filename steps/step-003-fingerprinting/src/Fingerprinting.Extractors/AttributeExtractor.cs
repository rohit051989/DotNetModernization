using Microsoft.CodeAnalysis.CSharp.Syntax;
using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Level 3 (Roslyn syntax) extraction — application-fingerprinting-v1.md
/// section 6.3: framework-relevant attributes, by simple name as written
/// (never a fabricated fully-qualified name — semantic analysis is off by
/// default per Part A4, and several of these attribute names exist in more
/// than one framework, e.g. <c>HttpGet</c> in both System.Web.Http and
/// Microsoft.AspNetCore.Mvc). Records declaring type and member per section
/// 6.3's own wording ("capture the attribute name, declaring class or
/// method...").
/// </summary>
public sealed class AttributeExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "AttributeExtractor";

    public string Name => ExtractorName;

    private sealed record AttributeRule(string SignalName, string Category);

    private static readonly IReadOnlyDictionary<string, AttributeRule> Rules =
        new Dictionary<string, AttributeRule>(StringComparer.Ordinal)
        {
            ["ServiceContract"] = new("SERVICE_CONTRACT_ATTRIBUTE", SignalCategories.SourceConstruct),
            ["OperationContract"] = new("OPERATION_CONTRACT_ATTRIBUTE", SignalCategories.SourceConstruct),
            ["DataContract"] = new("DATA_CONTRACT_ATTRIBUTE", SignalCategories.SourceConstruct),
            ["HttpGet"] = new("HTTP_GET_ATTRIBUTE", SignalCategories.SourceConstruct),
            ["HttpPost"] = new("HTTP_POST_ATTRIBUTE", SignalCategories.SourceConstruct),
            ["HttpPut"] = new("HTTP_PUT_ATTRIBUTE", SignalCategories.SourceConstruct),
            ["HttpDelete"] = new("HTTP_DELETE_ATTRIBUTE", SignalCategories.SourceConstruct),
            ["Route"] = new("ROUTE_ATTRIBUTE", SignalCategories.SourceConstruct),
            ["RoutePrefix"] = new("ROUTE_PREFIX_ATTRIBUTE", SignalCategories.SourceConstruct),
            ["ApiController"] = new("API_CONTROLLER_ATTRIBUTE", SignalCategories.SourceConstruct),
            ["WebMethod"] = new("WEB_METHOD_ATTRIBUTE", SignalCategories.SourceConstruct),
            ["FunctionName"] = new("FUNCTION_NAME_ATTRIBUTE", SignalCategories.SourceConstruct),
            // Test attributes get TESTING_INDICATOR, not SOURCE_CONSTRUCT —
            // application-fingerprinting-v1.md section 16 calls out "Test
            // attributes" as their own Test Fingerprint concern.
            ["TestMethod"] = new("TEST_METHOD_ATTRIBUTE", SignalCategories.TestingIndicator),
            ["Fact"] = new("FACT_ATTRIBUTE", SignalCategories.TestingIndicator),
            ["Test"] = new("TEST_ATTRIBUTE", SignalCategories.TestingIndicator),
            ["TestFixture"] = new("TEST_FIXTURE_ATTRIBUTE", SignalCategories.TestingIndicator),
        };

    public bool CanProcess(ProjectContext context) => Directory.Exists(context.ProjectDirectory);

    public async Task<ExtractorResult> ExtractAsync(ProjectContext context, CancellationToken cancellationToken)
    {
        var accumulator = new SignalAccumulator();
        var warnings = new List<Warning>();
        var scan = SourceFileScanner.EnumerateCSharpFiles(context.RepositoryRoot, context.ProjectDirectory, cancellationToken);

        foreach (var file in scan.Files)
        {
            cancellationToken.ThrowIfCancellationRequested();

            Microsoft.CodeAnalysis.SyntaxNode root;
            try
            {
                root = await SourceFileScanner.ParseAsync(file.AbsolutePath, cancellationToken);
            }
            catch (IOException)
            {
                continue;
            }

            foreach (var attribute in root.DescendantNodes().OfType<AttributeSyntax>())
            {
                var simpleName = RoslynNameHelpers.AttributeSimpleName(attribute.Name);
                if (simpleName is null || !Rules.TryGetValue(simpleName, out var rule))
                {
                    continue;
                }

                var lineSpan = attribute.GetLocation().GetLineSpan();
                accumulator.Add(
                    rule.SignalName,
                    rule.Category,
                    SignalTypes.Attribute,
                    simpleName,
                    EvidenceSourceTypes.SourceCode,
                    file.RelativePath,
                    ExtractorName,
                    evidence: new Evidence
                    {
                        LineStart = lineSpan.StartLinePosition.Line + 1,
                        LineEnd = lineSpan.EndLinePosition.Line + 1,
                        DeclaringType = FindDeclaringType(attribute),
                        Member = FindDeclaringMember(attribute),
                        SnippetHash = Hashing.Sha256Hex(attribute.ToString()),
                    });
            }
        }

        if (scan.Truncated)
        {
            warnings.Add(new Warning
            {
                Code = WarningCodes.SourceFileCapExceeded,
                Message = $"Project has more than {SourceFileScanner.MaxFilesPerProject} source files; " +
                          "attribute analysis stopped at the cap.",
                Severity = WarningSeverities.Warning,
            });
        }

        return new ExtractorResult { Signals = accumulator.Build(), Warnings = warnings };
    }

    private static string? FindDeclaringType(AttributeSyntax attribute) =>
        attribute.FirstAncestorOrSelf<TypeDeclarationSyntax>()?.Identifier.Text;

    /// <summary>The method or property the attribute decorates, or null when
    /// the attribute is on the type itself (e.g. [ApiController],
    /// [ServiceContract], [TestFixture]).</summary>
    private static string? FindDeclaringMember(AttributeSyntax attribute)
    {
        var target = attribute.FirstAncestorOrSelf<AttributeListSyntax>()?.Parent;
        return target switch
        {
            MethodDeclarationSyntax m => m.Identifier.Text,
            PropertyDeclarationSyntax p => p.Identifier.Text,
            _ => null,
        };
    }
}
