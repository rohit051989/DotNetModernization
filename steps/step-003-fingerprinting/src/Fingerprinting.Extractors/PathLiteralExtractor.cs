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

    /// <summary>Registry 1.16.0: a path built by joining parts with a backslash (<c>dir + "\\" + name</c>,
    /// <c>string.Concat(dir, @"\", name)</c>, <c>$"{dir}\\{name}"</c>). On Linux a backslash is an ordinary character of
    /// a file name, so the file lands somewhere else. The value is the literal's text.</summary>
    public const string BackslashPathBuilding = "BACKSLASH_PATH_BUILDING";

    // A path fragment that a backslash starts or ends: "\", "\logs\", "logs\". No drive letter, no colon, no
    // character a Windows path cannot hold, no space-only text.
    // Registry 1.17.0: a URL whose path has a "claims" segment (http://host/claims/role): a claim type, not an endpoint.
    private static readonly Regex ClaimsPathSegment = new(@"://[^/\s""'<>]+/(?:[^?#\s""'<>]*/)?claims(?:/|$|[?#\s""'<>])",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private static readonly Regex BackslashFragment = new(@"^(\\[^\\""<>|*?:\r\n]*)+\\?$|^[^\\""<>|*?:\r\n]+\\$",
        RegexOptions.CultureInvariant);

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

        foreach (var filePath in FileSystemWalk.EnumerateProjectFiles(context.ProjectDirectory, cancellationToken))
        {
            var fileName = Path.GetFileName(filePath);
            var relativePath = FileSystemWalk.ToRepositoryRelativePath(context.RepositoryRoot, filePath);
            try
            {
                if (ConfigFileNames.IsAppSettings(fileName))
                {
                    foreach (var node in JsonConfigWalker.Walk(filePath))
                    {
                        // StringValue is null for anything secret-bearing. Registry 1.12.0: the member is the
                        // configuration key the code reads it by (FileContent:FilePath), so a deployment parameter
                        // can be named after it.
                        if (node.StringValue is { } text)
                        {
                            AddMatches(text, relativePath, EvidenceSourceTypes.Configuration, node.Line, null, node.KeyPath, accumulator);
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
                accumulator, hostnames: !IsIdentifierUri(token));
            if (JoinsPathWithBackslash(token))
            {
                Add(BackslashPathBuilding, Clean(token.ValueText), relativePath, EvidenceSourceTypes.SourceCode, line,
                    token.Parent.FirstAncestorOrSelf<BaseTypeDeclarationSyntax>()?.Identifier.Text,
                    ApiUsageExtractor.EnclosingMemberName(token.Parent), accumulator);
            }
        }
    }

    /// <summary>Registry 1.17.0: a literal that is an identifier written as a URI (a claim type, an XML namespace), not an
    /// endpoint, so its host is no hostname to resolve: a URL with a <c>claims</c> path segment; an argument of
    /// <c>new Claim(...)</c>, <c>FindFirst</c>, <c>FindAll</c>, <c>FindFirstValue</c>, <c>HasClaim</c>,
    /// <c>new ClaimsIdentity(...)</c> or <c>XNamespace.Get</c>, or a value given to something typed <c>XNamespace</c>; the
    /// value of a constant, field, property or variable named like a claim type or a namespace (a name containing
    /// ClaimType or Xmlns, or ending in Namespace), or one declared in a type whose name contains ClaimType or ends in
    /// Claims; never a name that merely contains Claim (claimsServiceUrl is an endpoint); an attribute argument named
    /// <c>Namespace</c>, or an <c>XmlnsDefinition</c> attribute's argument.</summary>
    private static bool IsIdentifierUri(SyntaxToken token)
    {
        if (ClaimsPathSegment.IsMatch(token.ValueText))
        {
            return true;
        }

        foreach (var ancestor in token.Parent!.Ancestors())
        {
            switch (ancestor)
            {
                case AttributeArgumentSyntax argument:
                    if (argument.NameEquals?.Name.Identifier.Text == "Namespace" || argument.NameColon?.Name.Identifier.Text == "Namespace")
                    {
                        return true;
                    }

                    return argument.Parent?.Parent is AttributeSyntax attribute
                           && RoslynNameHelpers.AttributeSimpleName(attribute.Name) == "XmlnsDefinition";
                case ArgumentSyntax { Parent: ArgumentListSyntax { Parent: var call } }:
                    switch (call)
                    {
                        case ObjectCreationExpressionSyntax { Type: var created }
                            when RoslynNameHelpers.RightmostIdentifier(created) is "Claim" or "ClaimsIdentity":
                            return true;
                        case InvocationExpressionSyntax invocation
                            when ClaimLookups.Any(m => RoslynNameHelpers.IsMethodCallNamed(invocation, m))
                                 || invocation.Expression.ToString() is "XNamespace.Get" or "System.Xml.Linq.XNamespace.Get":
                            return true;
                    }

                    continue;
                case VariableDeclarationSyntax { Type: var declared } when declared.ToString().EndsWith("XNamespace", StringComparison.Ordinal):
                    return true;
                case VariableDeclaratorSyntax declarator when NamedLikeIdentifierUri(declarator.Identifier.Text):
                    return true;
                case PropertyDeclarationSyntax property:
                    return NamedLikeIdentifierUri(property.Identifier.Text) || property.Type.ToString().EndsWith("XNamespace", StringComparison.Ordinal)
                           || InClaimTypes(property);
                case AssignmentExpressionSyntax { Left: var left }:
                    return NamedLikeIdentifierUri(left.ToString());
                case FieldDeclarationSyntax field:
                    return InClaimTypes(field);
                case StatementSyntax or MemberDeclarationSyntax:
                    return false;
            }
        }

        return false;
    }

    private static readonly string[] ClaimLookups = ["FindFirst", "FindAll", "FindFirstValue", "HasClaim"];

    private static bool NamedLikeIdentifierUri(string name) =>
        name.Contains("ClaimType", StringComparison.OrdinalIgnoreCase)
        || name.Contains("Xmlns", StringComparison.OrdinalIgnoreCase)
        || name.EndsWith("Namespace", StringComparison.OrdinalIgnoreCase);

    private static bool InClaimTypes(SyntaxNode member) =>
        member.FirstAncestorOrSelf<BaseTypeDeclarationSyntax>()?.Identifier.Text is { } type
        && (type.Contains("ClaimType", StringComparison.OrdinalIgnoreCase) || type.EndsWith("Claims", StringComparison.OrdinalIgnoreCase));

    /// <summary>Registry 1.16.0: the literal is a backslash path fragment that joins parts of a path: an operand of
    /// <c>+</c>, an argument of <c>string.Concat</c>, or interpolated-string text beside an interpolation. A drive or
    /// UNC path is its own signal; text passed to a Regex is a pattern, not a path.</summary>
    private static bool JoinsPathWithBackslash(SyntaxToken token)
    {
        var text = token.ValueText;
        if (text.Length == 0 || !BackslashFragment.IsMatch(text) || DrivePath.IsMatch(text) || UncPath.IsMatch(text))
        {
            return false;
        }

        if (token.Parent?.FirstAncestorOrSelf<InvocationExpressionSyntax>() is { } call
            && call.Expression.ToString().Contains("Regex", StringComparison.Ordinal))
        {
            return false;
        }

        if (token.IsKind(SyntaxKind.InterpolatedStringTextToken))
        {
            return token.Parent is InterpolatedStringTextSyntax part
                   && part.Parent is InterpolatedStringExpressionSyntax whole
                   && whole.Contents.IndexOf(part) is var at
                   && ((at > 0 && whole.Contents[at - 1] is InterpolationSyntax)
                       || (at < whole.Contents.Count - 1 && whole.Contents[at + 1] is InterpolationSyntax));
        }

        if (!token.IsKind(SyntaxKind.StringLiteralToken) || token.Parent is not LiteralExpressionSyntax literal)
        {
            return false;
        }

        return literal.Parent switch
        {
            BinaryExpressionSyntax binary => binary.IsKind(SyntaxKind.AddExpression),
            ArgumentSyntax { Parent: ArgumentListSyntax { Parent: InvocationExpressionSyntax invocation } } =>
                invocation.Expression.ToString() is "string.Concat" or "String.Concat" or "System.String.Concat",
            _ => false,
        };
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
                AddMatches(attribute.Value, relativePath, EvidenceSourceTypes.Configuration, line, null, XmlSetting(element, attributeName), accumulator);
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

    /// <summary>The setting an XML value belongs to (registry 1.12.0): the <c>key</c> or <c>name</c> of an
    /// <c>&lt;add key=... value=...&gt;</c> or <c>&lt;environmentVariable name=... value=...&gt;</c>, else
    /// <c>element@attribute</c>.</summary>
    private static string XmlSetting(XElement element, string attributeName)
    {
        var name = (string?)element.Attribute("key") ?? (string?)element.Attribute("name");
        return attributeName == "value" && !string.IsNullOrEmpty(name) ? name : $"{element.Name.LocalName}@{attributeName}";
    }

    // ---- matching ----------------------------------------------------------

    private static void AddMatches(
        string text, string relativePath, string sourceType, int? line,
        string? declaringType, string? member, SignalAccumulator accumulator, bool hostnames = true)
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

        foreach (var host in hostnames ? Fingerprinting.Analysis.Hostnames.UnqualifiedInUrls(text) : [])
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
