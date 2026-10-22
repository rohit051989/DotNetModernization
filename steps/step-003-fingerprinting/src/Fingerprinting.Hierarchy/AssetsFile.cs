using System.Text.Json;
using NuGet.Frameworks;

namespace Fingerprinting.Hierarchy;

/// <summary>One package as restore resolved it for one framework: its version, and what it depends on (id → range as
/// the package asks).</summary>
public sealed record RestoredPackage(string Id, string Version, IReadOnlyDictionary<string, string> Dependencies);

/// <summary>
/// A project's restored <c>obj/project.assets.json</c> (37-DEPENDENCY-HIERARCHY.md Part B4): where one exists, what
/// restore actually chose — every package's version and its own dependencies — for the project's framework. Read only;
/// never written, never created: the step does not restore. A file restore wrote before the project last changed can
/// be stale; the artifact says which edges came from it.
/// </summary>
public sealed record AssetsFile(string Framework, IReadOnlyDictionary<string, RestoredPackage> Packages)
{
    /// <summary>The restored packages for <paramref name="framework"/> (or the file's only framework), or null with the
    /// reason when there is no usable file.</summary>
    public static (AssetsFile? File, string? Reason) Read(string projectDirectory, string? framework)
    {
        var path = Path.Combine(projectDirectory, "obj", "project.assets.json");
        if (!File.Exists(path)) return (null, "no obj/project.assets.json: the project has not been restored here");

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(path));
            if (!document.RootElement.TryGetProperty("targets", out var targets) || targets.ValueKind != JsonValueKind.Object)
            {
                return (null, "obj/project.assets.json has no targets");
            }

            var candidates = targets.EnumerateObject().Where(t => !t.Name.Contains('/')).ToList();  // a RID-specific target repeats one without
            var wanted = framework is null ? null : NuGetFramework.Parse(framework);
            var target = candidates.Count == 1
                ? candidates[0]
                : candidates.FirstOrDefault(t => wanted is not null && NuGetFramework.Parse(t.Name).Equals(wanted));
            if (target.Value.ValueKind != JsonValueKind.Object)
            {
                return (null, $"obj/project.assets.json has no target for {framework ?? "the project's framework"}");
            }

            var packages = new Dictionary<string, RestoredPackage>(StringComparer.OrdinalIgnoreCase);
            foreach (var entry in target.Value.EnumerateObject())
            {
                if (!entry.Value.TryGetProperty("type", out var type) || type.GetString() != "package") continue;
                var slash = entry.Name.IndexOf('/');
                if (slash <= 0) continue;
                var dependencies = new SortedDictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                if (entry.Value.TryGetProperty("dependencies", out var deps) && deps.ValueKind == JsonValueKind.Object)
                {
                    foreach (var dep in deps.EnumerateObject()) dependencies[dep.Name] = dep.Value.GetString() ?? "";
                }

                var id = entry.Name[..slash];
                packages[id] = new RestoredPackage(id, entry.Name[(slash + 1)..], dependencies);
            }

            return (new AssetsFile(NuGetFramework.Parse(target.Name).GetShortFolderName(), packages), null);
        }
        catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException or ArgumentException)
        {
            return (null, $"obj/project.assets.json could not be read: {ex.Message}");
        }
    }
}
