using Fingerprinting.Domain;
using Npgsql;
using NpgsqlTypes;

namespace Fingerprinting.EntryPoints.Cli;

/// <summary>
/// Npgsql persistence for 29-STEPS-004-005-INVENTORIES.md Part B4:
/// <c>entry_points</c>, one row per entry point, plus
/// <c>entry_point_scans</c>, one row per repository carrying the summaries
/// (the per-project counts, global authorisation and conventional route
/// tables the rows alone cannot give). Both owned by step 4 and replaced
/// wholesale per repository on rescan, in one transaction — same pattern
/// as step 3's FingerprintDatabase.
/// </summary>
public sealed class EntryPointDatabase(string connectionString)
{
    public async Task ReplaceAllAsync(EntryPointInventoryArtifact artifact, Guid? stepExecutionId, CancellationToken cancellationToken)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(cancellationToken);
        await using var transaction = await connection.BeginTransactionAsync(cancellationToken);
        var detectedAt = DateTimeOffset.UtcNow;

        foreach (var table in new[] { "entry_points", "entry_point_scans" })
        {
            await using var delete = new NpgsqlCommand($"DELETE FROM {table} WHERE repository_id = @rid", connection, transaction);
            delete.Parameters.AddWithValue("rid", artifact.RepositoryId);
            await delete.ExecuteNonQueryAsync(cancellationToken);
        }

        foreach (var project in artifact.Projects)
        {
            foreach (var entry in project.EntryPoints)
            {
                await using var insert = new NpgsqlCommand(
                    """
                    INSERT INTO entry_points
                        (id, repository_id, project_id, kind, handler_type, handler_member, file_path, line_start, line_end,
                         detail, confidence, confidence_reasons, auth_declared, origin, entry_class, step_execution_id, detected_at)
                    VALUES
                        (@id, @rid, @pid, @kind, @type, @member, @file, @start, @end,
                         @detail, @confidence, @reasons, @auth_declared, @origin, @entry_class, @sid, @at)
                    """,
                    connection, transaction);
                insert.Parameters.AddWithValue("id", entry.EntryPointId);
                insert.Parameters.AddWithValue("rid", artifact.RepositoryId);
                insert.Parameters.AddWithValue("pid", project.ProjectId);
                insert.Parameters.AddWithValue("kind", entry.Kind);
                insert.Parameters.AddWithValue("type", entry.Handler.Type);
                insert.Parameters.AddWithValue("member", (object?)entry.Handler.Member ?? DBNull.Value);
                insert.Parameters.AddWithValue("file", entry.Handler.FilePath);
                insert.Parameters.AddWithValue("start", entry.Handler.LineStart);
                insert.Parameters.AddWithValue("end", entry.Handler.LineEnd);
                insert.Parameters.Add(new NpgsqlParameter("detail", NpgsqlDbType.Jsonb) { Value = Json(entry.DetailBlock()) });
                insert.Parameters.AddWithValue("confidence", entry.Confidence);
                insert.Parameters.Add(new NpgsqlParameter("reasons", NpgsqlDbType.Jsonb) { Value = Json(entry.ConfidenceReasons) });
                insert.Parameters.AddWithValue("auth_declared", (object?)entry.AuthDeclared ?? DBNull.Value);
                insert.Parameters.AddWithValue("origin", entry.Origin);
                insert.Parameters.AddWithValue("entry_class", entry.EntryClass);
                insert.Parameters.AddWithValue("sid", (object?)stepExecutionId ?? DBNull.Value);
                insert.Parameters.AddWithValue("at", detectedAt);
                await insert.ExecuteNonQueryAsync(cancellationToken);
            }
        }

        var projectSummaries = artifact.Projects.Select(p => new
        {
            p.ProjectId,
            p.ProjectPath,
            p.Status,
            p.SkipReason,
            p.Summary,
            p.Warnings,
        }).ToList();

        await using (var scan = new NpgsqlCommand(
                   """
                   INSERT INTO entry_point_scans
                       (repository_id, scanner_version, skip_source, summary, project_summaries, capabilities, warnings, step_execution_id, scanned_at)
                   VALUES (@rid, @version, @skip, @summary, @projects, @capabilities, @warnings, @sid, @at)
                   """,
                   connection, transaction))
        {
            scan.Parameters.AddWithValue("rid", artifact.RepositoryId);
            scan.Parameters.AddWithValue("version", artifact.ScannerVersion);
            scan.Parameters.AddWithValue("skip", artifact.SkipSource);
            scan.Parameters.Add(new NpgsqlParameter("summary", NpgsqlDbType.Jsonb) { Value = Json(artifact.Summary) });
            scan.Parameters.Add(new NpgsqlParameter("projects", NpgsqlDbType.Jsonb) { Value = Json(projectSummaries) });
            scan.Parameters.Add(new NpgsqlParameter("capabilities", NpgsqlDbType.Jsonb) { Value = Json(artifact.Capabilities) });
            scan.Parameters.Add(new NpgsqlParameter("warnings", NpgsqlDbType.Jsonb) { Value = Json(artifact.Warnings) });
            scan.Parameters.AddWithValue("sid", (object?)stepExecutionId ?? DBNull.Value);
            scan.Parameters.AddWithValue("at", detectedAt);
            await scan.ExecuteNonQueryAsync(cancellationToken);
        }

        await transaction.CommitAsync(cancellationToken);
    }

    /// <summary>The same camelCase, key-sorted shape as the artifact, so a
    /// JSONB column reads like the file.</summary>
    private static string Json<T>(T value) => System.Text.Json.JsonSerializer.Serialize(value, DeterministicJson.Options);
}
