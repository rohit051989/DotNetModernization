using System.Text.RegularExpressions;
using Fingerprinting.Domain;

namespace Fingerprinting.Extractors;

/// <summary>
/// Presence is not readiness (registry 1.11.0). An existing Dockerfile or OpenShift / Kubernetes manifest is read
/// for what OpenShift's restricted security context constraint (restricted-v2) refuses or breaks:
/// <list type="bullet">
/// <item><b>CONTAINER_RUNS_AS_ROOT</b> — the image's final stage never switches to a non-root user, or switches to
/// root; a manifest that sets runAsUser: 0, runAsNonRoot: false, privileged: true or allowPrivilegeEscalation: true.</item>
/// <item><b>CONTAINER_PRIVILEGED_PORT</b> — a port below 1024: EXPOSE 80, a listening URL or port variable
/// (ASPNETCORE_URLS, ASPNETCORE_HTTP_PORTS, HTTP_PORTS) in the final stage, or a manifest's containerPort.</item>
/// <item><b>CONTAINER_FIXED_USER_WRITABLE_PATH</b> — writable paths that assume a fixed user: a chown in the final
/// stage to an owner whose group is not 0 with no later chmod giving the group the owner's rights (OpenShift runs
/// the image with an arbitrary UID in group 0), a chmod that leaves the group without write (700, 600), or a
/// manifest's fixed runAsUser / fsGroup (restricted-v2 assigns them from the project's range).</item>
/// </list>
/// Each finding is the instruction or line as written, with its line. Text only: nothing is built or run.
/// </summary>
public static class ContainerSecurity
{
    public const string RunsAsRoot = "CONTAINER_RUNS_AS_ROOT";
    public const string PrivilegedPort = "CONTAINER_PRIVILEGED_PORT";
    public const string FixedUserWritablePath = "CONTAINER_FIXED_USER_WRITABLE_PATH";

    public sealed record Finding(string Signal, string Value, int Line);

    private static readonly Regex Instruction = new(@"^\s*(?<op>[A-Za-z]+)\s+(?<args>.*)$", RegexOptions.CultureInvariant);
    private static readonly Regex PortInUrl = new(@"(?:https?://[^:/\s;]+:|^|[;,\s])(?<port>\d{1,5})(?=[/;,\s""]|$)", RegexOptions.CultureInvariant);
    private static readonly Regex Chown = new(@"\bchown\b(?:\s+-[A-Za-z]+)*\s+(?<owner>[^\s:]+)(?::(?<group>\S+))?", RegexOptions.CultureInvariant);
    private static readonly Regex GroupGetsOwnerRights = new(@"\bchmod\b[^;&|]*\bg(?:=u|\+[rwxX]*w)", RegexOptions.CultureInvariant);
    private static readonly Regex OwnerOnlyMode = new(@"\bchmod\b(?:\s+-[A-Za-z]+)*\s+0?[67]00\b", RegexOptions.CultureInvariant);
    private static readonly Regex YamlKey = new(@"^\s*-?\s*(?<key>[A-Za-z]+)\s*:\s*(?<value>[^#]*?)\s*(?:#.*)?$", RegexOptions.CultureInvariant);

    /// <summary>Findings in a Dockerfile: only its final stage runs, together with every earlier stage it is built
    /// FROM by name — <c>FROM base AS final</c> inherits <c>base</c>'s EXPOSE, ENV and USER.</summary>
    public static IReadOnlyList<Finding> Dockerfile(string text)
    {
        var lines = ReadLines(text);
        var finalFrom = lines.FindLastIndex(l => Op(l.Text) == "FROM");
        var stage = finalFrom < 0 ? lines : RuntimeStage(lines, finalFrom);
        var findings = new List<Finding>();

        var users = stage.Where(l => Op(l.Text) == "USER").ToList();
        if (users.Count == 0)
        {
            var from = finalFrom < 0 ? 1 : lines[finalFrom].Line;
            findings.Add(new Finding(RunsAsRoot, "no USER instruction: the image runs as root", from));
        }
        else
        {
            var last = users[^1];
            var user = Args(last.Text).Split(':')[0].Trim();
            if (user is "root" or "0")
            {
                findings.Add(new Finding(RunsAsRoot, last.Text.Trim(), last.Line));
            }
        }

        foreach (var line in stage)
        {
            var op = Op(line.Text);
            var args = Args(line.Text);
            if (op == "EXPOSE")
            {
                foreach (var port in args.Split(' ', StringSplitOptions.RemoveEmptyEntries).Select(p => p.Split('/')[0]))
                {
                    if (int.TryParse(port, out var n) && n < 1024) findings.Add(new Finding(PrivilegedPort, $"EXPOSE {port}", line.Line));
                }
            }
            else if (op == "ENV")
            {
                foreach (Match m in Regex.Matches(args, @"(?<name>ASPNETCORE_URLS|ASPNETCORE_HTTP_PORTS|ASPNETCORE_HTTPS_PORTS|HTTP_PORTS|HTTPS_PORTS)[= ]\s*""?(?<value>[^""\s\\]+)"))
                {
                    foreach (Match p in PortInUrl.Matches(m.Groups["value"].Value))
                    {
                        if (int.TryParse(p.Groups["port"].Value, out var n) && n < 1024)
                        {
                            findings.Add(new Finding(PrivilegedPort, $"{m.Groups["name"].Value}={m.Groups["value"].Value}", line.Line));
                        }
                    }
                }
            }
            else if (op == "RUN")
            {
                // A later chmod giving group 0 the owner's rights (chmod -R g=u) makes the paths writable for any UID.
                var groupFixedLater = stage.SkipWhile(l => l.Line < line.Line)
                    .Any(l => Op(l.Text) == "RUN" && GroupGetsOwnerRights.IsMatch(Args(l.Text)));
                if (groupFixedLater) continue;
                if (OwnerOnlyMode.Match(args) is { Success: true } mode)
                {
                    findings.Add(new Finding(FixedUserWritablePath, mode.Value.Trim(), line.Line));
                }

                foreach (Match chown in Chown.Matches(args))
                {
                    var group = chown.Groups["group"].Success ? chown.Groups["group"].Value : null;
                    if (group is not ("0" or "root")) findings.Add(new Finding(FixedUserWritablePath, chown.Value.Trim(), line.Line));
                }
            }
        }

        return findings;
    }

    /// <summary>Findings in an OpenShift / Kubernetes manifest, line by line.</summary>
    public static IReadOnlyList<Finding> Manifest(string text)
    {
        var findings = new List<Finding>();
        var number = 0;
        foreach (var raw in text.Split('\n'))
        {
            number++;
            var m = YamlKey.Match(raw.TrimEnd('\r'));
            if (!m.Success) continue;
            var key = m.Groups["key"].Value;
            var value = m.Groups["value"].Value.Trim().Trim('"', '\'');
            switch (key)
            {
                case "runAsUser" when value == "0":
                case "runAsNonRoot" when value.Equals("false", StringComparison.OrdinalIgnoreCase):
                case "privileged" when value.Equals("true", StringComparison.OrdinalIgnoreCase):
                case "allowPrivilegeEscalation" when value.Equals("true", StringComparison.OrdinalIgnoreCase):
                    findings.Add(new Finding(RunsAsRoot, $"{key}: {value}", number));
                    break;
                case "runAsUser" when int.TryParse(value, out var uid) && uid > 0:
                case "fsGroup" when int.TryParse(value, out _):
                    findings.Add(new Finding(FixedUserWritablePath, $"{key}: {value}", number));
                    break;
                case "containerPort" when int.TryParse(value, out var port) && port < 1024:
                    findings.Add(new Finding(PrivilegedPort, $"containerPort: {value}", number));
                    break;
            }
        }

        return findings;
    }

    public static IEnumerable<Signal> Signals(IReadOnlyList<Finding> findings, string sourcePath, string extractor) =>
        findings.GroupBy(f => (f.Signal, f.Value)).Select(g => new Signal
        {
            Name = g.Key.Signal,
            Category = SignalCategories.DeploymentIndicator,
            Type = SignalTypes.ConfigElement,
            Value = g.Key.Value,
            SourceType = EvidenceSourceTypes.DeploymentScript,
            SourcePath = sourcePath,
            OccurrenceCount = g.Count(),
            Evidence = g.Select(f => new Evidence { LineStart = f.Line, LineEnd = f.Line }).ToList(),
            Extractor = extractor,
            ExtractionConfidence = 0.90m,
        });

    // ---- Dockerfile lines: continuation lines joined, comments dropped, each with its first line number.
    private sealed record Logical(string Text, int Line);

    private static List<Logical> ReadLines(string text)
    {
        var result = new List<Logical>();
        var buffer = new List<string>();
        var start = 0;
        var number = 0;
        foreach (var raw in text.Replace("\r\n", "\n").Split('\n'))
        {
            number++;
            var line = raw.TrimEnd();
            if (buffer.Count == 0)
            {
                if (line.TrimStart().StartsWith('#') || line.Length == 0) continue;
                start = number;
            }
            else if (line.TrimStart().StartsWith('#'))
            {
                continue;
            }

            if (line.EndsWith('\\'))
            {
                buffer.Add(line[..^1]);
                continue;
            }

            buffer.Add(line);
            result.Add(new Logical(string.Join(' ', buffer.Select(b => b.Trim())), start));
            buffer.Clear();
        }

        if (buffer.Count > 0) result.Add(new Logical(string.Join(' ', buffer.Select(b => b.Trim())), start));
        return result;
    }

    /// <summary>The final stage's instructions, preceded by those of each stage it names in its FROM, oldest first.</summary>
    private static List<Logical> RuntimeStage(List<Logical> lines, int finalFrom)
    {
        var froms = lines.Select((l, i) => (l, i)).Where(x => Op(x.l.Text) == "FROM").Select(x => x.i).ToList();
        List<Logical> StageAt(int from) => lines.Skip(from).Take((froms.FirstOrDefault(f => f > from, lines.Count)) - from).ToList();

        var chain = new List<List<Logical>> { StageAt(finalFrom) };
        var current = finalFrom;
        for (var depth = 0; depth < froms.Count; depth++)
        {
            var image = Args(lines[current].Text).Split(' ', StringSplitOptions.RemoveEmptyEntries)
                .FirstOrDefault(a => !a.StartsWith("--", StringComparison.Ordinal));
            var parent = froms.Where(f => f < current).LastOrDefault(f => Alias(lines[f].Text) is { } alias
                                                                         && alias.Equals(image, StringComparison.OrdinalIgnoreCase), -1);
            if (parent < 0) break;
            chain.Insert(0, StageAt(parent));
            current = parent;
        }

        return chain.SelectMany(s => s).ToList();
    }

    private static string? Alias(string from)
    {
        var parts = Args(from).Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var at = Array.FindIndex(parts, p => p.Equals("AS", StringComparison.OrdinalIgnoreCase));
        return at >= 0 && at + 1 < parts.Length ? parts[at + 1] : null;
    }

    private static string Op(string line) => Instruction.Match(line) is { Success: true } m ? m.Groups["op"].Value.ToUpperInvariant() : "";

    private static string Args(string line) => Instruction.Match(line) is { Success: true } m ? m.Groups["args"].Value : "";
}
