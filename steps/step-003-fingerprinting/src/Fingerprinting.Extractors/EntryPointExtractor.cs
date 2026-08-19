using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Level 3 (Roslyn syntax) extraction — step-3-application-fingerprinting.md
/// section 6.1: entry-point constructs. Distinct from FileIndicatorExtractor,
/// which only records that a file named Program.cs/Startup.cs/Global.asax
/// exists (category FILE_INDICATOR); this extractor confirms a genuine
/// entry-point construct inside source (category ENTRY_POINT) — a Main
/// method, top-level statements, a recognisable Startup/Global.asax
/// convention, or one of the known host-building invocations.
/// </summary>
public sealed class EntryPointExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "EntryPointExtractor";

    public string Name => ExtractorName;

    private const string MainMethodEntryPoint = "MAIN_METHOD_ENTRY_POINT";
    private const string TopLevelStatementsEntryPoint = "TOP_LEVEL_STATEMENTS_ENTRY_POINT";
    private const string StartupClassEntryPoint = "STARTUP_CLASS_ENTRY_POINT";
    private const string GlobalAsaxEntryPoint = "GLOBAL_ASAX_ENTRY_POINT";
    private const string WebApplicationCreateBuilderEntryPoint = "WEB_APPLICATION_CREATE_BUILDER_ENTRY_POINT";
    private const string HostCreateDefaultBuilderEntryPoint = "HOST_CREATE_DEFAULT_BUILDER_ENTRY_POINT";
    private const string WebHostCreateDefaultBuilderEntryPoint = "WEBHOST_CREATE_DEFAULT_BUILDER_ENTRY_POINT";
    private const string ServiceBaseRunEntryPoint = "SERVICEBASE_RUN_ENTRY_POINT";
    private const string AddHostedServiceEntryPoint = "ADD_HOSTED_SERVICE_ENTRY_POINT";

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

            var firstGlobalStatement = root.DescendantNodes().OfType<GlobalStatementSyntax>().FirstOrDefault();
            if (firstGlobalStatement is not null)
            {
                Add(accumulator, TopLevelStatementsEntryPoint, file.RelativePath, declaringType: null, member: null, node: firstGlobalStatement);
            }

            foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
            {
                if (method.Identifier.Text == "Main" && method.Modifiers.Any(m => (SyntaxKind)m.RawKind == SyntaxKind.StaticKeyword))
                {
                    Add(accumulator, MainMethodEntryPoint, file.RelativePath,
                        declaringType: method.FirstAncestorOrSelf<TypeDeclarationSyntax>()?.Identifier.Text, member: "Main", node: method);
                }

                if (method.Identifier.Text == "Application_Start")
                {
                    Add(accumulator, GlobalAsaxEntryPoint, file.RelativePath,
                        declaringType: method.FirstAncestorOrSelf<TypeDeclarationSyntax>()?.Identifier.Text,
                        member: "Application_Start", node: method);
                }
            }

            foreach (var classDecl in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
            {
                if (classDecl.Identifier.Text != "Startup")
                {
                    continue;
                }

                var hasStartupMethod = classDecl.Members.OfType<MethodDeclarationSyntax>()
                    .Any(m => m.Identifier.Text is "Configure" or "ConfigureServices");

                if (hasStartupMethod)
                {
                    Add(accumulator, StartupClassEntryPoint, file.RelativePath, declaringType: "Startup", member: null, node: classDecl);
                }
            }

            foreach (var invocation in root.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var declaringType = invocation.FirstAncestorOrSelf<TypeDeclarationSyntax>()?.Identifier.Text;

                if (RoslynNameHelpers.IsStaticCallOn(invocation, "WebApplication", "CreateBuilder"))
                {
                    Add(accumulator, WebApplicationCreateBuilderEntryPoint, file.RelativePath, declaringType, "CreateBuilder", invocation);
                }
                else if (RoslynNameHelpers.IsStaticCallOn(invocation, "Host", "CreateDefaultBuilder"))
                {
                    Add(accumulator, HostCreateDefaultBuilderEntryPoint, file.RelativePath, declaringType, "CreateDefaultBuilder", invocation);
                }
                else if (RoslynNameHelpers.IsStaticCallOn(invocation, "WebHost", "CreateDefaultBuilder"))
                {
                    Add(accumulator, WebHostCreateDefaultBuilderEntryPoint, file.RelativePath, declaringType, "CreateDefaultBuilder", invocation);
                }
                else if (RoslynNameHelpers.IsStaticCallOn(invocation, "ServiceBase", "Run"))
                {
                    Add(accumulator, ServiceBaseRunEntryPoint, file.RelativePath, declaringType, "Run", invocation);
                }
                else if (RoslynNameHelpers.IsMethodCallNamed(invocation, "AddHostedService"))
                {
                    Add(accumulator, AddHostedServiceEntryPoint, file.RelativePath, declaringType, "AddHostedService", invocation);
                }
            }
        }

        if (scan.Truncated)
        {
            warnings.Add(new Warning
            {
                Code = WarningCodes.SourceFileCapExceeded,
                Message = $"Project has more than {SourceFileScanner.MaxFilesPerProject} source files; " +
                          "entry-point analysis stopped at the cap.",
                Severity = WarningSeverities.Warning,
            });
        }

        return new ExtractorResult { Signals = accumulator.Build(), Warnings = warnings };
    }

    private static void Add(
        SignalAccumulator accumulator,
        string signalName,
        string sourcePath,
        string? declaringType,
        string? member,
        Microsoft.CodeAnalysis.SyntaxNode node)
    {
        var lineSpan = node.GetLocation().GetLineSpan();
        accumulator.Add(
            signalName,
            SignalCategories.EntryPoint,
            SignalTypes.EntryPoint,
            value: null,
            EvidenceSourceTypes.SourceCode,
            sourcePath,
            ExtractorName,
            evidence: new Evidence
            {
                LineStart = lineSpan.StartLinePosition.Line + 1,
                LineEnd = lineSpan.EndLinePosition.Line + 1,
                DeclaringType = declaringType,
                Member = member,
                SnippetHash = Hashing.Sha256Hex(node.ToString()),
            });
    }
}
