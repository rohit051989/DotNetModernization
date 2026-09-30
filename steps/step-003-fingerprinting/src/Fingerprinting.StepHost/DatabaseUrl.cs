using System.Text.RegularExpressions;
using Npgsql;

namespace Fingerprinting.StepHost;

public static partial class DatabaseUrl
{
    [GeneratedRegex(@"^(postgres(?:ql)?)\+[a-zA-Z0-9_]+://")]
    private static partial Regex DriverSuffix();

    /// <summary>
    /// Converts a libpq-style URL — optionally carrying a SQLAlchemy "+driver"
    /// suffix, e.g. <c>postgresql+psycopg://user:pass@host:port/db</c> per
    /// backend/.env.example — into an Npgsql keyword/value connection string.
    /// Mirrors step 2's discovery/persistence.py
    /// <c>_normalize_database_url</c>, adapted for Npgsql, which — unlike
    /// psycopg — does not parse URI-style connection strings directly.
    /// </summary>
    public static string ToNpgsqlConnectionString(string databaseUrl)
    {
        var withoutDriver = DriverSuffix().Replace(databaseUrl, "$1://");
        var uri = new Uri(withoutDriver);

        var builder = new NpgsqlConnectionStringBuilder
        {
            Host = uri.Host,
            Port = uri.IsDefaultPort ? 5432 : uri.Port,
            Database = uri.AbsolutePath.TrimStart('/'),
        };

        var userInfo = uri.UserInfo;
        if (!string.IsNullOrEmpty(userInfo))
        {
            var parts = userInfo.Split(':', 2);
            builder.Username = Uri.UnescapeDataString(parts[0]);
            if (parts.Length > 1)
            {
                builder.Password = Uri.UnescapeDataString(parts[1]);
            }
        }

        return builder.ConnectionString;
    }
}
