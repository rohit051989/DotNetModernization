namespace Fingerprinting.Extractors;

/// <summary>
/// Iterative (never recursive, so a deeply nested repository cannot blow the
/// stack) file-system walk shared by every extractor that enumerates a
/// project directory. Same directory exclusions as steps 1 and 2
/// (backend/app/steps/repository_ingest.py SKIP_DIR_NAMES). Extracted from
/// <see cref="FileIndicatorExtractor"/> so <see cref="SourceFileScanner"/>
/// and <see cref="ConfigurationExtractor"/> share the identical walk instead
/// of re-implementing it.
/// </summary>
internal static class FileSystemWalk
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

    public static IEnumerable<string> EnumerateDirectories(string root, CancellationToken cancellationToken) =>
        EnumerateDirectoriesIncludingRoot(root, cancellationToken)
            .Where(d => !string.Equals(d, root, StringComparison.OrdinalIgnoreCase));

    public static IEnumerable<string> EnumerateDirectoriesIncludingRoot(string root, CancellationToken cancellationToken)
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
                if (!SkipDirNames.Contains(Path.GetFileName(child)))
                {
                    stack.Push(child);
                }
            }
        }
    }

    public static string ToRepositoryRelativePath(string repositoryRoot, string absolutePath) =>
        Path.GetRelativePath(repositoryRoot, absolutePath).Replace('\\', '/');
}
