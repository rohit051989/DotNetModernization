using Fingerprinting.StepHost;
using Npgsql;
using Xunit;

namespace Fingerprinting.Dependencies.Tests;

/// <summary>01-ENVIRONMENT-SETUP.md section 10: the platform's URLs carry no credentials, and name the schema as the
/// connection's search_path. The step programs take the username and password from PGUSER and PGPASSWORD.</summary>
public sealed class DatabaseUrlTests
{
    [Fact]
    public void A_credential_free_url_takes_its_login_from_the_environment_and_its_schema_from_the_options()
    {
        var user = Environment.GetEnvironmentVariable("PGUSER");
        var password = Environment.GetEnvironmentVariable("PGPASSWORD");
        try
        {
            Environment.SetEnvironmentVariable("PGUSER", "platform_user");
            Environment.SetEnvironmentVariable("PGPASSWORD", "s3cret");
            var built = new NpgsqlConnectionStringBuilder(DatabaseUrl.ToNpgsqlConnectionString(
                "postgresql+psycopg://db.corp.example:5433/modernization?options=-csearch_path%3Dmodplatform"));
            Assert.Equal(("db.corp.example", 5433, "modernization"), (built.Host, built.Port, built.Database));
            Assert.Equal(("platform_user", "s3cret"), (built.Username, built.Password));
            Assert.Equal("modplatform", built.SearchPath);
        }
        finally
        {
            Environment.SetEnvironmentVariable("PGUSER", user);
            Environment.SetEnvironmentVariable("PGPASSWORD", password);
        }
    }

    [Fact]
    public void A_url_without_options_has_no_search_path()
    {
        var built = new NpgsqlConnectionStringBuilder(DatabaseUrl.ToNpgsqlConnectionString("postgresql://u:p@localhost/db"));
        Assert.Equal(("u", "p", 5432), (built.Username, built.Password, built.Port));
        Assert.Null(built.SearchPath);
    }
}
