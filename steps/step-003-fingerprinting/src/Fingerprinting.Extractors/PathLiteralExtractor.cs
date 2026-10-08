using System.Text.Json;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using Fingerprinting.Domain;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Extractors;

/// <summary>
/// <c>LITERAL</c> signals (21-APPLICATION-FINGERPRINTING.md Part D "Signal
/// types"): Windows drive-letter and UNC path literals in C# source and in
/// configuration values. Each distinct matched value is its own row, and each
/// evidence entry carries <see cref="Evidence.MatchedValue"/>.
///
/// Only string <b>literals</b> are inspected — never comments, identifiers or
/// XML documentation — so a path mentioned in a comment is not a finding.
///
/// Part G: configuration values under a sensitive key or in a connection
/// string are never read (the JSON walker does not even materialise them),
/// and any text shaped like a connection string is skipped whole, wherever it
/// appears. A Windows path inside a connection string therefore produces no
/// row. <c>matchedValue</c> is only the substring the pattern matched, capped
/// at 512 characters.
/// </summary>
public sealed class PathLiteralExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "PathLiteralExtractor";

    public const string WindowsPathLiteral = "WINDOWS_PATH_LITERAL";
    public const string UncPathLiteral = "UNC_PATH_LITERAL";

    /// <summary>Registry 1.7.0: a URL whose host is a single label
    /// (<c>http://appsrv0341/…</c>) — resolves on Windows through NetBIOS or
    /// the DNS suffix search, in a pod only if the cluster's search domains
    /// cover it. The value is the host alone, never the rest of the URL.</summary>
    public const string UnqualifiedHostnameUrl = "UNQUALIFIED_HOSTNAME_URL";

    private const int MaxMatchedValueLength = 512;

    public string Name => ExtractorName;

    // A drive letter not glued to a preceding word ("http:" has letters
    // before the colon), then ':' and a separator, then path characters up to
    // a character no Windows path contains, or to where another drive-letter
    // path starts.
    private static readonly Regex DrivePath = new(
        @"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?:(?![ \t]+[A-Za-z]:[\\/])[^""'<>|*?;,\r\n])*",
        RegexOptions.CultureInvariant);

    // \\server\share[\rest]. The server name must start alphanumeric, which
    // rules out device paths (\\?\C:\, \\.\pipe\x) and regex text like \\d+.
    private static readonly Regex UncPath = new(
        @"(?<!\\)\\\\[A-Za-z0-9][A-Za-z0-9._$-]*\\[A-Za-z0-9._$ -]+(?:\\[^""'<>|*?;,\r\n]*)?",
        RegexOptions.CultureInvariant);

    public bool CanProcess(ProjectContext context) => Directory.Exists(context.ProjectDirectory);

    public async Task<ExtractorResult> ExtractAsync(ProjectContext context, CancellationToken cancellationToken)
    {
        var accumulator = new SignalAccumulator();
        var warnings = new List<Warning>();

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

            ExtractFromSource(root, file.RelativePath, accumulator);
        }

        foreach (var filePath in FileSystemWalk.EnumerateFiles(context.ProjectDirectory, cancellationToken))
        {
            var fileName = Path.GetFileName(filePath);
            var relativePath = FileSystemWalk.ToRepositoryRelativePath(context.RepositoryRoot, filePath);
            try
            {
                if (ConfigFileNames.IsAppSettings(fileName))
                {
                    foreach (var node in JsonConfigWalker.Walk(filePath))
                    {
                        // StringValue is null for anything secret-bearing.
                        if (node.StringValue is { } text)
                        {
                            AddMatches(text, relativePath, EvidenceSourceTypes.Configuration, node.Line, null, null, accumulator);
                        }
                    }
                }
                else if (ConfigFileNames.IsXmlConfig(fileName))
                {
                    ExtractFromXmlConfig(filePath, relativePath, accumulator);
                }
            }
            catch (Exception ex) when (ex is IOException or XmlException or JsonException)
            {
                // ConfigurationExtractor already warns about an unparseable
                // configuration file; saying it twice adds nothing.
            }
        }

        // Web Deploy SetParameters files (registry 1.7.0): a value is read only
        // when neither its name marks it secret nor it is a connection string —
        // the same Part G rule as configuration.
        foreach (var file in context.DeployParameterFiles)
        {
            foreach (var parameter in file.Parameters)
            {
                if (Fingerprinting.Analysis.DeployParameterFiles.Classify(parameter) is "sensitive" or "connection_string")
                {
                    continue;
                }

                AddMatches(parameter.RawValue, file.RelativePath, EvidenceSourceTypes.Configuration, parameter.Line, null, null, accumulator);
            }
        }

        if (scan.Truncated)
        {
            warnings.Add(new Warning
            {
                Code = WarningCodes.SourceFileCapExceeded,
                Message = $"Project has more than {SourceFileScanner.MaxFilesPerProject} source files; " +
                          "path literal analysis stopped at the cap.",
                Severity = WarningSeverities.Warning,
            });
        }

        return new ExtractorResult { Signals = accumulator.Build(), Warnings = warnings };
    }

    // ---- C# ----------------------------------------------------------------

    private static void ExtractFromSource(SyntaxNode root, string relativePath, SignalAccumulator accumulator)
    {
        foreach (var token in root.DescendantTokens())
        {
            var isLiteral = token.IsKind(SyntaxKind.StringLiteralToken)
                || token.IsKind(SyntaxKind.InterpolatedStringTextToken)
                || token.IsKind(SyntaxKind.SingleLineRawStringLiteralToken)
                || token.IsKind(SyntaxKind.MultiLineRawStringLiteralToken)
                || token.IsKind(SyntaxKind.Utf8StringLiteralToken);
            if (!isLiteral || token.Parent is null || IsAssignedToSensitiveName(token.Parent))
            {
                continue;
            }

            var line = token.GetLocation().GetLineSpan().StartLinePosition.Line + 1;
            AddMatches(
                token.ValueText, relativePath, EvidenceSourceTypes.SourceCode, line,
                token.Parent.FirstAncestorOrSelf<BaseTypeDeclarationSyntax>()?.Identifier.Text,
                ApiUsageExtractor.EnclosingMemberName(token.Parent),
                accumulator);
        }
    }

    /// <summary>A literal whose destination is named like a secret
    /// (<c>var connectionString = "…"</c>, <c>Password = "…"</c>) is never
    /// read, matching the configuration rule.</summary>
    private static bool IsAssignedToSensitiveName(SyntaxNode literal)
    {
        foreach (var ancestor in literal.Ancestors())
        {
            switch (ancestor)
            {
                case VariableDeclaratorSyntax declarator:
                    return Secrets.IsSensitiveKey(declarator.Identifier.Text);
                case AssignmentExpressionSyntax { Left: var left }:
                    return Secrets.IsSensitiveKey(left.ToString());
                case ArgumentSyntax { NameColon: { } nameColon }:
                    return Secrets.IsSensitiveKey(nameColon.Name.Identifier.Text);
                case StatementSyntax or MemberDeclarationSyntax:
                    return false;
            }
        }

        return false;
    }

    // ---- web.config / app.config -------------------------------------------

    private static void ExtractFromXmlConfig(string filePath, string relativePath, SignalAccumulator accumulator)
    {
        var doc = XDocument.Parse(File.ReadAllText(filePath), LoadOptions.SetLineInfo);
        if (doc.Root is null)
        {
            return;
        }

        foreach (var element in doc.Root.DescendantsAndSelf())
        {
            // Nothing under <connectionStrings> is read, at all.
            if (element.AncestorsAndSelf().Any(e => e.Name.LocalName == "connectionStrings"))
            {
                continue;
            }

            // <add key="Password" value="…"/>: the key names the value as secret.
            var key = (string?)element.Attribute("key");
            var valueIsSecret = key is not null && Secrets.IsSensitiveKey(key);

            foreach (var attribute in element.Attributes())
            {
                var attributeName = attribute.Name.LocalName;
                if (Secrets.IsSensitiveKey(attributeName) || (valueIsSecret && attributeName == "value"))
                {
                    continue;
                }

                var line = ((IXmlLineInfo)attribute).HasLineInfo() ? ((IXmlLineInfo)attribute).LineNumber : (int?)null;
                AddMatches(attribute.Value, relativePath, EvidenceSourceTypes.Configuration, line, null, null, accumulator);
            }

            if (!valueIsSecret)
            {
                foreach (var text in element.Nodes().OfType<XText>())
                {
                    var line = ((IXmlLineInfo)text).HasLineInfo() ? ((IXmlLineInfo)text).LineNumber : (int?)null;
                    AddMatches(text.Value, relativePath, EvidenceSourceTypes.Configuration, line, null, null, accumulator);
                }
            }
        }
    }

    // ---- matching ----------------------------------------------------------

    private static void AddMatches(
        string text, string relativePath, string sourceType, int? line,
        string? declaringType, string? member, SignalAccumulator accumulator)
    {
        if (text.Length < 3 || Secrets.LooksLikeConnectionString(text))
        {
            return;
        }

        foreach (Match match in UncPath.Matches(text))
        {
            Add(UncPathLiteral, Clean(match.Value), relativePath, sourceType, line, declaringType, member, accumulator);
        }

        foreach (Match match in DrivePath.Matches(text))
        {
            Add(WindowsPathLiteral, Clean(match.Value), relativePath, sourceType, line, declaringType, member, accumulator);
        }

        foreach (var host in Fingerprinting.Analysis.Hostnames.UnqualifiedInUrls(text))
        {
            Add(UnqualifiedHostnameUrl, host, relativePath, sourceType, line, declaringType, member, accumulator, SignalCategories.EndpointIndicator);
        }
    }

    private static string Clean(string matched)
    {
        var value = matched.TrimEnd(' ', '\t', '.', ')', ']', '}');
        return value.Length > MaxMatchedValueLength ? value[..MaxMatchedValueLength] : value;
    }

    private static void Add(
        string signalName, string matchedValue, string relativePath, string sourceType, int? line,
        string? declaringType, string? member, SignalAccumulator accumulator, string category = SignalCategories.HostingIndicator)
    {
        accumulator.Add(
            signalName, category, SignalTypes.Literal,
            matchedValue, sourceType, relativePath, ExtractorName,
            evidence: new Evidence
            {
                LineStart = line,
                LineEnd = line,
                DeclaringType = declaringType,
                Member = member,
                SnippetHash = Hashing.Sha256Hex(matchedValue),
                MatchedValue = matchedValue,
            });
    }
}
