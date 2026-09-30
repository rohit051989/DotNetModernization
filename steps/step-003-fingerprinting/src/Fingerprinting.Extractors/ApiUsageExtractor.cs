using Fingerprinting.Domain;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp.Syntax;

namespace Fingerprinting.Extractors;

/// <summary>
/// <c>API_INVOCATION</c> signals (21-STEP-003-FINGERPRINTING.md Part D "Signal
/// types"): uses of specific framework members whose behaviour changes, or
/// which do not exist, on Linux — plus the hosting calls a containerised
/// service needs. Signal <c>value</c> is the fully qualified member; one row
/// per (file, member), a line span per use.
///
/// Syntax only (Part A4: semantic analysis is off by default), so the
/// receiving type is never confirmed and no match reports 1.0:
/// <list type="bullet">
/// <item><b>0.90</b> — a type-qualified member (<c>Encoding.Default</c>,
/// <c>Process.Start</c>): the type name is written, but could still be a
/// user type or an alias.</item>
/// <item><b>0.80</b> — a bare method name (<c>UseWindowsService()</c>) or a
/// type name matched because the file imports the namespace (<c>new
/// Bitmap(…)</c> under <c>using System.Drawing</c>).</item>
/// </list>
/// </summary>
public sealed class ApiUsageExtractor : IFingerprintExtractor
{
    public const string ExtractorName = "ApiUsageExtractor";

    public string Name => ExtractorName;

    private const decimal QualifiedMember = 0.90m;
    private const decimal NameOnly = 0.80m;

    private sealed record MemberRule(string Signal, string Category, string[] TypeNames, string Member, string Value);

    // Type.Member accesses, matched on the written receiver.
    private static readonly MemberRule[] MemberRules =
    [
        new("ENCODING_DEFAULT_USAGE", SignalCategories.SourceConstruct, ["Encoding", "System.Text.Encoding"], "Default", "System.Text.Encoding.Default"),
        new("DATETIME_NOW_USAGE", SignalCategories.SourceConstruct, ["DateTime", "System.DateTime"], "Now", "System.DateTime.Now"),
        new("DATETIME_NOW_USAGE", SignalCategories.SourceConstruct, ["DateTime", "System.DateTime"], "Today", "System.DateTime.Today"),
        new("DATETIME_NOW_USAGE", SignalCategories.SourceConstruct, ["DateTimeOffset", "System.DateTimeOffset"], "Now", "System.DateTimeOffset.Now"),
        new("PROCESS_START_USAGE", SignalCategories.ExecutionIndicator, ["Process", "System.Diagnostics.Process"], "Start", "System.Diagnostics.Process.Start"),
    ];

    private static readonly string[] RegistryMembers =
        ["LocalMachine", "CurrentUser", "ClassesRoot", "Users", "CurrentConfig", "PerformanceData", "GetValue", "SetValue"];

    private static readonly string[] RegistryKeyMembers = ["OpenBaseKey", "OpenRemoteBaseKey"];

    // Extension methods: only the method name is visible to syntax.
    private sealed record MethodRule(string Signal, string Category, string Method);

    private static readonly MethodRule[] MethodRules =
    [
        new("USE_WINDOWS_SERVICE_INVOCATION", SignalCategories.HostingIndicator, "UseWindowsService"),
        new("USE_WINDOWS_SERVICE_INVOCATION", SignalCategories.HostingIndicator, "AddWindowsService"),
        new("ADD_HEALTH_CHECKS_INVOCATION", SignalCategories.HostingIndicator, "AddHealthChecks"),
        new("MAP_HEALTH_CHECKS_INVOCATION", SignalCategories.EndpointIndicator, "MapHealthChecks"),
        new("MAP_HEALTH_CHECKS_INVOCATION", SignalCategories.EndpointIndicator, "UseHealthChecks"),
    ];

    // Windows-only GDI+ types from System.Drawing.Common. Color, Point, Size
    // and Rectangle are deliberately absent: they are System.Drawing.Primitives
    // and work on Linux — which is exactly why SYSTEM_DRAWING_NAMESPACE alone
    // over-reports.
    private static readonly Dictionary<string, string> DrawingTypes = new(StringComparer.Ordinal)
    {
        ["Bitmap"] = "System.Drawing.Bitmap",
        ["Graphics"] = "System.Drawing.Graphics",
        ["Image"] = "System.Drawing.Image",
        ["Font"] = "System.Drawing.Font",
        ["FontFamily"] = "System.Drawing.FontFamily",
        ["Brush"] = "System.Drawing.Brush",
        ["Brushes"] = "System.Drawing.Brushes",
        ["SolidBrush"] = "System.Drawing.SolidBrush",
        ["TextureBrush"] = "System.Drawing.TextureBrush",
        ["Pen"] = "System.Drawing.Pen",
        ["Pens"] = "System.Drawing.Pens",
        ["Icon"] = "System.Drawing.Icon",
        ["Metafile"] = "System.Drawing.Imaging.Metafile",
        ["ImageFormat"] = "System.Drawing.Imaging.ImageFormat",
        ["StringFormat"] = "System.Drawing.StringFormat",
    };

    // System.DirectoryServices and .AccountManagement are Windows-only.
    // System.DirectoryServices.Protocols (LdapConnection) works on Linux and
    // is deliberately not matched.
    private static readonly Dictionary<string, string> DirectoryTypes = new(StringComparer.Ordinal)
    {
        ["DirectoryEntry"] = "System.DirectoryServices.DirectoryEntry",
        ["DirectorySearcher"] = "System.DirectoryServices.DirectorySearcher",
        ["PrincipalContext"] = "System.DirectoryServices.AccountManagement.PrincipalContext",
        ["UserPrincipal"] = "System.DirectoryServices.AccountManagement.UserPrincipal",
        ["GroupPrincipal"] = "System.DirectoryServices.AccountManagement.GroupPrincipal",
        ["ComputerPrincipal"] = "System.DirectoryServices.AccountManagement.ComputerPrincipal",
    };

    // WCF bindings a client can construct in code, as dotnet-svcutil's
    // generated GetBindingForEndpoint does. Recorded as
    // WCF_CLIENT_BINDING_USAGE (registry 1.5.0) only in client files; see
    // IsWcfClientFile.
    private static readonly HashSet<string> WcfBindingTypes = new(StringComparer.Ordinal)
    {
        "BasicHttpBinding", "BasicHttpsBinding", "NetHttpBinding", "NetHttpsBinding", "WSHttpBinding",
        "WS2007HttpBinding", "WSDualHttpBinding", "NetTcpBinding", "NetNamedPipeBinding", "CustomBinding",
    };

    public bool CanProcess(ProjectContext context) => Directory.Exists(context.ProjectDirectory);

    public async Task<ExtractorResult> ExtractAsync(ProjectContext context, CancellationToken cancellationToken)
    {
        var accumulator = new SignalAccumulator();
        var warnings = new List<Warning>();
        // Generated files are included, but only the WCF client binding
        // rule reads them (svcutil's Reference.cs holds the binding); every
        // other rule skips them, as every other extractor does.
        var scan = SourceFileScanner.EnumerateCSharpFiles(
            context.RepositoryRoot, context.ProjectDirectory, cancellationToken, includeGenerated: true);

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

            var usings = root.DescendantNodes().OfType<UsingDirectiveSyntax>()
                .Select(u => u.Name?.ToString() ?? string.Empty)
                .ToList();
            var importsDrawing = usings.Any(u => u == "System.Drawing" || u.StartsWith("System.Drawing.", StringComparison.Ordinal));
            var importsDirectory = usings.Any(u => u is "System.DirectoryServices" or "System.DirectoryServices.AccountManagement");
            var isWcfClientFile = IsWcfClientFile(root);

            foreach (var node in root.DescendantNodes())
            {
                if (file.IsGenerated)
                {
                    if (isWcfClientFile && node is ObjectCreationExpressionSyntax { Type: var generatedBinding }
                        && RoslynNameHelpers.RightmostIdentifier(generatedBinding) is { } generatedName
                        && WcfBindingTypes.Contains(generatedName))
                    {
                        Add(accumulator, "WCF_CLIENT_BINDING_USAGE", SignalCategories.EndpointIndicator,
                            $"System.ServiceModel.{generatedName}", file.RelativePath, node, NameOnly);
                    }

                    continue;
                }

                switch (node)
                {
                    case MemberAccessExpressionSyntax access:
                        MatchMemberAccess(access, file.RelativePath, accumulator);
                        break;
                    case InvocationExpressionSyntax invocation:
                        MatchMethodCall(invocation, file.RelativePath, accumulator);
                        break;
                    case ObjectCreationExpressionSyntax { Type: var bindingType }
                        when isWcfClientFile && RoslynNameHelpers.RightmostIdentifier(bindingType) is { } bindingName
                             && WcfBindingTypes.Contains(bindingName):
                        Add(accumulator, "WCF_CLIENT_BINDING_USAGE", SignalCategories.EndpointIndicator,
                            $"System.ServiceModel.{bindingName}", file.RelativePath, node, NameOnly);
                        break;
                    case ObjectCreationExpressionSyntax { Type: var created }
                        when RoslynNameHelpers.RightmostIdentifier(created) == "ProcessStartInfo":
                        Add(accumulator, "PROCESS_START_USAGE", SignalCategories.ExecutionIndicator,
                            "System.Diagnostics.ProcessStartInfo", file.RelativePath, node, QualifiedMember);
                        break;
                    case IdentifierNameSyntax identifier:
                        MatchTypeReference(identifier, importsDrawing, importsDirectory, file.RelativePath, accumulator);
                        break;
                }
            }
        }

        if (scan.Truncated)
        {
            warnings.Add(new Warning
            {
                Code = WarningCodes.SourceFileCapExceeded,
                Message = $"Project has more than {SourceFileScanner.MaxFilesPerProject} source files; " +
                          "API usage analysis stopped at the cap.",
                Severity = WarningSeverities.Warning,
            });
        }

        return new ExtractorResult { Signals = accumulator.Build(), Warnings = warnings };
    }

    private static void MatchMemberAccess(MemberAccessExpressionSyntax access, string path, SignalAccumulator accumulator)
    {
        var receiver = access.Expression.ToString();
        var member = access.Name.Identifier.Text;

        foreach (var rule in MemberRules)
        {
            if (rule.Member == member && rule.TypeNames.Contains(receiver))
            {
                Add(accumulator, rule.Signal, rule.Category, rule.Value, path, access, QualifiedMember);
            }
        }

        if ((receiver is "Registry" or "Microsoft.Win32.Registry") && RegistryMembers.Contains(member))
        {
            Add(accumulator, "REGISTRY_ACCESS_USAGE", SignalCategories.HostingIndicator,
                $"Microsoft.Win32.Registry.{member}", path, access, QualifiedMember);
        }
        else if ((receiver is "RegistryKey" or "Microsoft.Win32.RegistryKey") && RegistryKeyMembers.Contains(member))
        {
            Add(accumulator, "REGISTRY_ACCESS_USAGE", SignalCategories.HostingIndicator,
                $"Microsoft.Win32.RegistryKey.{member}", path, access, QualifiedMember);
        }
    }

    private static void MatchMethodCall(InvocationExpressionSyntax invocation, string path, SignalAccumulator accumulator)
    {
        foreach (var rule in MethodRules)
        {
            if (RoslynNameHelpers.IsMethodCallNamed(invocation, rule.Method))
            {
                Add(accumulator, rule.Signal, rule.Category, rule.Method, path, invocation, NameOnly);
            }
        }
    }

    /// <summary>A GDI+ or directory-services type used as a type — created,
    /// declared, or as the receiver of a static call — in a file importing
    /// its namespace, or written fully qualified.</summary>
    private static void MatchTypeReference(
        IdentifierNameSyntax identifier, bool importsDrawing, bool importsDirectory, string path, SignalAccumulator accumulator)
    {
        var name = identifier.Identifier.Text;
        var inDrawing = DrawingTypes.TryGetValue(name, out var drawingType);
        var inDirectory = DirectoryTypes.TryGetValue(name, out var directoryType);
        if (!inDrawing && !inDirectory)
        {
            return;
        }

        // `x.Image` is a member called Image, not the type.
        if (identifier.Parent is MemberAccessExpressionSyntax parentAccess && parentAccess.Name == identifier)
        {
            return;
        }

        var qualifiedParent = identifier.Parent is QualifiedNameSyntax q && q.Right == identifier ? q.Left.ToString() : null;
        var isTypePosition = identifier.Parent is ObjectCreationExpressionSyntax or VariableDeclarationSyntax
            or ParameterSyntax or TypeArgumentListSyntax or ArrayTypeSyntax or NullableTypeSyntax
            or PropertyDeclarationSyntax or MethodDeclarationSyntax or CastExpressionSyntax or QualifiedNameSyntax
            || identifier.Parent is MemberAccessExpressionSyntax { Expression: var expression } && expression == identifier;
        if (!isTypePosition)
        {
            return;
        }

        if (inDrawing)
        {
            var qualified = qualifiedParent is not null && qualifiedParent.StartsWith("System.Drawing", StringComparison.Ordinal);
            if (qualified || (qualifiedParent is null && importsDrawing))
            {
                Add(accumulator, "SYSTEM_DRAWING_USAGE", SignalCategories.SourceConstruct,
                    drawingType!, path, identifier, qualified ? QualifiedMember : NameOnly);
            }
        }

        if (inDirectory)
        {
            var qualified = qualifiedParent is "System.DirectoryServices" or "System.DirectoryServices.AccountManagement";
            if (qualified || (qualifiedParent is null && importsDirectory))
            {
                Add(accumulator, "DIRECTORY_SERVICES_USAGE", SignalCategories.HostingIndicator,
                    directoryType!, path, identifier, qualified ? QualifiedMember : NameOnly);
            }
        }
    }

    private static void Add(
        SignalAccumulator accumulator, string signal, string category, string value, string path,
        SyntaxNode node, decimal confidence)
    {
        var span = node.GetLocation().GetLineSpan();
        accumulator.Add(
            signal, category, SignalTypes.ApiInvocation, value, EvidenceSourceTypes.SourceCode, path, ExtractorName,
            confidence,
            new Evidence
            {
                LineStart = span.StartLinePosition.Line + 1,
                LineEnd = span.EndLinePosition.Line + 1,
                DeclaringType = node.FirstAncestorOrSelf<BaseTypeDeclarationSyntax>()?.Identifier.Text,
                Member = EnclosingMemberName(node),
                SnippetHash = Hashing.Sha256Hex(node.ToString()),
            });
    }

    /// <summary>
    /// A file that calls a WCF service and hosts none: it declares a type
    /// deriving <c>ClientBase&lt;T&gt;</c> or creates a
    /// <c>ChannelFactory&lt;T&gt;</c> / <c>DuplexChannelFactory&lt;T&gt;</c>, and
    /// never mentions <c>ServiceHost</c> or <c>AddServiceEndpoint</c>. A
    /// binding constructed in such a file is the client's binding, which is
    /// what makes "client calling over NetTcp" exact rather than "NetTcp
    /// somewhere in the project".
    /// </summary>
    private static bool IsWcfClientFile(SyntaxNode root)
    {
        var hosts = root.DescendantNodes().OfType<IdentifierNameSyntax>()
            .Any(i => i.Identifier.Text is "ServiceHost" or "AddServiceEndpoint");
        if (hosts)
        {
            return false;
        }

        var derivesClientBase = root.DescendantNodes().OfType<BaseTypeSyntax>()
            .Any(b => RoslynNameHelpers.RightmostIdentifier(b.Type) is "ClientBase" or "DuplexClientBase");
        var createsFactory = root.DescendantNodes().OfType<ObjectCreationExpressionSyntax>()
            .Any(o => RoslynNameHelpers.RightmostIdentifier(o.Type) is "ChannelFactory" or "DuplexChannelFactory");
        return derivesClientBase || createsFactory;
    }

    /// <summary>The method, constructor, property or local function a node
    /// sits in — the caller, for evidence. Null at type or file level.</summary>
    internal static string? EnclosingMemberName(SyntaxNode node)
    {
        foreach (var ancestor in node.AncestorsAndSelf())
        {
            switch (ancestor)
            {
                case LocalFunctionStatementSyntax local:
                    return local.Identifier.Text;
                case MethodDeclarationSyntax method:
                    return method.Identifier.Text;
                case ConstructorDeclarationSyntax ctor:
                    return ctor.Identifier.Text;
                case PropertyDeclarationSyntax property:
                    return property.Identifier.Text;
                case BaseTypeDeclarationSyntax:
                    return null;
            }
        }

        return null;
    }
}
