using System.Xml;
using System.Xml.Linq;

namespace Fingerprinting.Hierarchy;

/// <summary>A legacy <c>&lt;Reference&gt;</c> as the project file writes it.</summary>
public sealed record AssemblyReference(string Include, string Name, string? Version, string? HintPath, int? Line);

/// <summary>What the step reads from a project file beyond solution-discovery's inventory (37-DEPENDENCY-HIERARCHY.md
/// Part B): its assembly references, the lines of its project references, and what says it is a test or an
/// application. Declared values only, as solution-discovery reads them: no condition is evaluated, no import followed.</summary>
public sealed record ProjectFile(
    IReadOnlyList<AssemblyReference> AssemblyReferences,
    IReadOnlyDictionary<string, int> ProjectReferenceLines,
    IReadOnlySet<string> ProjectTypeGuids,
    bool? IsTestProject,
    string? Error)
{
    public static ProjectFile Empty(string error) => new([], new Dictionary<string, int>(), new HashSet<string>(), null, error);

    public static ProjectFile Read(string path)
    {
        XDocument document;
        try
        {
            document = XDocument.Load(path, LoadOptions.SetLineInfo);
        }
        catch (Exception ex) when (ex is XmlException or IOException or UnauthorizedAccessException)
        {
            return Empty($"the project file could not be read: {ex.Message}");
        }

        var references = new List<AssemblyReference>();
        var projectReferences = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (var item in document.Descendants())
        {
            var include = (string?)item.Attribute("Include");
            if (string.IsNullOrWhiteSpace(include)) continue;
            var line = item is IXmlLineInfo info && info.HasLineInfo() ? info.LineNumber : (int?)null;
            switch (item.Name.LocalName)
            {
                case "Reference":
                    var (name, version) = SplitStrongName(include);
                    var hint = item.Elements().FirstOrDefault(e => e.Name.LocalName == "HintPath")?.Value.Trim();
                    references.Add(new AssemblyReference(include.Trim(), name, version, string.IsNullOrWhiteSpace(hint) ? null : hint, line));
                    break;
                case "ProjectReference" when line is not null:
                    projectReferences.TryAdd(include.Trim().Replace('\\', '/'), line.Value);
                    break;
            }
        }

        var guids = document.Descendants().Where(e => e.Name.LocalName == "ProjectTypeGuids")
            .SelectMany(e => e.Value.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            .Select(g => g.Trim('{', '}').ToUpperInvariant())
            .ToHashSet(StringComparer.Ordinal);
        var isTest = document.Descendants().Where(e => e.Name.LocalName == "IsTestProject" && e.Parent?.Attribute("Condition") is null)
            .Select(e => bool.TryParse(e.Value.Trim(), out var b) ? b : (bool?)null)
            .FirstOrDefault(b => b is not null);
        return new ProjectFile(references, projectReferences, guids, isTest, null);
    }

    /// <summary><c>Foo, Version=1.2.0.0, Culture=neutral</c> → (Foo, 1.2.0.0).</summary>
    public static (string Name, string? Version) SplitStrongName(string include)
    {
        var parts = include.Split(',', StringSplitOptions.TrimEntries);
        var version = parts.Skip(1).Select(p => p.Split('=', 2)).FirstOrDefault(kv => kv.Length == 2 && kv[0].Equals("Version", StringComparison.OrdinalIgnoreCase))?[1];
        return (parts[0], version);
    }

    // ---------- what kind of project ----------

    /// <summary>Legacy project type GUIDs that make a project an application a person runs or a server hosts.</summary>
    private static readonly IReadOnlyDictionary<string, string> ApplicationTypeGuids = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["349C5851-65DF-11DA-9384-00065B846F21"] = "ASP.NET web application",
        ["E3E379DF-F4C6-4180-9B81-6769533ABE47"] = "ASP.NET MVC 4",
        ["E53F8FEA-EAE0-44A6-8774-FFD645390401"] = "ASP.NET MVC 3",
        ["F85E285D-A4E0-4152-9332-AB1D724D3325"] = "ASP.NET MVC 2",
        ["603C0E0B-DB56-11DC-BE95-000D561079B0"] = "ASP.NET MVC 1",
        ["3D9AD99F-2412-4246-B90B-4EAA41C64699"] = "WCF service application",
        ["E24C65DC-7377-472B-9ABA-BC803B73C61A"] = "web site",
    };

    private const string TestTypeGuid = "3AC096D0-A1C2-E12C-1390-A8335801FDAB";

    /// <summary>Packages that make a project a test project.</summary>
    private static readonly string[] TestPackages =
        ["Microsoft.NET.Test.Sdk", "xunit", "xunit.core", "NUnit", "MSTest.TestFramework", "MSTest", "MSTest.Sdk"];

    private static readonly HashSet<string> CodeProjectTypes = new(StringComparer.Ordinal) { "csharp_project", "vb_project", "fsharp_project" };

    private static readonly HashSet<string> ApplicationSdks = new(StringComparer.OrdinalIgnoreCase)
    {
        "Microsoft.NET.Sdk.Web", "Microsoft.NET.Sdk.Worker", "Microsoft.NET.Sdk.BlazorWebAssembly",
    };

    /// <summary>The project's kind and why (Part B2). Test first — a test project's OutputType is often Exe — then
    /// application, then library; anything that is not a C#, VB or F# project, or could not be parsed, is other.</summary>
    public (string Kind, string Basis) Classify(string structuralType, string parseStatus, string? outputType, string? sdk,
        IEnumerable<string> packages)
    {
        if (!CodeProjectTypes.Contains(structuralType)) return (ProjectKinds.Other, $"a {structuralType.Replace('_', ' ')}, not a code project");
        if (parseStatus != "success") return (ProjectKinds.Other, "the project file could not be parsed");

        if (IsTestProject == true) return (ProjectKinds.Test, "IsTestProject is true");
        if (ProjectTypeGuids.Contains(TestTypeGuid)) return (ProjectKinds.Test, "the legacy test project type");
        var packageSet = packages.ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (TestPackages.FirstOrDefault(packageSet.Contains) is { } testPackage) return (ProjectKinds.Test, $"test package {testPackage}");
        if (AssemblyReferences.FirstOrDefault(r => r.Name.StartsWith("Microsoft.VisualStudio.QualityTools.UnitTestFramework", StringComparison.OrdinalIgnoreCase)
                                                   || r.Name.Equals("nunit.framework", StringComparison.OrdinalIgnoreCase)
                                                   || r.Name.Equals("xunit", StringComparison.OrdinalIgnoreCase)) is { } testReference)
        {
            return (ProjectKinds.Test, $"test assembly reference {testReference.Name}");
        }

        if (outputType is { } output && (output.Equals("Exe", StringComparison.OrdinalIgnoreCase) || output.Equals("WinExe", StringComparison.OrdinalIgnoreCase)
                                         || output.Equals("AppContainerExe", StringComparison.OrdinalIgnoreCase)))
        {
            return (ProjectKinds.Application, $"OutputType {output}");
        }

        if (sdk is not null && ApplicationSdks.Contains(sdk)) return (ProjectKinds.Application, $"SDK {sdk}");
        if (ProjectTypeGuids.FirstOrDefault(ApplicationTypeGuids.ContainsKey) is { } guid) return (ProjectKinds.Application, $"the legacy {ApplicationTypeGuids[guid]} project type");
        return (ProjectKinds.Library, $"OutputType {outputType ?? "Library"}");
    }

    // ---------- where an assembly reference points ----------

    private static readonly HashSet<string> FrameworkAssemblies = new(StringComparer.OrdinalIgnoreCase)
    {
        "mscorlib", "netstandard", "System", "Microsoft.CSharp", "Microsoft.VisualBasic", "Microsoft.JScript", "WindowsBase",
        "PresentationCore", "PresentationFramework", "ReachFramework", "UIAutomationClient", "UIAutomationTypes", "UIAutomationProvider",
        "Accessibility", "WindowsFormsIntegration", "Microsoft.Build.Framework", "Microsoft.Build.Utilities.v4.0", "Microsoft.Build.Tasks.v4.0",
    };

    public static bool IsFrameworkAssembly(string name) =>
        FrameworkAssemblies.Contains(name)
        || name.StartsWith("System.", StringComparison.OrdinalIgnoreCase)
        || name.StartsWith("PresentationFramework.", StringComparison.OrdinalIgnoreCase);
}
