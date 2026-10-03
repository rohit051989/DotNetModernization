using System.Xml;
using System.Xml.Linq;
using NuGet.Versioning;

namespace Fingerprinting.Dependencies;

/// <summary>A direct package as step 2 recorded it.</summary>
public sealed record InputPackage(string PackageId, string? VersionRaw, string DeclarationSource);

/// <summary>A direct dependency, with its version resolved and the line that declares it.</summary>
public sealed record PackageDeclaration(
    string PackageId, NuGetVersion? Version, string? VersionText, string VersionSource, SourceLine DeclaredAt, string? Problem);

/// <summary>
/// Reads where each of step 2's direct packages is declared, without
/// touching the repository: the PackageReference line in the project file,
/// the packages.config line, and — for central package management, where
/// the project file carries no version — the <c>PackageVersion</c> in the
/// nearest Directory.Packages.props between the project and the repository root.
/// </summary>
public static class PackageDeclarations
{
    public static IReadOnlyList<PackageDeclaration> Read(string repositoryRoot, string projectPath, IReadOnlyList<InputPackage> packages)
    {
        var projectFile = Path.Combine(repositoryRoot, projectPath.Replace('/', Path.DirectorySeparatorChar));
        var projectDirectory = Path.GetDirectoryName(projectFile)!;
        var projectLines = ReadLines(projectFile);
        var packagesConfig = Path.Combine(projectDirectory, "packages.config");
        var packagesConfigLines = ReadLines(packagesConfig);
        var central = CentralVersions(repositoryRoot, projectDirectory);
        var properties = new Lazy<Dictionary<string, string>>(() => StaticProperties(repositoryRoot, projectFile));

        var result = new List<PackageDeclaration>();
        foreach (var package in packages.DistinctBy(p => p.PackageId.ToLowerInvariant()).OrderBy(p => p.PackageId, StringComparer.OrdinalIgnoreCase))
        {
            var fromConfig = package.DeclarationSource == "packages_config";
            var file = fromConfig ? packagesConfig : projectFile;
            var lines = fromConfig ? packagesConfigLines : projectLines;
            var attribute = fromConfig ? "id" : "Include";
            var line = FindLine(lines, attribute, package.PackageId);
            var declaredAt = new SourceLine { FilePath = Relative(repositoryRoot, file), Line = line };

            string? text = package.VersionRaw;
            var source = fromConfig ? "packages_config" : "project";
            if (string.IsNullOrWhiteSpace(text) && !fromConfig && central.TryGetValue(package.PackageId, out var centralVersion))
            {
                text = centralVersion;
                source = "central";
            }

            if (string.IsNullOrWhiteSpace(text))
            {
                result.Add(new PackageDeclaration(package.PackageId, null, null, "unresolved", declaredAt, "no version declared in the project, packages.config or Directory.Packages.props"));
                continue;
            }

            text = ExpandProperties(text, properties.Value);
            var version = ParseVersion(text);
            result.Add(new PackageDeclaration(package.PackageId, version, text, version is null ? "unresolved" : source, declaredAt,
                version is null ? $"version '{text}' is not a version or range this step can read (an MSBuild property?)" : null));
        }

        return result;
    }

    /// <summary>An exact version, or the lower bound of a range or float
    /// (<c>[1.2,2.0)</c>, <c>1.*</c>) — the version restore would start from.</summary>
    public static NuGetVersion? ParseVersion(string text)
    {
        var trimmed = text.Trim();
        if (trimmed.Contains("$(", StringComparison.Ordinal)) return null;
        if (NuGetVersion.TryParse(trimmed, out var exact)) return exact;
        return VersionRange.TryParse(trimmed, out var range) ? range.MinVersion ?? range.Float?.MinVersion : null;
    }

    /// <summary>Replaces <c>$(Name)</c> with a statically declared property
    /// value. Anything left unexpanded stays as written, so ParseVersion
    /// rejects it and the package is reported unknown with the reason.</summary>
    public static string ExpandProperties(string text, IReadOnlyDictionary<string, string> properties)
    {
        for (var pass = 0; pass < 5 && text.Contains("$(", StringComparison.Ordinal); pass++)
        {
            var expanded = System.Text.RegularExpressions.Regex.Replace(text, @"\$\(([A-Za-z_][A-Za-z0-9_.-]*)\)",
                m => properties.TryGetValue(m.Groups[1].Value, out var value) ? value : m.Value);
            if (expanded == text) break;
            text = expanded;
        }

        return text;
    }

    /// <summary>
    /// Unconditional, literal PropertyGroup values from the project file and
    /// every Directory.Build.props / Directory.Packages.props between it and
    /// the repository root. The project file wins over the props files, and a
    /// nearer props file over a further one — an approximation of MSBuild's
    /// import order that is right for the version-property idiom. Conditional
    /// properties are skipped rather than guessed.
    /// </summary>
    private static Dictionary<string, string> StaticProperties(string repositoryRoot, string projectFile)
    {
        var files = new List<string> { projectFile };
        var root = Path.GetFullPath(repositoryRoot).TrimEnd(Path.DirectorySeparatorChar);
        for (var directory = new DirectoryInfo(Path.GetDirectoryName(projectFile)!); directory is not null; directory = directory.Parent)
        {
            files.Add(Path.Combine(directory.FullName, "Directory.Packages.props"));
            files.Add(Path.Combine(directory.FullName, "Directory.Build.props"));
            if (directory.FullName.TrimEnd(Path.DirectorySeparatorChar).Equals(root, StringComparison.OrdinalIgnoreCase)) break;
        }

        var properties = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var file in files.Where(File.Exists))
        {
            try
            {
                foreach (var group in XDocument.Load(file).Descendants().Where(e => e.Name.LocalName == "PropertyGroup" && e.Attribute("Condition") is null))
                {
                    foreach (var property in group.Elements().Where(e => e.Attribute("Condition") is null && !e.HasElements))
                    {
                        properties.TryAdd(property.Name.LocalName, property.Value.Trim());
                    }
                }
            }
            catch (Exception ex) when (ex is XmlException or IOException)
            {
                // An unreadable file contributes nothing; affected packages stay unknown.
            }
        }

        return properties;
    }

    private static Dictionary<string, string> CentralVersions(string repositoryRoot, string projectDirectory)
    {
        var root = Path.GetFullPath(repositoryRoot).TrimEnd(Path.DirectorySeparatorChar);
        for (var directory = new DirectoryInfo(projectDirectory); directory is not null; directory = directory.Parent)
        {
            var props = Path.Combine(directory.FullName, "Directory.Packages.props");
            if (File.Exists(props))
            {
                try
                {
                    return XDocument.Load(props).Descendants()
                        .Where(e => e.Name.LocalName == "PackageVersion")
                        .Select(e => ((string?)e.Attribute("Include"), (string?)e.Attribute("Version")))
                        .Where(x => x.Item1 is not null && x.Item2 is not null)
                        .GroupBy(x => x.Item1!, StringComparer.OrdinalIgnoreCase)
                        .ToDictionary(g => g.Key, g => g.First().Item2!, StringComparer.OrdinalIgnoreCase);
                }
                catch (Exception ex) when (ex is XmlException or IOException)
                {
                    return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                }
            }

            if (directory.FullName.TrimEnd(Path.DirectorySeparatorChar).Equals(root, StringComparison.OrdinalIgnoreCase)) break;
        }

        return new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    }

    private static string[] ReadLines(string path)
    {
        try
        {
            return File.Exists(path) ? File.ReadAllLines(path) : [];
        }
        catch (IOException)
        {
            return [];
        }
    }

    private static int? FindLine(string[] lines, string attribute, string packageId)
    {
        for (var i = 0; i < lines.Length; i++)
        {
            var line = lines[i];
            if (line.Contains($"{attribute}=\"{packageId}\"", StringComparison.OrdinalIgnoreCase)
                || line.Contains($"{attribute}='{packageId}'", StringComparison.OrdinalIgnoreCase))
            {
                return i + 1;
            }
        }

        return null;
    }

    public static string Relative(string repositoryRoot, string path) =>
        Path.GetRelativePath(repositoryRoot, path).Replace('\\', '/');
}
