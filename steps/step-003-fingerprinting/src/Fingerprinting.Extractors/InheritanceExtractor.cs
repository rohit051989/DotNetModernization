using Microsoft.CodeAnalysis.CSharp.Syntax;
using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Level 3 (Roslyn syntax) extraction — application-fingerprinting-v1.md
/// section 6.2: base classes and implemented interfaces. Roslyn's syntax
/// tree does not distinguish a base class from an implemented interface in a
/// type's base list without semantic binding, so both use signal type
/// BASE_CLASS — the only construct SignalTypes offers for "appears in a base
/// list" (Part A4 keeps semantic analysis off by default).
/// </summary>
public sealed class InheritanceExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "InheritanceExtractor";

    public string Name => ExtractorName;

    private static readonly IReadOnlyDictionary<string, string> Rules =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["Page"] = "PAGE_BASE_CLASS",
            ["UserControl"] = "USER_CONTROL_BASE_CLASS",
            ["Controller"] = "CONTROLLER_BASE_CLASS",
            ["ApiController"] = "API_CONTROLLER_BASE_CLASS",
            ["ControllerBase"] = "CONTROLLER_BASE_BASE_CLASS",
            ["ServiceBase"] = "SERVICE_BASE_BASE_CLASS",
            ["BackgroundService"] = "BACKGROUND_SERVICE_BASE_CLASS",
            ["IHostedService"] = "IHOSTED_SERVICE_BASE_CLASS",
            ["DbContext"] = "DB_CONTEXT_BASE_CLASS",
            ["MasterPage"] = "MASTER_PAGE_BASE_CLASS",
            ["IHttpHandler"] = "IHTTP_HANDLER_BASE_CLASS",
            ["IHttpModule"] = "IHTTP_MODULE_BASE_CLASS",
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

            foreach (var typeDecl in root.DescendantNodes().OfType<TypeDeclarationSyntax>())
            {
                if (typeDecl.BaseList is null)
                {
                    continue;
                }

                foreach (var baseType in typeDecl.BaseList.Types)
                {
                    var simpleName = RoslynNameHelpers.RightmostIdentifier(baseType.Type);
                    if (simpleName is null || !Rules.TryGetValue(simpleName, out var signalName))
                    {
                        continue;
                    }

                    var lineSpan = baseType.GetLocation().GetLineSpan();
                    accumulator.Add(
                        signalName,
                        SignalCategories.SourceConstruct,
                        SignalTypes.BaseClass,
                        simpleName,
                        EvidenceSourceTypes.SourceCode,
                        file.RelativePath,
                        ExtractorName,
                        evidence: new Evidence
                        {
                            LineStart = lineSpan.StartLinePosition.Line + 1,
                            LineEnd = lineSpan.EndLinePosition.Line + 1,
                            DeclaringType = typeDecl.Identifier.Text,
                            SnippetHash = Hashing.Sha256Hex(baseType.ToString()),
                        });
                }
            }
        }

        if (scan.Truncated)
        {
            warnings.Add(new Warning
            {
                Code = WarningCodes.SourceFileCapExceeded,
                Message = $"Project has more than {SourceFileScanner.MaxFilesPerProject} source files; " +
                          "inheritance analysis stopped at the cap.",
                Severity = WarningSeverities.Warning,
            });
        }

        return new ExtractorResult { Signals = accumulator.Build(), Warnings = warnings };
    }
}
