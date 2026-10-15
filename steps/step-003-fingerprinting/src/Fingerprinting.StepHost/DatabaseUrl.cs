using System.Text.RegularExpressions;
using Npgsql;

namespace Fingerprinting.StepHost;

public static partial class DatabaseUrl
{
    [GeneratedRegex(@"^(postgres(?:ql)?)\+[a-zA-Z0-9_]+://")]
    private static partial Regex DriverSuffix();

    [GeneratedRegex(@"(?:^|\s)-c\s*search_path=([A-Za-z0-9_]+)")]
    private static partial Regex SearchPathOption();

    /// <summary>
    /// Converts a libpq-style URL — optionally carrying a SQLAlchemy "+driver"
    /// suffix, e.g. <c>postgresql+psycopg://host:port/db?options=-csearch_path%3Dschema</c>
    /// — into an Npgsql keyword/value connection string. Npgsql, unlike psycopg,
    /// does not parse URI-style connection strings directly.
    ///
    /// The platform's URLs carry no credentials (01-ENVIRONMENT-SETUP.md section
    /// 10): the username and password come from the environment, PGUSER and
    /// PGPASSWORD, which the platform sets in the process this step inherits.
    /// The schema comes from the <c>options</c> query parameter's search_path.
    /// A URL that does carry user information is still read.
    /// </summary>
    public static string ToNpgsqlConnectionString(string databaseUrl)
    {
        var withoutDriver = DriverSuffix().Replace(databaseUrl, "$1://");
        var uri = new Uri(withoutDriver);

        var builder = new NpgsqlConnectionStringBuilder
        {
            Host = uri.Host,
            Port = uri.IsDefaultPort ? 5432 : uri.Port,
            Database = Uri.UnescapeDataString(uri.AbsolutePath.TrimStart('/')),
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
        else
        {
            builder.Username = Environment.GetEnvironmentVariable("PGUSER");
            builder.Password = Environment.GetEnvironmentVariable("PGPASSWORD");
        }

        foreach (var pair in uri.Query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var kv = pair.Split('=', 2);
            if (kv.Length == 2 && kv[0] == "options")
            {
                var match = SearchPathOption().Match(Uri.UnescapeDataString(kv[1]));
                if (match.Success)
                {
                    builder.SearchPath = match.Groups[1].Value;
                }
            }
        }

        return builder.ConnectionString;
    }
}
