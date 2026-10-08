using System.Text.Json;
using Fingerprinting.Domain;
using Fingerprinting.TestCoverage;
using Npgsql;
using NpgsqlTypes;

namespace Fingerprinting.TestCoverage.Cli;

/// <summary>
/// Npgsql persistence for 32-TEST-COVERAGE-ASSESSMENT Part J, phase 1, in one transaction
/// per repository: <c>test_classes</c>, <c>test_mappings</c>,
/// <c>source_file_coverage</c> and <c>ci_maturity</c> replaced wholesale, and
/// a <c>coverage_scans</c> row recording the commit and cache state, with the
/// result itself on every row that computed it. A later run at the same commit
/// reuses the latest <c>computed</c> one (Part I).
/// </summary>
public sealed class TestCoverageDatabase(string connectionString)
{
    public async Task<string?> GetCommitShaAsync(Guid repositoryId, CancellationToken ct)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(ct);
        await using var command = new NpgsqlCommand(
            "SELECT ingest_commit_sha FROM repositories WHERE id = @id AND has_git_history", connection);
        command.Parameters.AddWithValue("id", repositoryId);
        return await command.ExecuteScalarAsync(ct) as string;
    }

    /// <summary>The latest computed result for this commit and cache key.</summary>
    public async Task<(Guid ScanId, string Result)?> FindCachedAsync(Guid repositoryId, string commitSha, string cacheKey, CancellationToken ct)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(ct);
        await using var command = new NpgsqlCommand(
            """
            SELECT id, result::text FROM coverage_scans
            WHERE repository_id = @rid AND commit_sha = @sha AND cache_key = @key AND cache_state = 'computed' AND result IS NOT NULL
            ORDER BY scanned_at DESC LIMIT 1
            """, connection);
        command.Parameters.AddWithValue("rid", repositoryId);
        command.Parameters.AddWithValue("sha", commitSha);
        command.Parameters.AddWithValue("key", cacheKey);
        await using var reader = await command.ExecuteReaderAsync(ct);
        return await reader.ReadAsync(ct) ? (reader.GetGuid(0), reader.GetString(1)) : null;
    }

    public async Task ReplaceAllAsync(
        TestCoverageArtifact artifact, IReadOnlyDictionary<string, Guid> projectIds, string cacheKey, string cacheState, string? cacheNote,
        Guid? reusedFrom, string checksum, Guid? stepExecutionId, CancellationToken ct)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(ct);
        await using var transaction = await connection.BeginTransactionAsync(ct);
        var rid = artifact.RepositoryId;
        object Sid() => (object?)stepExecutionId ?? DBNull.Value;
        object ProjectId(string path) => projectIds.TryGetValue(path, out var id) ? id : DBNull.Value;

        foreach (var table in new[] { "test_classes", "test_mappings", "source_file_coverage", "ci_maturity" })
        {
            await Execute(connection, transaction, $"DELETE FROM {table} WHERE repository_id = @rid", ("rid", rid));
        }

        foreach (var c in artifact.TestClasses)
        {
            await Insert(connection, transaction,
                """
                INSERT INTO test_classes (repository_id, project_id, project_path, file_path, class_name, namespace, line_start, test_type,
                                          classification_reason, evidence, test_count, step_execution_id)
                VALUES (@rid, @pid, @project, @file, @class, @ns, @line, @type, @reason, @evidence, @count, @sid)
                """,
                ("rid", rid), ("pid", ProjectId(c.ProjectPath)), ("project", c.ProjectPath), ("file", c.FilePath), ("class", c.ClassName),
                ("ns", (object?)c.Namespace ?? DBNull.Value), ("line", c.LineStart), ("type", c.TestType), ("reason", c.ClassificationReason),
                ("evidence", Jsonb(c.Evidence)), ("count", c.TestCount), ("sid", Sid()));
        }

        foreach (var m in artifact.Mappings)
        {
            await Insert(connection, transaction,
                """
                INSERT INTO test_mappings (repository_id, source_file, production_type, test_file, test_class, test_type, test_methods,
                                           mapping_method, confidence, evidence, step_execution_id)
                VALUES (@rid, @source, @type, @test_file, @test_class, @test_type, @methods, @method, @confidence, @evidence, @sid)
                """,
                ("rid", rid), ("source", m.SourceFile), ("type", m.ProductionType), ("test_file", m.TestFile), ("test_class", m.TestClass),
                ("test_type", m.TestType), ("methods", Jsonb(m.TestMethods)), ("method", m.Method), ("confidence", m.Confidence),
                ("evidence", Jsonb(m.Evidence)), ("sid", Sid()));
        }

        foreach (var f in artifact.SourceFiles)
        {
            await Insert(connection, transaction,
                """
                INSERT INTO source_file_coverage (repository_id, project_id, project_path, file_path, bucket, testable_members, test_files, test_types,
                    coverage_source, line_pct, branch_pct, not_measured_reason, unit_line_pct, unit_not_measured_reason,
                    integration_line_pct, integration_not_measured_reason, step_execution_id)
                VALUES (@rid, @pid, @project, @file, @bucket, @members, @test_files, @test_types, @source, @line, @branch, @reason,
                        @unit, @unit_reason, @integration, @integration_reason, @sid)
                """,
                ("rid", rid), ("pid", ProjectId(f.ProjectPath)), ("project", f.ProjectPath), ("file", f.FilePath), ("bucket", f.Bucket),
                ("members", f.TestableMembers), ("test_files", Jsonb(f.TestFiles)), ("test_types", Jsonb(f.TestTypes)), ("source", f.CoverageSource),
                ("line", Nullable(f.LinePct)), ("branch", Nullable(f.BranchPct)), ("reason", (object?)f.NotMeasuredReason ?? DBNull.Value),
                ("unit", Nullable(f.UnitLinePct)), ("unit_reason", (object?)f.UnitNotMeasuredReason ?? DBNull.Value),
                ("integration", Nullable(f.IntegrationLinePct)), ("integration_reason", (object?)f.IntegrationNotMeasuredReason ?? DBNull.Value),
                ("sid", Sid()));
        }

        var ci = artifact.CiMaturity;
        await Insert(connection, transaction,
            """
            INSERT INTO ci_maturity (repository_id, has_pipeline, runs_tests, collects_coverage, publishes_coverage, enforces_coverage_gate,
                                     pipelines, evidence, step_execution_id)
            VALUES (@rid, @has, @runs, @collects, @publishes, @gate, @pipelines, @evidence, @sid)
            """,
            ("rid", rid), ("has", ci.HasPipeline), ("runs", ci.RunsTests), ("collects", ci.CollectsCoverage), ("publishes", ci.PublishesCoverage),
            ("gate", ci.EnforcesCoverageGate), ("pipelines", Jsonb(ci.Pipelines)), ("evidence", Jsonb(ci.Evidence)), ("sid", Sid()));

        // Every scan that computed its result keeps it: the API reads it, and a
        // later run at the same commit reuses it — but only from a 'computed'
        // row (FindCachedAsync), never one computed despite uncommitted changes
        // or without a commit. A reused row points at the row it reused.
        await Insert(connection, transaction,
            """
            INSERT INTO coverage_scans (repository_id, commit_sha, cache_key, cache_state, cache_note, reused_from_scan_id, report_sources,
                                        result, result_checksum, step_execution_id)
            VALUES (@rid, @sha, @key, @state, @note, @from, @sources, @result, @checksum, @sid)
            """,
            ("rid", rid), ("sha", (object?)artifact.CommitSha ?? DBNull.Value), ("key", cacheKey), ("state", cacheState),
            ("note", (object?)cacheNote ?? DBNull.Value), ("from", (object?)reusedFrom ?? DBNull.Value),
            ("sources", Jsonb(artifact.CoverageReports.Select(r => new { r.Path, r.Format, r.Attribution }))),
            ("result", cacheState == "reused" ? DBNull.Value : Jsonb(artifact)), ("checksum", checksum), ("sid", Sid()));

        await transaction.CommitAsync(ct);
    }

    private static object Nullable(decimal? value) => (object?)value ?? DBNull.Value;

    private static NpgsqlParameter JsonbParameter(string name, object value) => new(name, NpgsqlDbType.Jsonb) { Value = value };

    private sealed record JsonbValue(string Json);

    private static JsonbValue Jsonb<T>(T value) => new(JsonSerializer.Serialize(value, DeterministicJson.Options));

    private static async Task Insert(NpgsqlConnection connection, NpgsqlTransaction transaction, string sql, params (string Name, object Value)[] parameters)
    {
        await using var command = new NpgsqlCommand(sql, connection, transaction);
        foreach (var (name, value) in parameters)
        {
            command.Parameters.Add(value is JsonbValue json ? JsonbParameter(name, json.Json) : new NpgsqlParameter(name, value));
        }

        await command.ExecuteNonQueryAsync();
    }

    private static async Task Execute(NpgsqlConnection connection, NpgsqlTransaction transaction, string sql, params (string, object)[] parameters)
    {
        await using var command = new NpgsqlCommand(sql, connection, transaction);
        foreach (var (name, value) in parameters) command.Parameters.AddWithValue(name, value);
        await command.ExecuteNonQueryAsync();
    }
}
