using System.Text.Json;
using Fingerprinting.Domain;
using Fingerprinting.Impact;
using Npgsql;
using NpgsqlTypes;

namespace Fingerprinting.Impact.Cli;

/// <summary>
/// impact-analysis's reads — the repository's engagement, its live decisions, the
/// catalog's resolutions and impact rules — and its writes
/// (33-IMPACT-ANALYSIS Part I) in one transaction: the repository's
/// work_item_impacts (client rows too: dependency-and-context-map adds them back at the end of
/// its next run), impact_summaries and file_impact_rollup, replaced.
/// </summary>
public sealed class ImpactDatabase(string connectionString)
{
    private static readonly JsonSerializerOptions RuleRead = new() { PropertyNameCaseInsensitive = true };

    public async Task<string> GetEngagementIdAsync(Guid repositoryId, CancellationToken ct)
    {
        await using var connection = await OpenAsync(ct);
        await using var command = new NpgsqlCommand("SELECT engagement_id FROM repositories WHERE id = @id", connection);
        command.Parameters.AddWithValue("id", repositoryId);
        return (string)(await command.ExecuteScalarAsync(ct) ?? throw new InvalidOperationException($"repository {repositoryId} has no engagement"));
    }

    /// <summary>Live (not superseded) decisions with a chosen resolution: item → resolution.</summary>
    public async Task<IReadOnlyDictionary<string, string>> GetDecisionsAsync(string engagementId, CancellationToken ct)
    {
        await using var connection = await OpenAsync(ct);
        await using var command = new NpgsqlCommand(
            "SELECT item_id, resolution_id FROM engagement_decisions WHERE engagement_id = @e AND status <> 'superseded' AND resolution_id IS NOT NULL", connection);
        command.Parameters.AddWithValue("e", engagementId);
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        await using var reader = await command.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct)) result[reader.GetString(0)] = reader.GetString(1);
        return result;
    }

    /// <summary>Each item's name and live, active resolutions with their impact rules.</summary>
    public async Task<IReadOnlyDictionary<string, CatalogItemInfo>> GetCatalogAsync(IReadOnlyList<string> itemIds, CancellationToken ct)
    {
        await using var connection = await OpenAsync(ct);
        await using var command = new NpgsqlCommand(
            """
            SELECT i.id, i.name, r.id, r.name, r.is_default, r.consumer_impact, r.impact_rules::text
            FROM catalog_items i
            JOIN item_resolutions r ON r.item_id = i.id AND r.deleted_at IS NULL AND r.status = 'active'
            WHERE i.id = ANY(@ids) AND i.deleted_at IS NULL
            ORDER BY i.id, r.id
            """, connection);
        command.Parameters.AddWithValue("ids", itemIds.ToArray());
        var items = new Dictionary<string, (string Name, List<ResolutionInfo> Resolutions)>(StringComparer.Ordinal);
        await using var reader = await command.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct))
        {
            var itemId = reader.GetString(0);
            if (!items.TryGetValue(itemId, out var entry)) items[itemId] = entry = (reader.GetString(1), []);
            var rules = JsonSerializer.Deserialize<List<ImpactRule>>(reader.GetString(6), RuleRead) ?? [];
            entry.Resolutions.Add(new ResolutionInfo(reader.GetString(2), reader.GetString(3), reader.GetBoolean(4), reader.GetString(5), rules));
        }

        return items.ToDictionary(kv => kv.Key, kv => new CatalogItemInfo(kv.Key, kv.Value.Name, kv.Value.Resolutions), StringComparer.Ordinal);
    }

    public async Task ReplaceAllAsync(ImpactArtifact artifact, Guid? stepExecutionId, CancellationToken ct)
    {
        await using var connection = await OpenAsync(ct);
        await using var transaction = await connection.BeginTransactionAsync(ct);
        var rid = artifact.RepositoryId;
        object Sid() => (object?)stepExecutionId ?? DBNull.Value;

        foreach (var table in new[] { "work_item_impacts", "impact_summaries", "file_impact_rollup" })
        {
            await using var delete = new NpgsqlCommand($"DELETE FROM {table} WHERE repository_id = @rid", connection, transaction);
            delete.Parameters.AddWithValue("rid", rid);
            await delete.ExecuteNonQueryAsync(ct);
        }

        foreach (var work in artifact.WorkItems)
        {
            foreach (var resolution in work.Resolutions)
            {
                foreach (var entry in resolution.Entries)
                {
                    await Insert(connection, transaction,
                        """
                        INSERT INTO work_item_impacts (repository_id, engagement_id, item_id, project_id, project_path, resolution_id, file_repository_id,
                            file_path, proposed_path, description, action, certainty, reasons, rule_ids, traversal_paths, details, source, step_execution_id)
                        VALUES (@rid, @eid, @item, @pid, @project, @resolution, @rid, @file, @proposed, @description, @action, @certainty,
                            @reasons, @rules, @paths, @details, 'structural', @sid)
                        """,
                        ("rid", rid), ("eid", artifact.EngagementId), ("item", work.ItemId), ("pid", (object?)work.ProjectId ?? DBNull.Value),
                        ("project", work.ProjectPath), ("resolution", resolution.ResolutionId), ("file", (object?)entry.FilePath ?? DBNull.Value),
                        ("proposed", (object?)entry.ProposedPath ?? DBNull.Value), ("description", (object?)entry.Description ?? DBNull.Value),
                        ("action", entry.Action), ("certainty", entry.Certainty), ("reasons", Jsonb(entry.Reasons)),
                        ("rules", Jsonb(entry.Reasons.Select(r => r.RuleId).Distinct())), ("paths", Jsonb(entry.TraversalPaths)),
                        ("details", Jsonb(entry.Details)), ("sid", Sid()));
                }

                await Insert(connection, transaction,
                    """
                    INSERT INTO impact_summaries (repository_id, engagement_id, item_id, project_id, project_path, resolution_id, roles, effective,
                        counts, changed, created, to_review, confirmed, possible, client_changed, client_review, rules_source, known_limits,
                        decision_resolution_id, stale, step_execution_id)
                    VALUES (@rid, @eid, @item, @pid, @project, @resolution, @roles, @effective, @counts, @changed, @created, @review,
                        @confirmed, @possible, 0, 0, @rules_source, @limits, @decision, false, @sid)
                    """,
                    ("rid", rid), ("eid", artifact.EngagementId), ("item", work.ItemId), ("pid", (object?)work.ProjectId ?? DBNull.Value),
                    ("project", work.ProjectPath), ("resolution", resolution.ResolutionId), ("roles", Jsonb(resolution.Roles)), ("effective", resolution.Effective),
                    ("counts", Jsonb(resolution.Counts)), ("changed", resolution.Changed),
                    ("created", resolution.Created), ("review", resolution.ToReview), ("confirmed", resolution.Confirmed), ("possible", resolution.Possible),
                    ("rules_source", resolution.RulesSource), ("limits", Jsonb(resolution.KnownLimits)),
                    ("decision", (object?)resolution.DecisionResolutionId ?? DBNull.Value), ("sid", Sid()));
            }
        }

        foreach (var file in artifact.Rollup)
        {
            await Insert(connection, transaction,
                "INSERT INTO file_impact_rollup (repository_id, file_key, work_items, hotspot, conflicts, includes_client) VALUES (@rid, @key, @items, @hotspot, @conflicts, false)",
                ("rid", rid), ("key", file.FileKey), ("items", Jsonb(file.WorkItems)), ("hotspot", file.Hotspot), ("conflicts", Jsonb(file.Conflicts)));
        }

        await transaction.CommitAsync(ct);
    }

    private sealed record JsonbValue(string Json);

    private static JsonbValue Jsonb<T>(T value) => new(JsonSerializer.Serialize(value, DeterministicJson.Options));

    private async Task<NpgsqlConnection> OpenAsync(CancellationToken ct)
    {
        var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(ct);
        return connection;
    }

    private static async Task Insert(NpgsqlConnection connection, NpgsqlTransaction transaction, string sql, params (string Name, object Value)[] parameters)
    {
        await using var command = new NpgsqlCommand(sql, connection, transaction);
        foreach (var (name, value) in parameters)
        {
            command.Parameters.Add(value is JsonbValue json ? new NpgsqlParameter(name, NpgsqlDbType.Jsonb) { Value = json.Json } : new NpgsqlParameter(name, value));
        }

        await command.ExecuteNonQueryAsync();
    }
}
