using Fingerprinting.Domain;
using Npgsql;
using NpgsqlTypes;

namespace Fingerprinting.Outbound.Cli;

/// <summary>
/// Npgsql persistence for 29-STEPS-004-005-INVENTORIES.md Part C8:
/// <c>outbound_invocations</c>, one row per invocation, plus
/// <c>outbound_scans</c>, one row per repository carrying the per-project
/// summaries. Both owned by step 5 and replaced wholesale per repository
/// on rescan, in one transaction — the same pattern as steps 3 and 4.
/// </summary>
public sealed class OutboundDatabase(string connectionString)
{
    public async Task ReplaceAllAsync(OutboundInventoryArtifact artifact, Guid? stepExecutionId, CancellationToken cancellationToken)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(cancellationToken);
        await using var transaction = await connection.BeginTransactionAsync(cancellationToken);
        var detectedAt = DateTimeOffset.UtcNow;

        foreach (var table in new[] { "outbound_invocations", "outbound_scans" })
        {
            await using var delete = new NpgsqlCommand($"DELETE FROM {table} WHERE repository_id = @rid", connection, transaction);
            delete.Parameters.AddWithValue("rid", artifact.RepositoryId);
            await delete.ExecuteNonQueryAsync(cancellationToken);
        }

        foreach (var project in artifact.Projects)
        {
            foreach (var invocation in project.Invocations)
            {
                await using var insert = new NpgsqlCommand(
                    """
                    INSERT INTO outbound_invocations
                        (id, repository_id, project_id, mechanism, usage, endpoint_scheme, endpoint_host, endpoint_port, endpoint_path,
                         resolution, placeholder, detail, environment_bindings, call_sites, credentials, auth_declared,
                         linux_verdict, linux_reasons, confidence, confidence_reasons, step_execution_id, detected_at)
                    VALUES
                        (@id, @rid, @pid, @mechanism, @usage, @scheme, @host, @port, @path,
                         @resolution, @placeholder, @detail, @bindings, @sites, @credentials, @auth,
                         @verdict, @reasons, @confidence, @confidence_reasons, @sid, @at)
                    """,
                    connection, transaction);
                var endpoint = invocation.Endpoint;
                insert.Parameters.AddWithValue("id", invocation.InvocationId);
                insert.Parameters.AddWithValue("rid", artifact.RepositoryId);
                insert.Parameters.AddWithValue("pid", project.ProjectId);
                insert.Parameters.AddWithValue("mechanism", invocation.Mechanism);
                insert.Parameters.AddWithValue("usage", invocation.Usage);
                insert.Parameters.AddWithValue("scheme", (object?)endpoint.Scheme ?? DBNull.Value);
                insert.Parameters.AddWithValue("host", (object?)endpoint.Host ?? DBNull.Value);
                insert.Parameters.AddWithValue("port", (object?)endpoint.Port ?? DBNull.Value);
                insert.Parameters.AddWithValue("path", (object?)endpoint.Path ?? DBNull.Value);
                insert.Parameters.AddWithValue("resolution", endpoint.Resolution);
                insert.Parameters.AddWithValue("placeholder", (object?)endpoint.Placeholder ?? DBNull.Value);
                insert.Parameters.Add(new NpgsqlParameter("detail", NpgsqlDbType.Jsonb) { Value = Json(new { Endpoint = endpoint, Block = invocation.DetailBlock() }) });
                insert.Parameters.Add(new NpgsqlParameter("bindings", NpgsqlDbType.Jsonb) { Value = Json(invocation.EnvironmentBindings) });
                insert.Parameters.Add(new NpgsqlParameter("sites", NpgsqlDbType.Jsonb) { Value = Json(invocation.CallSites) });
                insert.Parameters.Add(new NpgsqlParameter("credentials", NpgsqlDbType.Jsonb) { Value = Json(invocation.Credentials) });
                insert.Parameters.AddWithValue("auth", (object?)invocation.AuthDeclared ?? DBNull.Value);
                insert.Parameters.AddWithValue("verdict", invocation.LinuxCompatibility.Verdict);
                insert.Parameters.Add(new NpgsqlParameter("reasons", NpgsqlDbType.Jsonb) { Value = Json(invocation.LinuxCompatibility.Reasons) });
                insert.Parameters.AddWithValue("confidence", invocation.Confidence);
                insert.Parameters.Add(new NpgsqlParameter("confidence_reasons", NpgsqlDbType.Jsonb) { Value = Json(invocation.ConfidenceReasons) });
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
                   INSERT INTO outbound_scans
                       (repository_id, scanner_version, skip_source, summary, project_summaries, warnings, step_execution_id, scanned_at)
                   VALUES (@rid, @version, @skip, @summary, @projects, @warnings, @sid, @at)
                   """,
                   connection, transaction))
        {
            scan.Parameters.AddWithValue("rid", artifact.RepositoryId);
            scan.Parameters.AddWithValue("version", artifact.ScannerVersion);
            scan.Parameters.AddWithValue("skip", artifact.SkipSource);
            scan.Parameters.Add(new NpgsqlParameter("summary", NpgsqlDbType.Jsonb) { Value = Json(artifact.Summary) });
            scan.Parameters.Add(new NpgsqlParameter("projects", NpgsqlDbType.Jsonb) { Value = Json(projectSummaries) });
            scan.Parameters.Add(new NpgsqlParameter("warnings", NpgsqlDbType.Jsonb) { Value = Json(artifact.Warnings) });
            scan.Parameters.AddWithValue("sid", (object?)stepExecutionId ?? DBNull.Value);
            scan.Parameters.AddWithValue("at", detectedAt);
            await scan.ExecuteNonQueryAsync(cancellationToken);
        }

        await transaction.CommitAsync(cancellationToken);
    }

    /// <summary>The same camelCase, key-sorted shape as the artifact.</summary>
    private static string Json<T>(T value) => System.Text.Json.JsonSerializer.Serialize(value, DeterministicJson.Options);
}
