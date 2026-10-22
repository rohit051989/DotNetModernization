using System.Text.Json;
using Fingerprinting.Dependencies.Cli;
using Fingerprinting.Domain;
using Fingerprinting.Hierarchy;
using Npgsql;
using NpgsqlTypes;

namespace Fingerprinting.Hierarchy.Cli;

/// <summary>
/// Npgsql persistence for 37-DEPENDENCY-HIERARCHY.md Part D, in one transaction per repository: the repository's
/// <c>hierarchy_nodes</c> and <c>hierarchy_edges</c>, replaced wholesale, and the <c>package_lookup_cache</c> entries
/// this run fetched. The UI loads a node's children from these tables when it is expanded, never the whole graph.
/// </summary>
public sealed class HierarchyDatabase(string connectionString)
{
    /// <summary>Internal packages whose producing repository estate consolidation found (dependency_edges, edge kind
    /// internal_package), keyed by lower-case package id. Empty before the estate has been consolidated.</summary>
    public async Task<Dictionary<string, PackageProducer>> GetProducersAsync(Guid repositoryId, CancellationToken ct)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(ct);
        await using var command = new NpgsqlCommand(
            """
            SELECT DISTINCT ON (lower(e.via_package)) lower(e.via_package), r.id, r.name, tp.relative_path
            FROM dependency_edges e
            JOIN projects fp ON fp.id = e.from_project_id
            JOIN projects tp ON tp.id = e.to_project_id
            JOIN repositories r ON r.id = tp.repository_id
            WHERE e.edge_kind = 'internal_package' AND e.via_package IS NOT NULL AND fp.repository_id = @rid
            ORDER BY lower(e.via_package), r.name, tp.relative_path
            """, connection);
        command.Parameters.AddWithValue("rid", repositoryId);
        var producers = new Dictionary<string, PackageProducer>(StringComparer.Ordinal);
        await using var reader = await command.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct))
        {
            producers[reader.GetString(0)] = new PackageProducer
            {
                RepositoryId = reader.GetGuid(1),
                RepositoryName = reader.GetString(2),
                ProjectPath = reader.GetString(3),
            };
        }

        return producers;
    }

    public async Task ReplaceAllAsync(DependencyHierarchyArtifact artifact, PostgresLookupCache cache, Guid? stepExecutionId, CancellationToken ct)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(ct);
        await using var transaction = await connection.BeginTransactionAsync(ct);
        foreach (var table in new[] { "hierarchy_edges", "hierarchy_nodes" })
        {
            await using var delete = new NpgsqlCommand($"DELETE FROM {table} WHERE repository_id = @rid", connection, transaction);
            delete.Parameters.AddWithValue("rid", artifact.RepositoryId);
            await delete.ExecuteNonQueryAsync(ct);
        }

        // COPY, inside the transaction: a large repository's graph is tens of thousands of rows.
        var roots = artifact.Roots.ToHashSet(StringComparer.Ordinal);
        await using (var importer = await connection.BeginBinaryImportAsync(
                         "COPY hierarchy_nodes (repository_id, node_id, node_type, name, status, is_root, project_id, detail, step_execution_id) FROM STDIN (FORMAT BINARY)", ct))
        {
            foreach (var node in artifact.Nodes)
            {
                await importer.StartRowAsync(ct);
                await importer.WriteAsync(artifact.RepositoryId, NpgsqlDbType.Uuid, ct);
                await importer.WriteAsync(node.Id, NpgsqlDbType.Text, ct);
                await importer.WriteAsync(node.Type, NpgsqlDbType.Text, ct);
                await importer.WriteAsync(node.Name, NpgsqlDbType.Text, ct);
                await importer.WriteAsync(node.Status, NpgsqlDbType.Text, ct);
                await importer.WriteAsync(roots.Contains(node.Id), NpgsqlDbType.Boolean, ct);
                if (node.Project?.ProjectId is { } projectId) await importer.WriteAsync(projectId, NpgsqlDbType.Uuid, ct);
                else await importer.WriteNullAsync(ct);
                await importer.WriteAsync(Json(node), NpgsqlDbType.Jsonb, ct);
                if (stepExecutionId is { } sid) await importer.WriteAsync(sid, NpgsqlDbType.Uuid, ct);
                else await importer.WriteNullAsync(ct);
            }

            await importer.CompleteAsync(ct);
        }

        await using (var importer = await connection.BeginBinaryImportAsync(
                         "COPY hierarchy_edges (repository_id, from_node, to_node, kind, resolution, closes_cycle, detail) FROM STDIN (FORMAT BINARY)", ct))
        {
            foreach (var edge in artifact.Edges)
            {
                await importer.StartRowAsync(ct);
                await importer.WriteAsync(artifact.RepositoryId, NpgsqlDbType.Uuid, ct);
                await importer.WriteAsync(edge.From, NpgsqlDbType.Text, ct);
                await importer.WriteAsync(edge.To, NpgsqlDbType.Text, ct);
                await importer.WriteAsync(edge.Kind, NpgsqlDbType.Text, ct);
                await importer.WriteAsync(edge.Resolution, NpgsqlDbType.Text, ct);
                await importer.WriteAsync(edge.ClosesCycle, NpgsqlDbType.Boolean, ct);
                await importer.WriteAsync(Json(edge), NpgsqlDbType.Jsonb, ct);
            }

            await importer.CompleteAsync(ct);
        }

        await cache.FlushAsync(connection, transaction, ct);
        await transaction.CommitAsync(ct);
    }

    private static string Json<T>(T value) => JsonSerializer.Serialize(value, DeterministicJson.Options);
}
