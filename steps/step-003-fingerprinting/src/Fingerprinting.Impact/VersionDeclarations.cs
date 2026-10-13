using System.Text.RegularExpressions;

namespace Fingerprinting.Impact;

/// <summary>
/// Where a package's version is declared, for the <c>version_declaration</c> primitive (33-IMPACT-ANALYSIS
/// Part E). A package upgrade edits the version where it is written, which under central package management
/// is not the project file:
/// <list type="number">
/// <item>the project's <c>PackageReference</c> with a <c>VersionOverride</c>, or a literal <c>Version</c>: the project file;</item>
/// <item>a <c>Version="$(Name)"</c>: the nearest <c>Directory.Packages.props</c> or <c>Directory.Build.props</c>
/// above the project that defines the property;</item>
/// <item>no version on the reference: the nearest <c>Directory.Packages.props</c>'s <c>PackageVersion</c>, or the
/// property its version names, in that file or the nearest <c>Directory.Build.props</c>.</item>
/// </list>
/// The same order as backend/app/conversion/msbuild.py's <c>version_declaration</c>, which edits the version the
/// way this predicts it. Conditions are not evaluated. Repository-relative paths, "/" separated.
/// </summary>
public sealed class VersionDeclarations(string repositoryRoot, IReadOnlySet<string> files)
{
    public sealed record Declaration(string File, int Line, string Element);

    private readonly Dictionary<string, string> _text = new(StringComparer.OrdinalIgnoreCase);

    public Declaration? Find(string projectFile, string packageId)
    {
        var project = Read(projectFile);
        if (project is null) return null;
        var reference = Element(project, "PackageReference", packageId);
        if (reference is not null)
        {
            if (Attribute(reference.Value.Text, "VersionOverride") is not null)
                return new Declaration(projectFile, reference.Value.Line, $"<PackageReference Include=\"{packageId}\" VersionOverride> line {reference.Value.Line}");
            var version = Attribute(reference.Value.Text, "Version");
            if (version is not null && Property(version) is null)
                return new Declaration(projectFile, reference.Value.Line, $"<PackageReference Include=\"{packageId}\" Version> line {reference.Value.Line}");
            if (Property(version) is { } name)
                return PropertyDeclaration(projectFile, name, ["Directory.Packages.props", "Directory.Build.props"]);
        }

        var central = Nearest(projectFile, "Directory.Packages.props");
        if (central is null) return null;
        var packageVersion = Element(Read(central)!, "PackageVersion", packageId);
        if (packageVersion is null) return null;
        var centralVersion = Attribute(packageVersion.Value.Text, "Version");
        if (Property(centralVersion) is { } property)
        {
            return PropertyDeclaration(central, property, ["Directory.Packages.props", "Directory.Build.props"])
                   ?? PropertyDeclaration(projectFile, property, ["Directory.Build.props"]);
        }

        return new Declaration(central, packageVersion.Value.Line, $"<PackageVersion Include=\"{packageId}\"> line {packageVersion.Value.Line}");
    }

    private Declaration? PropertyDeclaration(string from, string name, string[] fileNames)
    {
        foreach (var fileName in fileNames)
        {
            var holder = Nearest(from, fileName);
            if (holder is null) continue;
            var text = Read(holder)!;
            var match = Regex.Match(text, $@"<{Regex.Escape(name)}(\s[^>]*)?>", RegexOptions.IgnoreCase);
            if (match.Success)
            {
                var line = LineOf(text, match.Index);
                return new Declaration(holder, line, $"<{name}> property, line {line}");
            }
        }

        return null;
    }

    /// <summary>The nearest file of this name in the directory of <paramref name="from"/> or above it, within the repository.</summary>
    private string? Nearest(string from, string fileName)
    {
        var directory = Path.GetDirectoryName(from.Replace('/', Path.DirectorySeparatorChar))?.Replace(Path.DirectorySeparatorChar, '/') ?? "";
        while (true)
        {
            var candidate = directory.Length == 0 ? fileName : $"{directory}/{fileName}";
            var found = files.FirstOrDefault(f => string.Equals(f, candidate, StringComparison.OrdinalIgnoreCase));
            if (found is not null) return found;
            if (directory.Length == 0) return null;
            var slash = directory.LastIndexOf('/');
            directory = slash < 0 ? "" : directory[..slash];
        }
    }

    private string? Read(string relative)
    {
        if (_text.TryGetValue(relative, out var cached)) return cached;
        var path = Path.Combine(repositoryRoot, relative.Replace('/', Path.DirectorySeparatorChar));
        var text = File.Exists(path) ? File.ReadAllText(path) : null;
        if (text is not null) _text[relative] = text;
        return text;
    }

    private static (string Text, int Line)? Element(string text, string tag, string packageId)
    {
        foreach (Match m in Regex.Matches(text, $@"<{tag}\b[^>]*>", RegexOptions.IgnoreCase))
        {
            var include = Attribute(m.Value, "Include") ?? Attribute(m.Value, "Update");
            if (string.Equals(include, packageId, StringComparison.OrdinalIgnoreCase)) return (m.Value, LineOf(text, m.Index));
        }

        return null;
    }

    private static string? Attribute(string element, string name)
    {
        var m = Regex.Match(element, $@"\b{name}\s*=\s*""([^""]*)""", RegexOptions.IgnoreCase);
        return m.Success ? m.Groups[1].Value : null;
    }

    private static string? Property(string? value)
    {
        var m = value is null ? Match.Empty : Regex.Match(value.Trim(), @"^\$\(([A-Za-z_][A-Za-z0-9_.-]*)\)$");
        return m.Success ? m.Groups[1].Value : null;
    }

    private static int LineOf(string text, int index) => text.AsSpan(0, index).Count('\n') + 1;
}
