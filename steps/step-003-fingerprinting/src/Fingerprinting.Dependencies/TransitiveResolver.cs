using System.Diagnostics;
using System.Text.Json;
using System.Xml.Linq;

namespace Fingerprinting.Dependencies;

public sealed record TransitiveResult(IReadOnlyList<(string Id, string Version)> Packages, string? Error);

/// <summary>
/// Part B5: transitive dependencies are resolved by restoring a <b>copy</b>
/// of the project file, its NuGet.config files and its Directory.*.props /
/// .targets in a scratch directory — never in place, so the repository's
/// obj/ and project.assets.json are never written. Project references are
/// removed from the copy (their projects are not copied), so the result is
/// this project's own package graph. SDK-style projects only: a
/// packages.config project already lists every package it uses.
/// </summary>
public sealed class TransitiveResolver(string scratchRoot, string packagesDirectory, TimeSpan timeout)
{
    private static readonly string[] CopiedNames =
        ["nuget.config", "Directory.Build.props", "Directory.Build.targets", "Directory.Packages.props"];

    public async Task<TransitiveResult> ResolveAsync(string repositoryRoot, string projectPath, CancellationToken ct)
    {
        var source = Path.Combine(repositoryRoot, projectPath.Replace('/', Path.DirectorySeparatorChar));
        XDocument project;
        try
        {
            project = XDocument.Load(source);
        }
        catch (Exception ex) when (ex is IOException or System.Xml.XmlException)
        {
            return new TransitiveResult([], $"could not read {projectPath}: {ex.Message}");
        }

        if (project.Root?.Attribute("Sdk") is null && !project.Root!.Elements().Any(e => e.Name.LocalName == "Sdk"))
        {
            return new TransitiveResult([], $"{projectPath} is not SDK-style; its packages.config already lists every package");
        }

        var scratch = Path.Combine(scratchRoot, Guid.NewGuid().ToString("N"));
        try
        {
            // The project file, without its project references.
            var copy = Path.Combine(scratch, projectPath.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(copy)!);
            project.Descendants().Where(e => e.Name.LocalName == "ProjectReference").Remove();
            project.Save(copy);

            // Its configuration, from the project directory up to the repository root.
            var root = Path.GetFullPath(repositoryRoot).TrimEnd(Path.DirectorySeparatorChar);
            for (var directory = new DirectoryInfo(Path.GetDirectoryName(source)!); directory is not null; directory = directory.Parent)
            {
                foreach (var file in directory.EnumerateFiles().Where(f => CopiedNames.Contains(f.Name, StringComparer.OrdinalIgnoreCase)))
                {
                    var target = Path.Combine(scratch, Path.GetRelativePath(root, file.FullName));
                    Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                    File.Copy(file.FullName, target, overwrite: true);
                }

                if (directory.FullName.TrimEnd(Path.DirectorySeparatorChar).Equals(root, StringComparison.OrdinalIgnoreCase)) break;
            }

            var start = new ProcessStartInfo("dotnet", ["restore", copy, "--packages", packagesDirectory, "--verbosity", "quiet", "--nologo"])
            {
                WorkingDirectory = scratch,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            start.Environment["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1";
            start.Environment["DOTNET_NOLOGO"] = "1";
            using var process = Process.Start(start)!;
            using var timer = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timer.CancelAfter(timeout);
            // Both pipes are read, so a chatty restore never blocks on a full one; over the time limit, or when the
            // step is stopped, the restore and everything it started end (rbc-release-5).
            var output = process.StandardOutput.ReadToEndAsync(CancellationToken.None);
            var errors = process.StandardError.ReadToEndAsync(CancellationToken.None);
            try
            {
                await process.WaitForExitAsync(timer.Token);
            }
            catch (OperationCanceledException)
            {
                try
                {
                    process.Kill(entireProcessTree: true);
                }
                catch (InvalidOperationException)
                {
                    // Already exited.
                }

                throw;
            }

            await Task.WhenAll(output, errors);
            if (process.ExitCode != 0)
            {
                var text = (await output).Split('\n').FirstOrDefault(l => l.Contains("error", StringComparison.OrdinalIgnoreCase))?.Trim();
                return new TransitiveResult([], $"restore of a scratch copy of {projectPath} failed{(text is null ? "" : ": " + text)}");
            }

            var assets = Path.Combine(Path.GetDirectoryName(copy)!, "obj", "project.assets.json");
            using var document = JsonDocument.Parse(await File.ReadAllTextAsync(assets, ct));
            var packages = document.RootElement.GetProperty("libraries").EnumerateObject()
                .Where(l => l.Value.TryGetProperty("type", out var type) && type.GetString() == "package")
                .Select(l => (Id: l.Name[..l.Name.IndexOf('/')], Version: l.Name[(l.Name.IndexOf('/') + 1)..]))
                .OrderBy(p => p.Id, StringComparer.OrdinalIgnoreCase)
                .ToList();
            return new TransitiveResult(packages, null);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            return new TransitiveResult([], $"restore of a scratch copy of {projectPath} timed out");
        }
        finally
        {
            try
            {
                Directory.Delete(scratch, recursive: true);
            }
            catch (IOException)
            {
                // Scratch is outside the repository; a leftover is harmless.
            }
        }
    }
}
