using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;

namespace Fingerprinting.Analysis;

/// <summary>One <c>&lt;setParameter name value/&gt;</c> of a Web Deploy
/// SetParameters file. <see cref="RawValue"/> is held in memory only: a
/// caller may persist it only where <see cref="DeployParameterFiles.MayStore"/>
/// allows — a URL that links to an endpoint, or a path.</summary>
public sealed record DeployParameter(string Name, string RawValue, int Line);

/// <summary>A SetParameters file (MSDeploy parameterisation, one per
/// environment): where it is, the environment it is for, and the project it
/// belongs to, when a folder on its path is named after one.</summary>
public sealed record DeployParameterFile(string RelativePath, string Environment, string? ProjectPath, IReadOnlyList<DeployParameter> Parameters);

/// <summary>What a <c>parameters.xml</c> declaration says a parameter
/// replaces, read from its <c>parameterEntry match</c> XPath:
/// <c>client_endpoint</c> (a WCF client endpoint's address, by endpoint
/// name), <c>app_setting</c> (by key), <c>connection_string</c> (by name),
/// or <c>xpath</c> for anything else, with the XPath as written.</summary>
public sealed record DeployParameterTarget(string Kind, string Name);

public static partial class DeployParameterFiles
{
    /// <summary>The engagement setting's default (29-STEPS Part C9, 1.3.0).</summary>
    public static readonly IReadOnlyList<string> DefaultGlobs = ["**/SetParam*.xml", "**/SetParameters*.xml"];

    // SetParam.PROD.xml, SetParameters.UAT.xml: the environment as a suffix.
    [GeneratedRegex(@"^Set(Param|Parameters)[._-](?<env>[^.]+)\.xml$", RegexOptions.IgnoreCase)]
    private static partial Regex SuffixedName();

    [GeneratedRegex(@"^/configuration/system\.serviceModel/client/endpoint\[@name='(?<name>[^']+)'\]/@address$", RegexOptions.IgnoreCase)]
    private static partial Regex ClientEndpointXPath();

    [GeneratedRegex(@"^/configuration/appSettings/add\[@key='(?<name>[^']+)'\]/@value$", RegexOptions.IgnoreCase)]
    private static partial Regex AppSettingXPath();

    [GeneratedRegex(@"^/configuration/connectionStrings/add\[@name='(?<name>[^']+)'\]/@connectionString$", RegexOptions.IgnoreCase)]
    private static partial Regex ConnectionStringXPath();

    [GeneratedRegex(@"^[A-Za-z][A-Za-z0-9+.-]*://", RegexOptions.CultureInvariant)]
    private static partial Regex UrlStart();

    // A drive path, a UNC path, or a relative path with a separator and no
    // spaces, equals signs or semicolons (Logs\FundsTransfer\).
    [GeneratedRegex(@"^([A-Za-z]:[\\/]|\\\\[A-Za-z0-9]|[A-Za-z0-9._-]+[\\/][^=;\s]*$)", RegexOptions.CultureInvariant)]
    private static partial Regex PathShape();

    /// <summary>Every file matching any glob, parsed, its environment named
    /// and its project found. A file that is not well-formed XML is skipped.
    /// <paramref name="projectPaths"/> are step 2's project file paths.</summary>
    public static IReadOnlyList<DeployParameterFile> Discover(
        string repositoryRoot, IReadOnlyList<string> globs, IReadOnlyList<string> projectPaths, CancellationToken cancellationToken)
    {
        var patterns = (globs.Count == 0 ? DefaultGlobs : globs).Select(GlobRegex).ToList();
        var files = new List<(string Relative, string Text)>();
        foreach (var path in FileSystemWalk.EnumerateFiles(repositoryRoot, cancellationToken))
        {
            var relative = FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, path);
            if (patterns.Any(p => p.IsMatch(relative)))
            {
                files.Add((relative, File.ReadAllText(path)));
            }
        }

        return FromText(files, projectPaths);
    }

    /// <summary>For tests, and for <see cref="Discover"/>: files given as text.</summary>
    public static IReadOnlyList<DeployParameterFile> FromText(IReadOnlyList<(string RelativePath, string Text)> files, IReadOnlyList<string> projectPaths)
    {
        var result = new List<DeployParameterFile>();
        foreach (var (relative, text) in files.OrderBy(f => f.RelativePath, StringComparer.Ordinal))
        {
            XDocument document;
            try
            {
                document = XDocument.Parse(text, LoadOptions.SetLineInfo);
            }
            catch (XmlException)
            {
                continue;
            }

            if (document.Root?.Name.LocalName != "parameters")
            {
                continue;   // matched the glob, but not a SetParameters file
            }

            var parameters = document.Root.Elements().Where(e => e.Name.LocalName == "setParameter")
                .Select(e => ((string?)e.Attribute("name"), (string?)e.Attribute("value") ?? "", ((IXmlLineInfo)e).LineNumber))
                .Where(p => !string.IsNullOrEmpty(p.Item1))
                .Select(p => new DeployParameter(p.Item1!, p.Item2, p.LineNumber))
                .ToList();
            result.Add(new DeployParameterFile(relative, EnvironmentOf(relative), ProjectFor(relative, projectPaths), parameters));
        }

        return result;
    }

    /// <summary>A filename suffix (<c>SetParam.PROD.xml</c>) names the
    /// environment; otherwise the parent folder does
    /// (<c>SetParamFiles\PROD\SetParam.xml</c>, <c>DEV\LOCAL\SetParam.xml</c> → LOCAL).</summary>
    public static string EnvironmentOf(string relativePath)
    {
        var name = relativePath.Split('/')[^1];
        if (SuffixedName().Match(name) is { Success: true } match)
        {
            return match.Groups["env"].Value;
        }

        var segments = relativePath.Split('/');
        return segments.Length >= 2 ? segments[^2] : "default";
    }

    /// <summary>The project whose name a folder on the file's path carries
    /// (<c>CustomFiles\Catalog.Host\SetParamFiles\…</c> → Catalog.Host), or
    /// the project whose directory contains the file. Null when neither.</summary>
    public static string? ProjectFor(string relativePath, IReadOnlyList<string> projectPaths)
    {
        var folders = relativePath.Split('/')[..^1];
        foreach (var project in projectPaths.OrderBy(p => p, StringComparer.Ordinal))
        {
            var stem = Path.GetFileNameWithoutExtension(project.Split('/')[^1]);
            if (folders.Any(f => f.Equals(stem, StringComparison.OrdinalIgnoreCase)))
            {
                return project;
            }
        }

        return projectPaths
            .Where(p => p.Contains('/') && relativePath.StartsWith(p[..(p.LastIndexOf('/') + 1)], StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(p => p.Length).FirstOrDefault();
    }

    /// <summary>The <c>parameters.xml</c> declarations in a project directory,
    /// by parameter name: what each replaces, read from its XPath match.</summary>
    public static IReadOnlyDictionary<string, DeployParameterTarget> Declarations(string? declarationsText)
    {
        var result = new Dictionary<string, DeployParameterTarget>(StringComparer.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(declarationsText))
        {
            return result;
        }

        XDocument document;
        try
        {
            document = XDocument.Parse(declarationsText);
        }
        catch (XmlException)
        {
            return result;
        }

        foreach (var parameter in document.Root?.Elements().Where(e => e.Name.LocalName == "parameter") ?? [])
        {
            var name = (string?)parameter.Attribute("name");
            var match = parameter.Elements().Where(e => e.Name.LocalName == "parameterEntry")
                .Select(e => (string?)e.Attribute("match")).FirstOrDefault(m => !string.IsNullOrEmpty(m));
            if (name is null || match is null)
            {
                continue;
            }

            result[name] = match switch
            {
                _ when ClientEndpointXPath().Match(match) is { Success: true } m => new DeployParameterTarget("client_endpoint", m.Groups["name"].Value),
                _ when AppSettingXPath().Match(match) is { Success: true } m => new DeployParameterTarget("app_setting", m.Groups["name"].Value),
                _ when ConnectionStringXPath().Match(match) is { Success: true } m => new DeployParameterTarget("connection_string", m.Groups["name"].Value),
                _ => new DeployParameterTarget("xpath", match),
            };
        }

        return result;
    }

    /// <summary><c>url</c>, <c>path</c>, <c>connection_string</c>,
    /// <c>sensitive</c> (the name marks it secret) or <c>other</c>. A
    /// sensitive name or a connection string wins over any shape.</summary>
    public static string Classify(DeployParameter parameter)
    {
        if (Secrets.IsSensitiveKey(parameter.Name))
        {
            return "sensitive";
        }

        var value = parameter.RawValue.Trim();
        if (Secrets.LooksLikeConnectionString(value))
        {
            return "connection_string";
        }

        if (UrlStart().IsMatch(value))
        {
            return "url";
        }

        return PathShape().IsMatch(value) ? "path" : "other";
    }

    /// <summary>The only values a caller may persist: a path, or a URL that
    /// links to an endpoint. Everything else is recorded as present.</summary>
    public static bool MayStore(string kind, bool linkedToEndpoint) => kind == "path" || (kind == "url" && linkedToEndpoint);

    /// <summary>A glob (<c>**/</c> any folders, <c>*</c> within one segment,
    /// <c>?</c> one character) over repository-relative paths, case-insensitive.</summary>
    public static Regex GlobRegex(string glob)
    {
        var pattern = Regex.Escape(glob.Replace('\\', '/'))
            .Replace(@"\*\*/", "(?:.*/)?")
            .Replace(@"\*\*", ".*")
            .Replace(@"\*", "[^/]*")
            .Replace(@"\?", "[^/]");
        return new Regex("^" + pattern + "$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    }
}
