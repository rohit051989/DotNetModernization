using System.Xml;
using System.Xml.Linq;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Level 2/3 extraction — step-3-application-fingerprinting.md section 5:
/// assembly references, namespace usings and package references, grouped
/// into a stable signal vocabulary. Package references are read from step 2's
/// already-recorded data (<see cref="ProjectContext.Packages"/>), never
/// re-parsed from the project file (21-STEP-003-FINGERPRINTING.md Part A7).
/// Assembly references (classic non-SDK <c>&lt;Reference Include=""&gt;</c>
/// elements) are new — step 2 never parses those at all.
/// </summary>
public sealed class FrameworkReferenceExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "FrameworkReferenceExtractor";

    public string Name => ExtractorName;

    private sealed record NamespaceRule(string Prefix, string SignalName);

    private sealed record PackageRule(string Match, string SignalName, bool IsPrefix);

    // Longest/most-specific prefix first — "System.Web.Mvc" must win over the
    // "System.Web" fallback for a "using System.Web.Mvc;" directive.
    private static readonly IReadOnlyList<NamespaceRule> NamespaceRules =
    [
        new("System.Web.Mvc", "SYSTEM_WEB_MVC_NAMESPACE"),
        new("System.Web.Http", "SYSTEM_WEB_HTTP_NAMESPACE"),
        new("System.Web.UI", "SYSTEM_WEB_UI_NAMESPACE"),
        new("System.Web", "SYSTEM_WEB_NAMESPACE"),
        new("System.ServiceModel", "SYSTEM_SERVICEMODEL_NAMESPACE"),
        new("System.ServiceProcess", "SYSTEM_SERVICEPROCESS_NAMESPACE"),
        new("System.Messaging", "SYSTEM_MESSAGING_NAMESPACE"),
        new("System.Data.Entity", "SYSTEM_DATA_ENTITY_NAMESPACE"),
        new("Microsoft.AspNetCore.Mvc", "MICROSOFT_ASPNETCORE_MVC_NAMESPACE"),
        new("Microsoft.AspNetCore", "MICROSOFT_ASPNETCORE_NAMESPACE"),
        new("Microsoft.EntityFrameworkCore", "MICROSOFT_ENTITYFRAMEWORKCORE_NAMESPACE"),
        new("Dapper", "DAPPER_NAMESPACE"),
        // Registered, but deliberately unreferenced by the catalog: the
        // namespace also holds the cross-platform Color/Point/Size types, so
        // it over-reports. system-drawing-common keys on
        // SYSTEM_DRAWING_USAGE (ApiUsageExtractor) instead.
        new("System.Drawing", "SYSTEM_DRAWING_NAMESPACE"),
    ];

    // Classic .NET Framework assemblies referenced via a raw <Reference
    // Include="..."> element in a non-SDK project — ASP.NET Core / EF Core /
    // Dapper are always NuGet packages, never raw assembly references, so
    // they have no entry here.
    private static readonly IReadOnlyDictionary<string, string> AssemblySignalNames =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["System.Web"] = "SYSTEM_WEB_ASSEMBLY",
            ["System.Web.Mvc"] = "SYSTEM_WEB_MVC_ASSEMBLY",
            ["System.Web.Http"] = "SYSTEM_WEB_HTTP_ASSEMBLY",
            ["System.ServiceModel"] = "SYSTEM_SERVICEMODEL_ASSEMBLY",
            ["System.ServiceProcess"] = "SYSTEM_SERVICEPROCESS_ASSEMBLY",
            ["System.Messaging"] = "SYSTEM_MESSAGING_ASSEMBLY",
        };

    private static readonly IReadOnlyList<PackageRule> PackageRules =
    [
        new("Microsoft.AspNetCore", "MICROSOFT_ASPNETCORE_PACKAGE", IsPrefix: true),
        new("Microsoft.EntityFrameworkCore", "MICROSOFT_ENTITYFRAMEWORKCORE_PACKAGE", IsPrefix: true),
        new("EntityFramework", "ENTITYFRAMEWORK_PACKAGE", IsPrefix: false),
        new("Dapper", "DAPPER_PACKAGE", IsPrefix: false),
        new("xunit", "XUNIT_PACKAGE", IsPrefix: true),
        new("NUnit", "NUNIT_PACKAGE", IsPrefix: true),
        new("MSTest", "MSTEST_PACKAGE", IsPrefix: true),
        // A Microsoft.AspNetCore.Components.WebAssembly* package also matches
        // the generic "Microsoft.AspNetCore" rule above — ExtractPackageSignals
        // checks every rule per package, so both MICROSOFT_ASPNETCORE_PACKAGE
        // and this more specific signal are emitted for it.
        new("Microsoft.AspNetCore.Components.WebAssembly", "BLAZOR_WEBASSEMBLY_PACKAGE", IsPrefix: true),
        // Registry 1.4.0 — Linux blockers and the integrations an OpenShift
        // landing needs to know about. Exact matches unless noted.
        new("System.Drawing.Common", "SYSTEM_DRAWING_COMMON_PACKAGE", IsPrefix: false),
        new("Confluent.Kafka", "CONFLUENT_KAFKA_PACKAGE", IsPrefix: false),
        new("StackExchange.Redis", "STACKEXCHANGE_REDIS_PACKAGE", IsPrefix: false),
        new("Microsoft.Extensions.Caching.StackExchangeRedis", "STACKEXCHANGE_REDIS_PACKAGE", IsPrefix: false),
        new("VaultSharp", "VAULTSHARP_PACKAGE", IsPrefix: false),
        new("Microsoft.Extensions.Hosting.WindowsServices", "MICROSOFT_EXTENSIONS_HOSTING_WINDOWSSERVICES_PACKAGE", IsPrefix: false),
        // The .NET (Core) WCF client packages — System.ServiceModel.Http,
        // .NetTcp, .Primitives, .Duplex, .Security, .Federation. Client-side
        // only: server-side WCF on .NET is CoreWCF, a different package id.
        // The value names the package, so System.ServiceModel.NetTcp (the
        // Linux-blocker binding configured in code) is visible on its own.
        new("System.ServiceModel.", "WCF_CLIENT_PACKAGE", IsPrefix: true),
    ];

    public bool CanProcess(ProjectContext context) => Directory.Exists(context.ProjectDirectory);

    public async Task<ExtractorResult> ExtractAsync(ProjectContext context, CancellationToken cancellationToken)
    {
        var accumulator = new SignalAccumulator();
        var warnings = new List<Warning>();

        ExtractPackageSignals(context, accumulator);
        await ExtractAssemblyReferenceSignalsAsync(context, accumulator, cancellationToken);
        await ExtractNamespaceSignalsAsync(context, accumulator, warnings, cancellationToken);

        return new ExtractorResult { Signals = accumulator.Build(), Warnings = warnings };
    }

    private static void ExtractPackageSignals(ProjectContext context, SignalAccumulator accumulator)
    {
        foreach (var package in context.Packages)
        {
            foreach (var rule in PackageRules)
            {
                var matches = rule.IsPrefix
                    ? package.PackageName.StartsWith(rule.Match, StringComparison.OrdinalIgnoreCase)
                    : string.Equals(package.PackageName, rule.Match, StringComparison.OrdinalIgnoreCase);

                if (matches)
                {
                    accumulator.Add(
                        rule.SignalName,
                        SignalCategories.PackageDependency,
                        SignalTypes.Package,
                        package.PackageName,
                        EvidenceSourceTypes.PackageReference,
                        context.ProjectRelativePath,
                        ExtractorName);
                }
            }
        }
    }

    private static async Task ExtractAssemblyReferenceSignalsAsync(
        ProjectContext context, SignalAccumulator accumulator, CancellationToken cancellationToken)
    {
        var projectFilePath = Path.Combine(context.RepositoryRoot, context.ProjectRelativePath.Replace('/', Path.DirectorySeparatorChar));
        if (!File.Exists(projectFilePath))
        {
            return;
        }

        XDocument doc;
        try
        {
            var xml = await File.ReadAllTextAsync(projectFilePath, cancellationToken);
            doc = XDocument.Parse(xml, LoadOptions.SetLineInfo);
        }
        catch (Exception ex) when (ex is IOException or System.Xml.XmlException)
        {
            return;
        }

        foreach (var reference in doc.Descendants().Where(e => e.Name.LocalName == "Reference"))
        {
            var include = reference.Attribute("Include")?.Value;
            if (include is null)
            {
                continue;
            }

            // "System.Web, Version=4.0.0.0, Culture=neutral, ..." -> "System.Web"
            var simpleName = include.Split(',')[0].Trim();
            if (!AssemblySignalNames.TryGetValue(simpleName, out var signalName))
            {
                continue;
            }

            var lineInfo = (IXmlLineInfo)reference;
            accumulator.Add(
                signalName,
                SignalCategories.FrameworkReference,
                SignalTypes.Assembly,
                simpleName,
                EvidenceSourceTypes.AssemblyReference,
                context.ProjectRelativePath,
                ExtractorName,
                evidence: new Evidence
                {
                    LineStart = lineInfo.HasLineInfo() ? lineInfo.LineNumber : null,
                    LineEnd = lineInfo.HasLineInfo() ? lineInfo.LineNumber : null,
                    SnippetHash = Hashing.Sha256Hex(reference.ToString()),
                });
        }
    }

    private static async Task ExtractNamespaceSignalsAsync(
        ProjectContext context, SignalAccumulator accumulator, List<Warning> warnings, CancellationToken cancellationToken)
    {
        var scan = SourceFileScanner.EnumerateCSharpFiles(context.RepositoryRoot, context.ProjectDirectory, cancellationToken);

        foreach (var file in scan.Files)
        {
            cancellationToken.ThrowIfCancellationRequested();

            Microsoft.CodeAnalysis.SyntaxNode parsedRoot;
            try
            {
                parsedRoot = await SourceFileScanner.ParseAsync(file.AbsolutePath, cancellationToken);
            }
            catch (IOException)
            {
                continue;
            }

            foreach (var usingDirective in parsedRoot.DescendantNodes().OfType<UsingDirectiveSyntax>())
            {
                if (usingDirective.Alias is not null || (SyntaxKind)usingDirective.StaticKeyword.RawKind == SyntaxKind.StaticKeyword)
                {
                    continue;
                }

                var namespaceName = usingDirective.Name?.ToString();
                if (namespaceName is null)
                {
                    continue;
                }

                var signalName = MatchNamespace(namespaceName);
                if (signalName is null)
                {
                    continue;
                }

                var lineSpan = usingDirective.GetLocation().GetLineSpan();
                accumulator.Add(
                    signalName,
                    SignalCategories.FrameworkReference,
                    SignalTypes.Namespace,
                    namespaceName,
                    EvidenceSourceTypes.SourceCode,
                    file.RelativePath,
                    ExtractorName,
                    evidence: new Evidence
                    {
                        LineStart = lineSpan.StartLinePosition.Line + 1,
                        LineEnd = lineSpan.EndLinePosition.Line + 1,
                        SnippetHash = Hashing.Sha256Hex(usingDirective.ToString()),
                    });
            }
        }

        if (scan.Truncated)
        {
            warnings.Add(new Warning
            {
                Code = WarningCodes.SourceFileCapExceeded,
                Message = $"Project has more than {SourceFileScanner.MaxFilesPerProject} source files; " +
                          "namespace-using analysis stopped at the cap.",
                Severity = WarningSeverities.Warning,
            });
        }
    }

    private static string? MatchNamespace(string namespaceName)
    {
        foreach (var rule in NamespaceRules)
        {
            if (namespaceName == rule.Prefix || namespaceName.StartsWith(rule.Prefix + ".", StringComparison.Ordinal))
            {
                return rule.SignalName;
            }
        }

        return null;
    }
}
