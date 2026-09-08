using System.Text.Json;
using Fingerprinting.Domain;
using Npgsql;
using NpgsqlTypes;

namespace Fingerprinting.Cli;

/// <summary>
/// Npgsql persistence for the three tables from
/// 21-STEP-003-FINGERPRINTING.md Part E. All rows owned by step 3 and
/// replaced wholesale per repository on rescan — same pattern as step 2's
/// <c>discovery/persistence.py</c>.
/// </summary>
public sealed class FingerprintDatabase(string connectionString)
{
    public async Task<string?> GetRepositoryLocalPathAsync(Guid repositoryId, CancellationToken cancellationToken)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(cancellationToken);

        await using var command = new NpgsqlCommand("SELECT local_path FROM repositories WHERE id = @rid", connection);
        command.Parameters.AddWithValue("rid", repositoryId);

        return (string?)await command.ExecuteScalarAsync(cancellationToken);
    }

    /// <summary>Resolves each project's DB row id by (repository_id,
    /// relative_path) — the artifact itself carries no project id; see
    /// SolutionProjectInventory.cs.</summary>
    public async Task<Dictionary<string, Guid>> ResolveProjectIdsAsync(
        Guid repositoryId, CancellationToken cancellationToken)
    {
        await using var connection = new NpgsqlConnection(connectionString);
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

    public async Task ReplaceAllAsync(
        Guid repositoryId, ApplicationFingerprintArtifact artifact, Guid? stepExecutionId, CancellationToken cancellationToken)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(cancellationToken);
        await using var transaction = await connection.BeginTransactionAsync(cancellationToken);

        await ExecuteAsync(connection, transaction, "DELETE FROM fingerprint_signals WHERE repository_id = @rid", repositoryId, cancellationToken);
        await ExecuteAsync(connection, transaction, "DELETE FROM project_fingerprints WHERE repository_id = @rid", repositoryId, cancellationToken);
        await ExecuteAsync(connection, transaction, "DELETE FROM fingerprint_scans WHERE repository_id = @rid", repositoryId, cancellationToken);

        foreach (var project in artifact.Projects)
        {
            await InsertProjectFingerprintAsync(connection, transaction, repositoryId, project, stepExecutionId, cancellationToken);
            foreach (var signal in project.Signals)
            {
                await InsertSignalAsync(connection, transaction, repositoryId, project.ProjectId, signal, cancellationToken);
            }
        }

        foreach (var signal in artifact.RepositorySignals)
        {
            await InsertSignalAsync(connection, transaction, repositoryId, null, signal, cancellationToken);
        }

        await InsertScanAsync(connection, transaction, repositoryId, artifact, stepExecutionId, cancellationToken);

        await transaction.CommitAsync(cancellationToken);
    }

    private static async Task ExecuteAsync(
        NpgsqlConnection connection, NpgsqlTransaction transaction, string sql, Guid repositoryId, CancellationToken cancellationToken)
    {
        await using var command = new NpgsqlCommand(sql, connection, transaction);
        command.Parameters.AddWithValue("rid", repositoryId);
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    private static async Task InsertProjectFingerprintAsync(
        NpgsqlConnection connection,
        NpgsqlTransaction transaction,
        Guid repositoryId,
        ProjectFingerprint project,
        Guid? stepExecutionId,
        CancellationToken cancellationToken)
    {
        await using var command = new NpgsqlCommand(
            """
            INSERT INTO project_fingerprints (
                project_id, repository_id, fingerprint_status, scanner_version,
                analysis_capabilities, project_sdk, nullable_enabled, implicit_usings,
                evaluated_properties, signal_count, evidence_count, category_summary,
                warnings, analysis_duration_ms, step_execution_id, fingerprinted_at
            ) VALUES (
                @project_id, @repository_id, @fingerprint_status, @scanner_version,
                @analysis_capabilities, @project_sdk, @nullable_enabled, @implicit_usings,
                @evaluated_properties, @signal_count, @evidence_count, @category_summary,
                @warnings, @analysis_duration_ms, @step_execution_id, now()
            )
            """,
            connection, transaction);

        command.Parameters.AddWithValue("project_id", project.ProjectId);
        command.Parameters.AddWithValue("repository_id", repositoryId);
        command.Parameters.AddWithValue("fingerprint_status", FingerprintStatuses.ToDbValue(project.FingerprintStatus));
        command.Parameters.AddWithValue("scanner_version", FingerprintPipeline.ScannerVersion);
        AddJsonb(command, "analysis_capabilities", ToJson(project.AnalysisCapabilities));
        command.Parameters.AddWithValue("project_sdk", (object?)project.ProjectSdk ?? DBNull.Value);
        command.Parameters.AddWithValue("nullable_enabled", (object?)project.NullableEnabled ?? DBNull.Value);
        command.Parameters.AddWithValue("implicit_usings", (object?)project.ImplicitUsings ?? DBNull.Value);
        AddJsonb(command, "evaluated_properties", project.EvaluatedProperties is null ? null : ToJson(project.EvaluatedProperties));
        command.Parameters.AddWithValue("signal_count", project.Signals.Count);
        command.Parameters.AddWithValue("evidence_count", project.Signals.Sum(s => s.Evidence.Count));
        AddJsonb(command, "category_summary", ToJson(CategorySummary(project)));
        AddJsonb(command, "warnings", ToJson(project.Warnings));
        command.Parameters.AddWithValue("analysis_duration_ms", DBNull.Value);
        command.Parameters.AddWithValue("step_execution_id", (object?)stepExecutionId ?? DBNull.Value);

        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    private static Dictionary<string, int> CategorySummary(ProjectFingerprint project) =>
        project.Signals
            .GroupBy(s => s.Category, StringComparer.Ordinal)
            .OrderBy(g => g.Key, StringComparer.Ordinal)
            .ToDictionary(g => g.Key, g => g.Count());

    private static async Task InsertSignalAsync(
        NpgsqlConnection connection,
        NpgsqlTransaction transaction,
        Guid repositoryId,
        Guid? projectId,
        Signal signal,
        CancellationToken cancellationToken)
    {
        await using var command = new NpgsqlCommand(
            """
            INSERT INTO fingerprint_signals (
                project_id, repository_id, signal_name, signal_category, signal_type,
                value, source_type, source_path, evidence_kind, occurrence_count, evidence,
                extractor, extraction_confidence
            ) VALUES (
                @project_id, @repository_id, @signal_name, @signal_category, @signal_type,
                @value, @source_type, @source_path, @evidence_kind, @occurrence_count, @evidence,
                @extractor, @extraction_confidence
            )
            """,
            connection, transaction);

        command.Parameters.AddWithValue("project_id", (object?)projectId ?? DBNull.Value);
        command.Parameters.AddWithValue("repository_id", repositoryId);
        command.Parameters.AddWithValue("signal_name", signal.Name);
        command.Parameters.AddWithValue("signal_category", signal.Category);
        command.Parameters.AddWithValue("signal_type", signal.Type);
        command.Parameters.AddWithValue("value", (object?)signal.Value ?? DBNull.Value);
        command.Parameters.AddWithValue("source_type", signal.SourceType);
        command.Parameters.AddWithValue("source_path", (object?)signal.SourcePath ?? DBNull.Value);
        command.Parameters.AddWithValue("evidence_kind", (object?)signal.EvidenceKind ?? DBNull.Value);
        command.Parameters.AddWithValue("occurrence_count", signal.OccurrenceCount);
        AddJsonb(command, "evidence", ToJson(signal.Evidence));
        command.Parameters.AddWithValue("extractor", signal.Extractor);
        command.Parameters.AddWithValue("extraction_confidence", signal.ExtractionConfidence);

        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    private static async Task InsertScanAsync(
        NpgsqlConnection connection,
        NpgsqlTransaction transaction,
        Guid repositoryId,
        ApplicationFingerprintArtifact artifact,
        Guid? stepExecutionId,
        CancellationToken cancellationToken)
    {
        await using var command = new NpgsqlCommand(
            """
            INSERT INTO fingerprint_scans (
                repository_id, scan_status, scanner_version, signal_registry_version,
                projects_eligible, projects_complete, projects_partial, projects_failed,
                projects_skipped, total_signals, total_evidence, semantic_analysis_enabled,
                repository_signal_count, warnings, step_execution_id, scanned_at
            ) VALUES (
                @repository_id, @scan_status, @scanner_version, @signal_registry_version,
                @projects_eligible, @projects_complete, @projects_partial, @projects_failed,
                @projects_skipped, @total_signals, @total_evidence, @semantic_analysis_enabled,
                @repository_signal_count, @warnings, @step_execution_id, now()
            )
            """,
            connection, transaction);

        command.Parameters.AddWithValue("repository_id", repositoryId);
        command.Parameters.AddWithValue("scan_status", artifact.ScanStatus);
        command.Parameters.AddWithValue("scanner_version", artifact.ScannerVersion);
        command.Parameters.AddWithValue("signal_registry_version", artifact.SignalRegistryVersion);
        command.Parameters.AddWithValue("projects_eligible", artifact.Summary.ProjectsEligible);
        command.Parameters.AddWithValue("projects_complete", artifact.Summary.ProjectsComplete);
        command.Parameters.AddWithValue("projects_partial", artifact.Summary.ProjectsPartial);
        command.Parameters.AddWithValue("projects_failed", artifact.Summary.ProjectsFailed);
        command.Parameters.AddWithValue("projects_skipped", artifact.Summary.ProjectsSkipped);
        command.Parameters.AddWithValue("total_signals", artifact.Summary.TotalSignals);
        command.Parameters.AddWithValue("total_evidence", artifact.Summary.TotalEvidence);
        command.Parameters.AddWithValue("semantic_analysis_enabled", artifact.SemanticAnalysisEnabled);
        command.Parameters.AddWithValue("repository_signal_count", artifact.RepositorySignals.Count);
        AddJsonb(command, "warnings", ToJson(artifact.Warnings));
        command.Parameters.AddWithValue("step_execution_id", (object?)stepExecutionId ?? DBNull.Value);

        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    private static void AddJsonb(NpgsqlCommand command, string name, string? json)
    {
        var parameter = command.Parameters.Add(name, NpgsqlDbType.Jsonb);
        parameter.Value = (object?)json ?? DBNull.Value;
    }

    private static string ToJson<T>(T value) => JsonSerializer.Serialize(value, DeterministicJson.Options);
}
