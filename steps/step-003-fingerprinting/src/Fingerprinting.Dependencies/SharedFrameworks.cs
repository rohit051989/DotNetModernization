using System.Text.Json;
using System.Text.RegularExpressions;
using NuGet.Versioning;

namespace Fingerprinting.Dependencies;

/// <summary>
/// The packages a target framework's shared frameworks provide (30-DEPENDENCY-ASSESSMENT Part C2, 1.4.0), from
/// schemas/shared-frameworks-1.0.0.json — the SDK's own PackageOverrides.txt for each targeting pack, the list .NET's
/// package pruning uses. A reference to one of them, at a version the framework already carries, is a removal:
/// the target provides it (Microsoft.AspNetCore.Server.Kestrel 2.x and System.Text.Json on net10.0).
///
/// Microsoft.NETCore.App is every project's. Microsoft.AspNetCore.App is a project's when it uses the Web SDK
/// (Microsoft.NET.Sdk.Web, Razor) or declares <c>&lt;FrameworkReference Include="Microsoft.AspNetCore.App" /&gt;</c>.
/// </summary>
public sealed class SharedFrameworks
{
    public const string NetCoreApp = "Microsoft.NETCore.App";
    public const string AspNetCoreApp = "Microsoft.AspNetCore.App";

    private static readonly Regex AspNetCoreFrameworkReference =
        new(@"<FrameworkReference\s+Include\s*=\s*""Microsoft\.AspNetCore\.App""", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    private readonly Dictionary<string, Dictionary<string, Dictionary<string, NuGetVersion>>> _frameworks;

    public SharedFrameworks(Dictionary<string, Dictionary<string, Dictionary<string, NuGetVersion>>> frameworks) => _frameworks = frameworks;

    public static SharedFrameworks Empty { get; } = new([]);

    public static SharedFrameworks Load(string path)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var result = new Dictionary<string, Dictionary<string, Dictionary<string, NuGetVersion>>>(StringComparer.OrdinalIgnoreCase);
        foreach (var tfm in document.RootElement.GetProperty("frameworks").EnumerateObject())
        {
            var byFramework = new Dictionary<string, Dictionary<string, NuGetVersion>>(StringComparer.Ordinal);
            foreach (var framework in tfm.Value.EnumerateObject())
            {
                byFramework[framework.Name] = framework.Value.EnumerateObject()
                    .Where(p => NuGetVersion.TryParse(p.Value.GetString(), out _))
                    .ToDictionary(p => p.Name, p => NuGetVersion.Parse(p.Value.GetString()!), StringComparer.OrdinalIgnoreCase);
            }

            result[tfm.Name] = byFramework;
        }

        return new SharedFrameworks(result);
    }

    /// <summary>The shared frameworks a project uses: always Microsoft.NETCore.App, and Microsoft.AspNetCore.App for
    /// the Web or Razor SDK or a FrameworkReference to it in the project file.</summary>
    public static IReadOnlyList<string> UsedBy(string? projectSdk, string? projectFileText)
    {
        var web = projectSdk is { } sdk && (sdk.Equals("Microsoft.NET.Sdk.Web", StringComparison.OrdinalIgnoreCase)
                                             || sdk.Equals("Microsoft.NET.Sdk.Razor", StringComparison.OrdinalIgnoreCase));
        return web || (projectFileText is not null && AspNetCoreFrameworkReference.IsMatch(projectFileText))
            ? [NetCoreApp, AspNetCoreApp]
            : [NetCoreApp];
    }

    /// <summary>The shared framework that provides <paramref name="packageId"/> at <paramref name="version"/> on the
    /// target, or null: the package is in that framework's overrides and the referenced version is not above the
    /// version it carries (a newer out-of-band release is a legitimate override, kept).</summary>
    public string? Provider(string targetFramework, IReadOnlyList<string> used, string packageId, NuGetVersion version)
    {
        if (!_frameworks.TryGetValue(targetFramework, out var byFramework)) return null;
        foreach (var framework in used)
        {
            if (byFramework.TryGetValue(framework, out var packages) && packages.TryGetValue(packageId, out var carried) && version <= carried)
            {
                return framework;
            }
        }

        return null;
    }

    public bool Knows(string targetFramework) => _frameworks.ContainsKey(targetFramework);
}
