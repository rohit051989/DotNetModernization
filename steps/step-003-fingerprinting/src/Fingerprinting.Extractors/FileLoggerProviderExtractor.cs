using Fingerprinting.Domain;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Extractors;

/// <summary>
/// Registry 1.12.0: a custom logging provider that writes files — a class implementing <c>ILoggerProvider</c> in a
/// source file that writes to the file system (<c>File.AppendAllText</c>, <c>StreamWriter</c>, <c>FileStream</c> ...),
/// such as AccountsApi's <c>FileLoggerProvider</c>. Like a Serilog file sink (SERILOG_FILE_SINK_CONFIG), it writes
/// logs where a container keeps nothing, instead of standard output. <c>CUSTOM_FILE_LOGGER_PROVIDER</c>'s value is the
/// class name, located at its declaration. Syntax only.
/// </summary>
public sealed class FileLoggerProviderExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "FileLoggerProviderExtractor";
    public const string CustomFileLoggerProvider = "CUSTOM_FILE_LOGGER_PROVIDER";

    private static readonly HashSet<string> FileWrites = new(StringComparer.Ordinal)
    {
        "AppendAllText", "AppendAllLines", "AppendAllTextAsync", "AppendAllLinesAsync", "AppendText",
        "WriteAllText", "WriteAllLines", "WriteAllTextAsync", "WriteAllLinesAsync", "WriteAllBytes", "Create", "CreateText", "Open", "OpenWrite",
    };

    public string Name => ExtractorName;

    public bool CanProcess(ProjectContext context) => Directory.Exists(context.ProjectDirectory);

    public async Task<ExtractorResult> ExtractAsync(ProjectContext context, CancellationToken cancellationToken)
    {
        var accumulator = new SignalAccumulator();
        var scan = SourceFileScanner.EnumerateCSharpFiles(context.RepositoryRoot, context.ProjectDirectory, cancellationToken);
        foreach (var file in scan.Files)
        {
            cancellationToken.ThrowIfCancellationRequested();
            SyntaxNode root;
            try
            {
                root = await SourceFileScanner.ParseAsync(file.AbsolutePath, cancellationToken);
            }
            catch (IOException)
            {
                continue;
            }

            var providers = root.DescendantNodes().OfType<ClassDeclarationSyntax>()
                .Where(c => c.BaseList?.Types.Any(t => SyntaxHelpers.RightmostTypeName(t.Type) == "ILoggerProvider") == true)
                .ToList();
            if (providers.Count == 0 || !WritesFiles(root))
            {
                continue;
            }

            foreach (var provider in providers)
            {
                var line = provider.Identifier.GetLocation().GetLineSpan().StartLinePosition.Line + 1;
                accumulator.Add(CustomFileLoggerProvider, SignalCategories.SourceConstruct, SignalTypes.BaseClass,
                    provider.Identifier.Text, EvidenceSourceTypes.SourceCode, file.RelativePath, ExtractorName,
                    evidence: new Evidence { LineStart = line, LineEnd = line, DeclaringType = provider.Identifier.Text });
            }
        }

        return new ExtractorResult { Signals = accumulator.Build(), Warnings = [] };
    }

    /// <summary>A file-system write anywhere in the file: <c>File.X(...)</c> for a writing X, or a
    /// <c>StreamWriter</c> / <c>FileStream</c> created.</summary>
    private static bool WritesFiles(SyntaxNode root) =>
        root.DescendantNodes().Any(n => n switch
        {
            InvocationExpressionSyntax { Expression: MemberAccessExpressionSyntax access }
                when access.Expression is IdentifierNameSyntax { Identifier.Text: "File" } or MemberAccessExpressionSyntax { Name.Identifier.Text: "File" } =>
                FileWrites.Contains(access.Name.Identifier.Text),
            ObjectCreationExpressionSyntax creation => SyntaxHelpers.RightmostTypeName(creation.Type) is "StreamWriter" or "FileStream",
            _ => false,
        });
}
