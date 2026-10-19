using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Fingerprinting.Analysis;

/// <summary>
/// What a step has finished, project by project, kept in a folder that outlives the execution (rbc-release-5), so a
/// rerun after a time limit, a stall or a crash continues from the last completed project instead of starting over.
///
/// The folder belongs to one step and one repository (the engine passes it: <c>checkpoint_dir</c>). Its manifest
/// names what the results were computed from — the step's version and its inputs' checksums — and a different key
/// empties the folder: a result is reused only for exactly the same inputs. Each result is written whole, to a
/// temporary name first, so a crash part-way through writing leaves no half result behind.
/// </summary>
public sealed class ProjectCheckpoints
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    private readonly string? _directory;

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

        return new ProjectCheckpoints(directory);
    }

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

        var path = PathOf(projectPath);
        var temporary = path + ".writing";
        File.WriteAllText(temporary, JsonSerializer.Serialize(value, Json));
        File.Move(temporary, path, overwrite: true);
    }

    /// <summary>Every result is in the artifact now: nothing left to resume.</summary>
    public void Complete()
    {
        if (_directory is not null && Directory.Exists(_directory))
        {
            Directory.Delete(_directory, recursive: true);
        }
    }

    private string PathOf(string projectPath) =>
        Path.Combine(_directory!, "projects", Convert.ToHexString(SHA1.HashData(Encoding.UTF8.GetBytes(projectPath))).ToLowerInvariant() + ".json");
}
