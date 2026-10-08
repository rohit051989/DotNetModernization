using System.Globalization;
using System.Xml;
using System.Xml.Linq;
using Fingerprinting.Analysis;

namespace Fingerprinting.TestCoverage;

/// <summary>
/// Part E: existing coverage reports — Cobertura, OpenCover and lcov — found
/// in the repository or a configured CI output location, parsed into
/// per-file line and branch data. The format is decided by content, not
/// name: Cobertura's <c>&lt;coverage&gt;</c>, OpenCover's
/// <c>&lt;CoverageSession&gt;</c>, lcov's <c>SF:</c> records.
///
/// A report names files by the path on the machine that produced it, so each
/// is mapped to a repository source file by the longest repository-relative
/// path it ends with. A path matching no file, or two equally, is reported
/// unmatched rather than guessed.
/// </summary>
public static class CoverageReports
{
    /// <summary>Per-file data from one report: line → covered, and per line
    /// the branches covered and total.</summary>
    public sealed class FileData
    {
        public Dictionary<int, bool> Lines { get; } = [];
        public Dictionary<int, (int Covered, int Total)> Branches { get; } = [];

        public void AddLine(int line, bool covered) => Lines[line] = Lines.TryGetValue(line, out var was) ? was || covered : covered;

        public void AddBranches(int line, int covered, int total)
        {
            var (c, t) = Branches.TryGetValue(line, out var was) ? was : (0, 0);
            Branches[line] = (c + covered, t + total);
        }
    }

    public sealed record ParsedReport(string Path, string Format, IReadOnlyDictionary<string, FileData> FilesByReportPath);

    /// <summary>Candidate report files: names that coverage tools write.</summary>
    public static bool IsCandidate(string path)
    {
        var name = System.IO.Path.GetFileName(path).ToLowerInvariant();
        if (name == "lcov.info" || name.EndsWith(".lcov", StringComparison.Ordinal)) return true;
        return name.EndsWith(".xml", StringComparison.Ordinal)
               && (name.Contains("cobertura") || name.Contains("opencover") || name.Contains("coverage"));
    }

    /// <summary>Every candidate in the repository (step 1's walk, skipping
    /// bin, obj, node_modules) and, fully, in each configured location.
    /// Returns (absolute path, display path) pairs, sorted.</summary>
    public static IReadOnlyList<(string Absolute, string Display)> Find(string repositoryRoot, IEnumerable<string> configuredLocations, CancellationToken ct)
    {
        var found = FileSystemWalk.EnumerateFiles(repositoryRoot, ct).Where(IsCandidate)
            .Select(p => (p, FileSystemWalk.ToRepositoryRelativePath(repositoryRoot, p))).ToList();
        foreach (var location in configuredLocations.Where(Directory.Exists))
        {
            found.AddRange(Directory.EnumerateFiles(location, "*", SearchOption.AllDirectories).Where(IsCandidate)
                .Select(p => (p, "ci:" + p.Replace('\\', '/'))));
        }

        return found.DistinctBy(f => f.Item1.ToLowerInvariant()).OrderBy(f => f.Item2, StringComparer.Ordinal).ToList();
    }

    /// <summary>Null when the file is not a coverage report after all.</summary>
    public static ParsedReport? Parse(string absolutePath, string displayPath)
    {
        var text = File.ReadAllText(absolutePath);
        var trimmed = text.TrimStart('\uFEFF', ' ', '\r', '\n', '\t');
        if (trimmed.StartsWith("TN:", StringComparison.Ordinal) || trimmed.StartsWith("SF:", StringComparison.Ordinal))
        {
            return new ParsedReport(displayPath, "lcov", ParseLcov(text));
        }

        if (!trimmed.StartsWith('<')) return null;
        XDocument document;
        try
        {
            using var reader = XmlReader.Create(new StringReader(text), new XmlReaderSettings { DtdProcessing = DtdProcessing.Ignore, XmlResolver = null });
            document = XDocument.Load(reader);
        }
        catch (XmlException)
        {
            return null;
        }

        return document.Root?.Name.LocalName switch
        {
            "coverage" when document.Root.Element("packages") is not null => new ParsedReport(displayPath, "cobertura", ParseCobertura(document)),
            "CoverageSession" => new ParsedReport(displayPath, "opencover", ParseOpenCover(document)),
            _ => null,
        };
    }

    private static Dictionary<string, FileData> ParseCobertura(XDocument document)
    {
        var sources = document.Root!.Element("sources")?.Elements("source").Select(s => s.Value.Trim()).Where(s => s.Length > 0).ToList() ?? [];
        var files = new Dictionary<string, FileData>(StringComparer.Ordinal);
        foreach (var @class in document.Descendants("class"))
        {
            var filename = (string?)@class.Attribute("filename");
            if (string.IsNullOrWhiteSpace(filename)) continue;
            var path = Normalise(sources.Count == 1 && !IsRooted(filename) ? $"{sources[0].TrimEnd('/', '\\')}/{filename}" : filename);
            var data = files.TryGetValue(path, out var existing) ? existing : files[path] = new FileData();
            // The class's own <lines>; methods repeat the same lines.
            foreach (var line in @class.Element("lines")?.Elements("line") ?? [])
            {
                var number = Int(line.Attribute("number"));
                if (number <= 0) continue;
                data.AddLine(number, Int(line.Attribute("hits")) > 0);
                // condition-coverage="50% (1/2)"
                var condition = (string?)line.Attribute("condition-coverage");
                if (condition is not null && condition.IndexOf('(') is var open and >= 0 && condition.IndexOf(')', open) is var close and > 0)
                {
                    var parts = condition[(open + 1)..close].Split('/');
                    if (parts.Length == 2 && int.TryParse(parts[0], out var covered) && int.TryParse(parts[1], out var total))
                    {
                        data.AddBranches(number, covered, total);
                    }
                }
            }
        }

        return files;
    }

    private static Dictionary<string, FileData> ParseOpenCover(XDocument document)
    {
        var files = new Dictionary<string, FileData>(StringComparer.Ordinal);
        foreach (var module in document.Descendants("Module"))
        {
            var paths = module.Element("Files")?.Elements("File")
                .ToDictionary(f => (string?)f.Attribute("uid") ?? "", f => Normalise((string?)f.Attribute("fullPath") ?? "")) ?? [];
            foreach (var method in module.Descendants("Method"))
            {
                var methodFile = (string?)method.Element("FileRef")?.Attribute("uid");
                foreach (var point in method.Descendants("SequencePoint"))
                {
                    var path = paths.GetValueOrDefault((string?)point.Attribute("fileid") ?? methodFile ?? "");
                    var line = Int(point.Attribute("sl"));
                    if (string.IsNullOrEmpty(path) || line <= 0) continue;
                    (files.TryGetValue(path, out var d) ? d : files[path] = new FileData()).AddLine(line, Int(point.Attribute("vc")) > 0);
                }

                foreach (var point in method.Descendants("BranchPoint"))
                {
                    var path = paths.GetValueOrDefault((string?)point.Attribute("fileid") ?? methodFile ?? "");
                    var line = Int(point.Attribute("sl"));
                    if (string.IsNullOrEmpty(path) || line <= 0) continue;
                    (files.TryGetValue(path, out var d) ? d : files[path] = new FileData()).AddBranches(line, Int(point.Attribute("vc")) > 0 ? 1 : 0, 1);
                }
            }
        }

        return files;
    }

    private static Dictionary<string, FileData> ParseLcov(string text)
    {
        var files = new Dictionary<string, FileData>(StringComparer.Ordinal);
        FileData? current = null;
        foreach (var raw in text.Split('\n'))
        {
            var line = raw.Trim();
            if (line.StartsWith("SF:", StringComparison.Ordinal))
            {
                var path = Normalise(line[3..]);
                current = files.TryGetValue(path, out var d) ? d : files[path] = new FileData();
            }
            else if (line == "end_of_record") current = null;
            else if (current is not null && line.StartsWith("DA:", StringComparison.Ordinal))
            {
                var parts = line[3..].Split(',');
                if (parts.Length >= 2 && int.TryParse(parts[0], out var number) && long.TryParse(parts[1], out var hits)) current.AddLine(number, hits > 0);
            }
            else if (current is not null && line.StartsWith("BRDA:", StringComparison.Ordinal))
            {
                // BRDA:line,block,branch,taken — taken '-' means never evaluated.
                var parts = line[5..].Split(',');
                if (parts.Length == 4 && int.TryParse(parts[0], out var number))
                {
                    current.AddBranches(number, parts[3] != "-" && long.TryParse(parts[3], out var taken) && taken > 0 ? 1 : 0, 1);
                }
            }
        }

        return files;
    }

    /// <summary>Maps a report's file path to a repository-relative source
    /// path: the longest one it ends with. Null when none, or when two match
    /// equally.</summary>
    public static string? MatchToRepository(string reportPath, IReadOnlyList<string> repositoryFiles)
    {
        var path = "/" + Normalise(reportPath).TrimStart('/');
        var matches = repositoryFiles
            .Where(f => path.EndsWith("/" + f, StringComparison.OrdinalIgnoreCase))
            .GroupBy(f => f.Length).OrderByDescending(g => g.Key).FirstOrDefault()?.ToList();
        return matches is { Count: 1 } ? matches[0] : null;
    }

    private static string Normalise(string path) => path.Trim().Replace('\\', '/');

    private static bool IsRooted(string path) => path.StartsWith('/') || (path.Length > 1 && path[1] == ':');

    private static int Int(XAttribute? attribute) =>
        attribute is not null && int.TryParse(attribute.Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) ? value : 0;
}
