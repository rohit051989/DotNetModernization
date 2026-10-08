using System.Text.Json;
using Fingerprinting.Dependencies;
using Fingerprinting.Domain;
using Npgsql;
using NpgsqlTypes;

namespace Fingerprinting.Dependencies.Cli;

/// <summary>
/// Npgsql persistence for 30-DEPENDENCY-ASSESSMENT.md Part F, in
/// one transaction per repository:
/// <list type="bullet">
/// <item><c>package_assessments</c>, one row per project per direct package,
/// replaced wholesale.</item>
/// <item>this step's signals in <c>fingerprint_signals</c>, under extractor
/// <see cref="DependencyPipeline.Extractor"/> — replaced, leaving step 3's rows
/// alone — so item detection matches them like any other signal (Part A).</item>
/// <item>the <c>package_lookup_cache</c> entries this run fetched.</item>
/// </list>
/// </summary>
public sealed class DependencyDatabase(string connectionString)
{
    public async Task<string?> GetTargetFrameworkAsync(Guid repositoryId, CancellationToken ct)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(ct);
        await using var command = new NpgsqlCommand(
            "SELECT e.target_framework FROM repositories r JOIN engagements e ON e.id = r.engagement_id WHERE r.id = @id", connection);
        command.Parameters.AddWithValue("id", repositoryId);
        return await command.ExecuteScalarAsync(ct) as string;
    }

    public async Task ReplaceAllAsync(DependencyAssessmentArtifact artifact, PostgresLookupCache cache, Guid? stepExecutionId, CancellationToken ct)
    {
        await using var connection = new NpgsqlConnection(connectionString);
        await connection.OpenAsync(ct);
        await using var transaction = await connection.BeginTransactionAsync(ct);
        var assessedAt = DateTimeOffset.UtcNow;

        await Execute(connection, transaction, "DELETE FROM package_assessments WHERE repository_id = @rid", ("rid", artifact.RepositoryId));
        await Execute(connection, transaction, "DELETE FROM fingerprint_signals WHERE repository_id = @rid AND extractor = @extractor",
            ("rid", artifact.RepositoryId), ("extractor", DependencyPipeline.Extractor));

        foreach (var project in artifact.Projects)
        {
            foreach (var package in project.Packages)
            {
                await using var insert = new NpgsqlCommand(
                    """
                    INSERT INTO package_assessments
                        (id, repository_id, project_id, package_id, current_version, recommended_version, outcome, outcome_reason,
                         classification_method, deprecated, deprecation_replacement, vulnerable, vulnerability_max_severity,
                         vulnerabilities_resolved_by_upgrade, not_in_client_feed, latest_public_version, feed_source, feed_name, feed_url,
                         confidence, breaking_members, call_sites, step_execution_id, assessed_at,
                         package_kind, breaking_evidence, content_breaking_possible, version_drift)
                    VALUES
                        (@id, @rid, @pid, @package, @current, @recommended, @outcome, @reason,
                         @method, @deprecated, @replacement, @vulnerable, @severity,
                         @resolved, @gap, @public, @feed_source, @feed_name, @feed_url,
                         @confidence, @members, @sites, @sid, @at,
                         @kind, @evidence, @content_risk, @drift)
                    """,
                    connection, transaction);
                insert.Parameters.AddWithValue("id", package.AssessmentId);
                insert.Parameters.AddWithValue("rid", artifact.RepositoryId);
                insert.Parameters.AddWithValue("pid", project.ProjectId);
                insert.Parameters.AddWithValue("package", package.PackageId);
                insert.Parameters.AddWithValue("current", (object?)package.CurrentVersion ?? DBNull.Value);
                insert.Parameters.AddWithValue("recommended", (object?)package.RecommendedVersion ?? DBNull.Value);
                insert.Parameters.AddWithValue("outcome", package.Outcome);
                insert.Parameters.AddWithValue("reason", (object?)package.OutcomeReason ?? DBNull.Value);
                insert.Parameters.AddWithValue("method", (object?)package.ClassificationMethod ?? DBNull.Value);
                insert.Parameters.AddWithValue("deprecated", package.Deprecated is not null);
                insert.Parameters.AddWithValue("replacement", (object?)package.Deprecated?.ReplacementId ?? DBNull.Value);
                insert.Parameters.AddWithValue("vulnerable", package.Vulnerable is not null);
                insert.Parameters.AddWithValue("severity", (object?)package.Vulnerable?.MaxSeverity ?? DBNull.Value);
                insert.Parameters.AddWithValue("resolved", (object?)package.Vulnerable?.ResolvedByUpgrade ?? DBNull.Value);
                insert.Parameters.AddWithValue("gap", package.NotInClientFeed is not null);
                insert.Parameters.AddWithValue("public", (object?)package.NotInClientFeed?.LatestPublicVersion ?? DBNull.Value);
                insert.Parameters.AddWithValue("feed_source", (object?)package.FeedSource ?? DBNull.Value);
                insert.Parameters.AddWithValue("feed_name", (object?)package.FeedName ?? DBNull.Value);
                insert.Parameters.AddWithValue("feed_url", (object?)package.FeedUrl ?? DBNull.Value);
                insert.Parameters.AddWithValue("confidence", package.Confidence);
                insert.Parameters.Add(new NpgsqlParameter("members", NpgsqlDbType.Jsonb) { Value = Json(package.BreakingMembers) });
                insert.Parameters.Add(new NpgsqlParameter("sites", NpgsqlDbType.Jsonb) { Value = Json(package.CallSites) });
                insert.Parameters.AddWithValue("sid", (object?)stepExecutionId ?? DBNull.Value);
                insert.Parameters.AddWithValue("at", assessedAt);
                insert.Parameters.AddWithValue("kind", (object?)package.PackageKind ?? DBNull.Value);
                insert.Parameters.AddWithValue("evidence", (object?)package.BreakingEvidence ?? DBNull.Value);
                insert.Parameters.AddWithValue("content_risk", package.ContentBreakingPossible);
                insert.Parameters.AddWithValue("drift", package.VersionDrift);
                await insert.ExecuteNonQueryAsync(ct);
            }

            foreach (var signal in project.Signals)
            {
                await using var insert = new NpgsqlCommand(
                    """
                    INSERT INTO fingerprint_signals
                        (project_id, repository_id, signal_name, signal_category, signal_type, value, source_type, source_path,
                         evidence_kind, occurrence_count, evidence, extractor, extraction_confidence)
                    VALUES (@pid, @rid, @name, @category, @type, @value, @source_type, @source_path, @kind, @count, @evidence, @extractor, @confidence)
                    """,
                    connection, transaction);
                insert.Parameters.AddWithValue("pid", project.ProjectId);
                insert.Parameters.AddWithValue("rid", artifact.RepositoryId);
                insert.Parameters.AddWithValue("name", signal.Name);
                insert.Parameters.AddWithValue("category", signal.Category);
                insert.Parameters.AddWithValue("type", signal.Type);
                insert.Parameters.AddWithValue("value", (object?)signal.Value ?? DBNull.Value);
                insert.Parameters.AddWithValue("source_type", signal.SourceType);
                insert.Parameters.AddWithValue("source_path", (object?)signal.SourcePath ?? DBNull.Value);
                insert.Parameters.AddWithValue("kind", (object?)signal.EvidenceKind ?? DBNull.Value);
                insert.Parameters.AddWithValue("count", signal.OccurrenceCount);
                insert.Parameters.Add(new NpgsqlParameter("evidence", NpgsqlDbType.Jsonb) { Value = Json(signal.Evidence) });
                insert.Parameters.AddWithValue("extractor", signal.Extractor);
                insert.Parameters.AddWithValue("confidence", signal.ExtractionConfidence);
                await insert.ExecuteNonQueryAsync(ct);
            }
        }

        await cache.FlushAsync(connection, transaction, ct);
        await transaction.CommitAsync(ct);
    }

    private static async Task Execute(NpgsqlConnection connection, NpgsqlTransaction transaction, string sql, params (string, object)[] parameters)
    {
        await using var command = new NpgsqlCommand(sql, connection, transaction);
        foreach (var (name, value) in parameters) command.Parameters.AddWithValue(name, value);
        await command.ExecuteNonQueryAsync();
    }

    private static string Json<T>(T value) => JsonSerializer.Serialize(value, DeterministicJson.Options);
}

/// <summary>
/// The <c>package_lookup_cache</c> table (Part B6), keyed by
/// <c>(feed_url_normalised, package_id)</c>: <c>versions</c> is the version
/// list, newest first; <c>metadata</c> holds, per version, listing,
/// framework, deprecation and vulnerability data. Reads go to the table;
/// writes are held and flushed in the step's own transaction.
/// </summary>
public sealed class PostgresLookupCache(string connectionString) : ILookupCache
{
    private readonly Dictionary<(string, string), CacheEntry?> _read = [];
    private readonly Dictionary<(string, string), CacheEntry> _dirty = [];

    public CacheEntry? Get(string feedUrl, string packageId)
    {
        var key = (feedUrl, packageId.ToLowerInvariant());
        if (_dirty.TryGetValue(key, out var written)) return written;
        if (_read.TryGetValue(key, out var cached)) return cached;

        using var connection = new NpgsqlConnection(connectionString);
        connection.Open();
        using var command = new NpgsqlCommand(
            "SELECT versions::text, metadata::text, fetched_at FROM package_lookup_cache WHERE feed_url_normalised = @feed AND package_id = @id", connection);
        command.Parameters.AddWithValue("feed", feedUrl);
        command.Parameters.AddWithValue("id", key.Item2);
        using var reader = command.ExecuteReader();
        CacheEntry? entry = null;
        if (reader.Read())
        {
            var versions = JsonSerializer.Deserialize<List<string>>(reader.GetString(0)) ?? [];
            var metadata = JsonSerializer.Deserialize<Dictionary<string, CachedVersion>>(reader.GetString(1), DeterministicJson.Options) ?? [];
            entry = new CacheEntry
            {
                FeedUrl = feedUrl,
                PackageId = key.Item2,
                FetchedAt = reader.GetFieldValue<DateTimeOffset>(2),
                Versions = versions.Select(v => metadata.TryGetValue(v, out var m) ? m : new CachedVersion { Version = v }).ToList(),
            };
        }

        _read[key] = entry;
        return entry;
    }

    public void Put(CacheEntry entry) => _dirty[(entry.FeedUrl, entry.PackageId.ToLowerInvariant())] = entry;

    public async Task FlushAsync(NpgsqlConnection connection, NpgsqlTransaction transaction, CancellationToken ct)
    {
        foreach (var entry in _dirty.Values)
        {
            await using var upsert = new NpgsqlCommand(
                """
                INSERT INTO package_lookup_cache (feed_url_normalised, package_id, versions, metadata, fetched_at)
                VALUES (@feed, @id, @versions, @metadata, @at)
                ON CONFLICT (feed_url_normalised, package_id)
                DO UPDATE SET versions = EXCLUDED.versions, metadata = EXCLUDED.metadata, fetched_at = EXCLUDED.fetched_at
                """,
                connection, transaction);
            upsert.Parameters.AddWithValue("feed", entry.FeedUrl);
            upsert.Parameters.AddWithValue("id", entry.PackageId.ToLowerInvariant());
            upsert.Parameters.Add(new NpgsqlParameter("versions", NpgsqlDbType.Jsonb) { Value = JsonSerializer.Serialize(entry.Versions.Select(v => v.Version)) });
            upsert.Parameters.Add(new NpgsqlParameter("metadata", NpgsqlDbType.Jsonb)
            {
                Value = JsonSerializer.Serialize(entry.Versions.ToDictionary(v => v.Version), DeterministicJson.Options),
            });
            upsert.Parameters.AddWithValue("at", entry.FetchedAt);
            await upsert.ExecuteNonQueryAsync(ct);
        }
    }
}
