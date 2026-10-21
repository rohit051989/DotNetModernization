using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Fingerprinting.Analysis;

/// <summary>
/// What a step has finished, project by project, kept in a folder that outlives the execution (release 5), so a
/// rerun after a time limit, a stall or a crash continues from the last completed project instead of starting over.
///
/// The folder belongs to one step and one repository (the engine passes it: <c>checkpoint_dir</c>). Its manifest
/// names what the results were computed from — the step's version and its inputs' checksums — and a different key
/// empties the folder: a result is reused only for exactly the same inputs. Each result is written whole, to a
/// temporary name first, so a crash part-way through writing leaves no half result behind.
///
/// A resume never runs into the same wall twice. A project recorded "not checked" (over its time limit) is kept as
/// such; and a project that was still being analysed after <see cref="SuspectSeconds"/> when the run stopped — what a
/// time limit, a stall or a crash stopped on — is not retried automatically either (<c>inflight.json</c>, written at
/// every heartbeat by <see cref="Watch"/>). Both are listed in <c>skip.json</c>. A person retries them by removing it
/// (<c>python -m app.workflow.time_limits retry</c>), or by changing the project time limit, which starts afresh.
/// </summary>
public sealed class ProjectCheckpoints
{
    /// <summary>In flight this long when the run stopped: the project it was stuck on.</summary>
    public const int SuspectSeconds = 60;

    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    private readonly string? _directory;
    private readonly Dictionary<string, string> _skip = new(StringComparer.Ordinal);
    private StepProgress? _watched;

    private ProjectCheckpoints(string? directory) => _directory = directory;

    /// <summary>No checkpoints: every project is computed.</summary>
    public static ProjectCheckpoints None { get; } = new(null);

    /// <summary>How many results came from an earlier, unfinished run.</summary>
    public int Reused { get; private set; }

    public static ProjectCheckpoints Open(string? directory, string key)
    {
        if (string.IsNullOrEmpty(directory))
        {
            return None;
        }

        var manifest = Path.Combine(directory, "manifest.json");
        var existing = File.Exists(manifest) ? File.ReadAllText(manifest) : null;
        var wanted = JsonSerializer.Serialize(new { key });
        if (existing != wanted)
        {
            if (Directory.Exists(directory))
            {
                Directory.Delete(directory, recursive: true);
            }

            Directory.CreateDirectory(Path.Combine(directory, "projects"));
            File.WriteAllText(manifest, wanted);
        }

        var checkpoints = new ProjectCheckpoints(directory);
        checkpoints.ReadSkips();
        return checkpoints;
    }

    /// <summary>The projects the previous run recorded as not checked, and those it was stuck on when it stopped.</summary>
    private void ReadSkips()
    {
        var skipFile = Path.Combine(_directory!, "skip.json");
        if (File.Exists(skipFile))
        {
            try
            {
                foreach (var (path, reason) in JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(skipFile)) ?? [])
                {
                    _skip[path] = reason;
                }
            }
            catch (JsonException)
            {
                // An unreadable list retries everything.
            }
        }

        var inflightFile = Path.Combine(_directory!, "inflight.json");
        if (File.Exists(inflightFile))
        {
            try
            {
                foreach (var item in JsonSerializer.Deserialize<List<InFlightItem>>(File.ReadAllText(inflightFile), Json) ?? [])
                {
                    if (item.Seconds >= SuspectSeconds)
                    {
                        _skip.TryAdd(item.Path, $"not checked: not retried — it was still being analysed after {item.Seconds:0} s when the " +
                                                "previous run stopped (a time limit, a stall or a crash); retry it with " +
                                                "python -m app.workflow.time_limits retry, or with a different project time limit");
                    }
                }
            }
            catch (JsonException)
            {
                // Nothing known about the previous run.
            }

            File.Delete(inflightFile);
        }

        WriteSkips();
    }

    /// <summary>True when <paramref name="projectPath"/> is not to be retried, with the reason to record.</summary>
    public bool Skipped(string projectPath, out string reason)
    {
        lock (_skip)
        {
            if (_skip.TryGetValue(projectPath, out var why))
            {
                reason = why.StartsWith("not checked", StringComparison.Ordinal) ? why : $"not checked: not retried — {why}";
                return true;
            }
        }

        reason = "";
        return false;
    }

    /// <summary>Records a project as not checked, so a resume does not retry it.</summary>
    public void MarkNotChecked(string projectPath, string reason)
    {
        if (_directory is null)
        {
            return;
        }

        lock (_skip)
        {
            _skip[projectPath] = reason;
            WriteSkips();
        }
    }

    /// <summary>Writes what is in flight at every heartbeat of <paramref name="progress"/>, so a run stopped from
    /// outside leaves behind what it was stuck on.</summary>
    public void Watch(StepProgress progress)
    {
        if (_directory is null || _watched is not null)
        {
            return;
        }

        _watched = progress;
        progress.Beat += () =>
        {
            try
            {
                WriteWhole(Path.Combine(_directory, "inflight.json"),
                    JsonSerializer.Serialize(progress.InFlight().Select(x => new InFlightItem(x.Path, x.Seconds)).ToList(), Json));
            }
            catch (IOException)
            {
                // Best effort: progress never fails the step.
            }
        };
    }

    private void WriteSkips()
    {
        if (_directory is null)
        {
            return;
        }

        var ordered = _skip.OrderBy(kv => kv.Key, StringComparer.Ordinal).ToDictionary(kv => kv.Key, kv => kv.Value);
        WriteWhole(Path.Combine(_directory, "skip.json"), JsonSerializer.Serialize(ordered, new JsonSerializerOptions { WriteIndented = true }));
    }

    private static void WriteWhole(string path, string text)
    {
        var temporary = path + ".writing";
        File.WriteAllText(temporary, text);
        File.Move(temporary, path, overwrite: true);
    }

    private sealed record InFlightItem(string Path, double Seconds);

    /// <summary>A key over the step version and the given inputs (artifact checksums, settings that change results).</summary>
    public static string Key(params string?[] parts) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join("\n", parts.Select(p => p ?? "-"))))).ToLowerInvariant();

    public bool TryGet<T>(string projectPath, out T? value)
    {
        value = default;
        if (_directory is null)
        {
            return false;
        }

        var path = PathOf(projectPath);
        if (!File.Exists(path))
        {
            return false;
        }

        try
        {
            value = JsonSerializer.Deserialize<T>(File.ReadAllText(path), Json);
            if (value is not null)
            {
                lock (this)
                {
                    Reused++;
                }
            }

            return value is not null;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    public void Save<T>(string projectPath, T value)
    {
        if (_directory is null)
        {
            return;
        }

        WriteWhole(PathOf(projectPath), JsonSerializer.Serialize(value, Json));
    }

    /// <summary>Every result is in the artifact now: nothing left to resume.</summary>
    public void Complete()
    {
        if (_directory is not null && Directory.Exists(_directory))
        {
            lock (_skip)
            {
                Directory.Delete(_directory, recursive: true);
            }
        }
    }

    private string PathOf(string projectPath) =>
        Path.Combine(_directory!, "projects", Convert.ToHexString(SHA1.HashData(Encoding.UTF8.GetBytes(projectPath))).ToLowerInvariant() + ".json");
}
