namespace Fingerprinting.Analysis;

/// <summary>
/// Iterative (never recursive, so a deeply nested repository cannot blow the
/// stack) file-system walk shared by every extractor that enumerates a
/// project directory. Same directory exclusions as steps 1 and 2
/// (backend/app/steps/repository_ingest.py SKIP_DIR_NAMES). Extracted from
/// FileIndicatorExtractor so <see cref="SourceFileScanner"/>
/// and ConfigurationExtractor share the identical walk instead
/// of re-implementing it.
/// </summary>
public static class FileSystemWalk
{
    private static readonly HashSet<string> SkipDirNames =
        new(StringComparer.OrdinalIgnoreCase) { ".git", "node_modules", "bin", "obj", "packages" };

    public static IEnumerable<string> EnumerateFiles(string root, CancellationToken cancellationToken)
    {
        foreach (var directory in EnumerateDirectoriesIncludingRoot(root, cancellationToken))
        {
            IEnumerable<string> files;
            try
            {
                files = Directory.EnumerateFiles(directory);
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException or IOException)
            {
                continue;
            }

            foreach (var file in files)
            {
                cancellationToken.ThrowIfCancellationRequested();
                yield return file;
            }
        }
    }

    /// <summary>Project files: a project file in a folder makes that folder, and everything under it, its project's.</summary>
    private static readonly string[] ProjectExtensions = [".csproj", ".vbproj", ".fsproj"];

    /// <summary>
    /// A project's own files (rbc-release-5): its folder, without any subfolder that holds a project file of its own.
    /// A legacy web project's folder often contains every module project (<c>Orchard.Web/Modules/*</c>); walking it
    /// whole read each module's code — generated proxies included — once more for the web project, and analysed it
    /// again there, which made the work grow with the square of the code.
    /// </summary>
    public static IEnumerable<string> EnumerateProjectFiles(string projectDirectory, CancellationToken cancellationToken)
    {
        foreach (var directory in EnumerateDirectoriesIncludingRoot(projectDirectory, cancellationToken, stopAtNestedProjects: true))
        {
            IEnumerable<string> files;
            try
            {
                files = Directory.EnumerateFiles(directory);
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException or IOException)
            {
                continue;
            }

            foreach (var file in files)
            {
                cancellationToken.ThrowIfCancellationRequested();
                yield return file;
            }
        }
    }

    /// <summary>Whether a folder holds a project file of its own.</summary>
    public static bool HoldsProject(string directory)
    {
        try
        {
            return Directory.EnumerateFiles(directory).Any(f => ProjectExtensions.Contains(Path.GetExtension(f), StringComparer.OrdinalIgnoreCase));
        }
        catch (Exception ex) when (ex is UnauthorizedAccessException or IOException)
        {
            return false;
        }
    }

    public static IEnumerable<string> EnumerateDirectories(string root, CancellationToken cancellationToken) =>
        EnumerateDirectoriesIncludingRoot(root, cancellationToken)
            .Where(d => !string.Equals(d, root, StringComparison.OrdinalIgnoreCase));

    public static IEnumerable<string> EnumerateDirectoriesIncludingRoot(
        string root, CancellationToken cancellationToken, bool stopAtNestedProjects = false)
    {
        var stack = new Stack<string>();
        stack.Push(root);

        while (stack.Count > 0)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var current = stack.Pop();
            yield return current;

            IEnumerable<string> children;
            try
            {
                children = Directory.EnumerateDirectories(current);
            }
            catch (Exception ex) when (ex is UnauthorizedAccessException or IOException)
            {
                continue;
            }

            foreach (var child in children)
            {
                if (!SkipDirNames.Contains(Path.GetFileName(child)) && !(stopAtNestedProjects && HoldsProject(child)))
                {
                    stack.Push(child);
                }
            }
        }
    }

    public static string ToRepositoryRelativePath(string repositoryRoot, string absolutePath) =>
        Path.GetRelativePath(repositoryRoot, absolutePath).Replace('\\', '/');
}
