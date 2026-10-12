using Npgsql;

namespace Fingerprinting.StepHost;

/// <summary>
/// The platform rows a step reads but does not own: the repository's local
/// path and project ids. Each step writes its own tables through its own
/// class. Upstream facts arrive as artifacts through <c>inputs</c>, never
/// from another step's tables.
/// </summary>
public sealed class PlatformDatabase(string connectionString)
{
    public string ConnectionString { get; } = connectionString;

    public async Task<string?> GetRepositoryLocalPathAsync(Guid repositoryId, CancellationToken cancellationToken)
    {
        await using var connection = new NpgsqlConnection(ConnectionString);
        await connection.OpenAsync(cancellationToken);

        await using var command = new NpgsqlCommand("SELECT local_path FROM repositories WHERE id = @rid", connection);
        command.Parameters.AddWithValue("rid", repositoryId);

        return (string?)await command.ExecuteScalarAsync(cancellationToken);
    }

    /// <summary>The repository's engagement's target framework
    /// (engagements.target_framework); null when it has none.</summary>
    public async Task<string?> GetTargetFrameworkAsync(Guid repositoryId, CancellationToken cancellationToken)
    {
        await using var connection = new NpgsqlConnection(ConnectionString);
        await connection.OpenAsync(cancellationToken);
        await using var command = new NpgsqlCommand(
            "SELECT e.target_framework FROM repositories r JOIN engagements e ON e.id = r.engagement_id WHERE r.id = @rid", connection);
        command.Parameters.AddWithValue("rid", repositoryId);
        return await command.ExecuteScalarAsync(cancellationToken) as string;
    }

    /// <summary>The repository's engagement's SetParameters globs
    /// (engagements.deploy_parameter_globs) — steps 3 and 5. Empty when none
    /// are set, which means <c>DeployParameterFiles.DefaultGlobs</c>.</summary>
    public async Task<IReadOnlyList<string>> GetDeployParameterGlobsAsync(Guid repositoryId, CancellationToken cancellationToken)
    {
        await using var connection = new NpgsqlConnection(ConnectionString);
        await connection.OpenAsync(cancellationToken);
        await using var command = new NpgsqlCommand(
            "SELECT e.deploy_parameter_globs::text FROM repositories r JOIN engagements e ON e.id = r.engagement_id WHERE r.id = @rid", connection);
        command.Parameters.AddWithValue("rid", repositoryId);
        return await command.ExecuteScalarAsync(cancellationToken) is string json
            ? System.Text.Json.JsonSerializer.Deserialize<List<string>>(json) ?? []
            : [];
    }

    /// <summary>Resolves each project's DB row id by (repository_id,
    /// relative_path) — step 2's artifact itself carries no project id; see
    /// SolutionProjectInventory.cs.</summary>
    public async Task<Dictionary<string, Guid>> ResolveProjectIdsAsync(
        Guid repositoryId, CancellationToken cancellationToken)
    {
        await using var connection = new NpgsqlConnection(ConnectionString);
        await connection.OpenAsync(cancellationToken);

        var map = new Dictionary<string, Guid>(StringComparer.Ordinal);
        await using var command = new NpgsqlCommand(
            "SELECT relative_path, id FROM projects WHERE repository_id = @rid", connection);
        command.Parameters.AddWithValue("rid", repositoryId);

        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            map[reader.GetString(0)] = reader.GetGuid(1);
        }

        return map;
    }
}
