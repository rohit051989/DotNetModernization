using System.Diagnostics;
using System.Text.Json;

namespace Fingerprinting.Analysis;

/// <summary>
/// Progress and timing for a step (rbc-release-5; backend/app/workflow/progress.py is the Python twin).
///
/// At least every <see cref="HeartbeatSeconds"/> seconds, and at every change of phase, the step's position — phase,
/// items done out of the total, the current item — goes to stderr as <c>##progress {json}</c>, which the engine reads
/// for the job page and for stall detection (backend/app/workflow/processes.py). <c>progress.json</c> and
/// <c>timing-profile.json</c> are rewritten in the output folder at the same time, so a step stopped part-way — a time
/// limit, a stall, a crash — leaves behind where it was and where its time went. The profile holds durations and
/// paths only, never code, so a person can share it.
///
/// Thread-safe: projects analysed in parallel each report through the same instance.
/// </summary>
public sealed class StepProgress : IDisposable
{
    public const int HeartbeatSeconds = 10;

    /// <summary>Items reported between heartbeats are written at most this often: thousands of files must not cost a
    /// write each.</summary>
    public const int ItemEmitSeconds = 2;

    private const int Slowest = 25;

    private readonly string? _outputDirectory;
    private readonly TextWriter _stderr;
    private readonly Stopwatch _clock = Stopwatch.StartNew();
    private readonly object _gate = new();
    private readonly List<PhaseTiming> _phases = [];
    private readonly Dictionary<string, List<ItemTiming>> _items = new(StringComparer.Ordinal);
    private readonly List<NotChecked> _notChecked = [];
    private readonly Dictionary<string, TimeSpan> _inFlight = new(StringComparer.Ordinal);
    private readonly Timer _heartbeat;
    private TimeSpan _lastEmit = TimeSpan.MinValue;
    private string _phase = "starting";
    private int _done;
    private int? _total;
    private string? _item;
    private TimeSpan _phaseStarted;
    private bool _finished;

    public StepProgress(string? outputDirectory, TextWriter stderr)
    {
        _outputDirectory = outputDirectory;
        _stderr = stderr;
        _heartbeat = new Timer(_ =>
        {
            Emit();
            Beat?.Invoke();
        }, null, TimeSpan.FromSeconds(HeartbeatSeconds), TimeSpan.FromSeconds(HeartbeatSeconds));
        Emit();
    }

    /// <summary>At every heartbeat, after the progress is written (ProjectCheckpoints records what is in flight).</summary>
    public event Action? Beat;

    /// <summary>The items begun and not yet finished, with how long each has run.</summary>
    public IReadOnlyList<(string Path, double Seconds)> InFlight()
    {
        lock (_gate)
        {
            var now = _clock.Elapsed;
            return _inFlight.Select(kv => (kv.Key, Math.Round((now - kv.Value).TotalSeconds, 1))).OrderBy(x => x.Key, StringComparer.Ordinal).ToList();
        }
    }

    /// <summary>A progress reporter that writes nowhere: for tests and standalone use without an output folder.</summary>
    public static StepProgress Silent() => new(null, TextWriter.Null);

    public void Phase(string name, int? total = null)
    {
        lock (_gate)
        {
            ClosePhase();
            (_phase, _total, _done, _item) = (name, total, 0, null);
        }

        Emit();
    }

    /// <summary>Times one item (a project, a file) of the current phase; disposing it counts the item done.</summary>
    /// <param name="kind">What the slowest-items list groups it under; by default, the phase it is in.</param>
    public IDisposable Item(string path, string? kind = null)
    {
        var started = _clock.Elapsed;
        lock (_gate)
        {
            _item = path;
            kind ??= _phase;
            _inFlight[path] = started;
        }

        return new ItemScope(this, path, kind, started);
    }

    /// <summary>Records one timed piece of work that is not a counted item of the phase (a file within a project).</summary>
    public void Timed(string path, string kind, TimeSpan duration)
    {
        lock (_gate)
        {
            Add(kind, path, duration);
        }
    }

    /// <summary>Something the step could not check, with the reason — reported in the profile.</summary>
    public void RecordNotChecked(string path, string kind, string reason)
    {
        lock (_gate)
        {
            _notChecked.Add(new NotChecked(path, kind, reason));
        }
    }

    public IReadOnlyList<NotChecked> NotCheckedItems
    {
        get
        {
            lock (_gate)
            {
                return _notChecked.ToList();
            }
        }
    }

    public void Finish(string outcome = "completed")
    {
        lock (_gate)
        {
            ClosePhase();
            (_phase, _item, _finished) = (outcome, null, true);
        }

        Emit();
    }

    public void Dispose()
    {
        _heartbeat.Dispose();
        if (!_finished)
        {
            Emit();
        }
    }

    private void Completed(string path, string kind, TimeSpan started)
    {
        lock (_gate)
        {
            Add(kind, path, _clock.Elapsed - started);
            _done++;
            _inFlight.Remove(path);
        }

        Emit(force: false);
    }

    private void Add(string kind, string path, TimeSpan duration)
    {
        if (!_items.TryGetValue(kind, out var list))
        {
            _items[kind] = list = [];
        }

        list.Add(new ItemTiming(path, Math.Round(duration.TotalSeconds, 3)));
    }

    private void ClosePhase()
    {
        var now = _clock.Elapsed;
        if (_phase != "starting")
        {
            _phases.Add(new PhaseTiming(_phase, Math.Round((now - _phaseStarted).TotalSeconds, 3), _done, false));
        }

        _phaseStarted = now;
    }

    private void Emit(bool force = true)
    {
        string progress;
        string? profile = null;
        lock (_gate)
        {
            if (!force && _clock.Elapsed - _lastEmit < TimeSpan.FromSeconds(ItemEmitSeconds))
            {
                return;
            }

            _lastEmit = _clock.Elapsed;
            progress = JsonSerializer.Serialize(new Dictionary<string, object?>
            {
                ["phase"] = _phase, ["done"] = _done, ["total"] = _total, ["item"] = _item,
                ["elapsedSeconds"] = Math.Round(_clock.Elapsed.TotalSeconds, 1),
                ["at"] = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", System.Globalization.CultureInfo.InvariantCulture),
            });
            if (_outputDirectory is not null)
            {
                var phases = _phases.ToList();
                if (!_finished && _phase != "starting")
                {
                    phases.Add(new PhaseTiming(_phase, Math.Round((_clock.Elapsed - _phaseStarted).TotalSeconds, 3), _done, true));
                }

                profile = JsonSerializer.Serialize(new Dictionary<string, object?>
                {
                    ["format"] = 1,
                    ["note"] = "Durations and paths only: no code, no file content, no values.",
                    ["elapsedSeconds"] = Math.Round(_clock.Elapsed.TotalSeconds, 1),
                    ["position"] = new Dictionary<string, object?> { ["phase"] = _phase, ["done"] = _done, ["total"] = _total, ["item"] = _item },
                    ["phases"] = phases.Select(p => new Dictionary<string, object?>
                    {
                        ["phase"] = p.Phase, ["seconds"] = p.Seconds, ["items"] = p.Items, ["running"] = p.Running ? true : null,
                    }),
                    ["slowest"] = _items.ToDictionary(kv => kv.Key, kv => kv.Value.OrderByDescending(i => i.Seconds).Take(Slowest)
                        .Select(i => new Dictionary<string, object?> { ["path"] = i.Path, ["seconds"] = i.Seconds })),
                    ["notChecked"] = _notChecked.Select(n => new Dictionary<string, object?> { ["path"] = n.Path, ["kind"] = n.Kind, ["reason"] = n.Reason }),
                }, new JsonSerializerOptions { WriteIndented = true });
            }
        }

        try
        {
            lock (_stderr)
            {
                _stderr.WriteLine("##progress " + progress);
                _stderr.Flush();
            }

            if (_outputDirectory is not null && profile is not null)
            {
                Directory.CreateDirectory(_outputDirectory);
                File.WriteAllText(Path.Combine(_outputDirectory, "progress.json"), progress);
                File.WriteAllText(Path.Combine(_outputDirectory, "timing-profile.json"), profile);
            }
        }
        catch (IOException)
        {
            // Progress must never fail the step.
        }
    }

    private sealed record PhaseTiming(string Phase, double Seconds, int Items, bool Running);

    private sealed record ItemTiming(string Path, double Seconds);

    public sealed record NotChecked(string Path, string Kind, string Reason);

    private sealed class ItemScope(StepProgress owner, string path, string kind, TimeSpan started) : IDisposable
    {
        private bool _disposed;

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            owner.Completed(path, kind, started);
        }
    }
}
