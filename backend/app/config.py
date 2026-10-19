"""The platform's settings, from the environment and backend/.env (gitignored; .env.example is committed).

The database (01-ENVIRONMENT-SETUP.md section 10): where it is comes from configuration — DB_HOST, DB_PORT,
DB_NAME and DB_SCHEMA (every table, sequence and the migration version table live in that schema, `public` by
default). Who connects comes only from the environment: DB_USER and DB_PASSWORD, which a gitignored .env may
supply. They are handed to PostgreSQL's client libraries as PGUSER and PGPASSWORD in this process's environment,
which the step programs inherit, and are never put in a connection URL, a step's context, a log or a file. A
connection error never echoes them (app.db).
"""
import os
import re
from pathlib import Path
from urllib.parse import quote

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND_DIR / ".env"
SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _default_platform_root() -> str:
    # backend/app/config.py -> backend/app -> backend -> repository root.
    return str(Path(__file__).resolve().parents[2])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    # The database. Configuration: where it is. Environment only: who connects.
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str
    db_schema: str = "public"
    db_user: str | None = None
    db_password: SecretStr | None = None

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"
    # Where every engagement's run output, verifications, conversions and experiments live: engagement data, never
    # the repository's. It must be outside the repository (01-ENVIRONMENT-SETUP.md section 9): a relative value is
    # resolved against backend/, and one that lands inside the repository is refused. Read it through runs_path.
    runs_dir: str
    # Where repositories registered by their git URL are cloned by default: <REPOS_DIR>\<engagement>\<repository>.
    # Optional: unset, the registration form asks for the target folder. A short absolute path, outside the
    # repository and outside RUNS_DIR (docs/VDI-SETUP.md: Registering a client repository). Read it through repos_path.
    repos_dir: str = ""
    # What this deployment is. The platform ships to each client as code and that client's data
    # lives only in its database, so the default is a client deployment. Only an explicit
    # DEPLOYMENT=demo lets the demo reset (app.seed.reset_demo) clear engagements and repositories.
    deployment: str = "client"
    artifact_inline_max_bytes: int = 5 * 1024 * 1024

    # Package sources (the client network, 01-ENVIRONMENT-SETUP.md section 10). The platform's own dependencies
    # install from these (scripts/bootstrap.ps1, read by app.preflight); empty means the public default. Dependency
    # assessment's comparison of a client feed with nuget.org can be switched off where nuget.org is unreachable.
    pip_index_url: str = ""
    npm_registry: str = ""
    nuget_sources: str = ""              # comma-separated: feed URLs or local folders for the step programs' restore
    compare_public_nuget_feed: bool = True

    # A .NET installed per user (docs/VDI-SETUP.md: Account settings). When set, this folder goes first on PATH and becomes
    # DOTNET_ROOT for this process and so for every process it starts: the step programs (which find their runtime
    # through DOTNET_ROOT), the package step's and the verifier's dotnet builds and tests. Unset: the dotnet on PATH,
    # with the runtime found as usual.
    dotnet_root: str = ""
    # The Python interpreter bootstrap and preflight use (scripts/bootstrap.ps1, scripts/preflight.py); the backend
    # itself always runs in backend/.venv. Unset: python on PATH.
    python: str = ""

    # The single machine this platform runs on (CLAUDE.md's operating model).
    # A relative `command` or `cwd` in a process-adapter step's adapter_config
    # is resolved against this, never against the backend process's own
    # working directory — see 11-STEP-CONTRACT.md's "process" adapter section.
    # Defaults to the repository root two levels above this file; override in
    # .env only if the backend package is ever relocated relative to the repo.
    platform_root: str = Field(default_factory=_default_platform_root)

    @field_validator("db_schema")
    @classmethod
    def _schema_name(cls, value: str) -> str:
        if not SCHEMA_NAME.match(value):
            raise ValueError(f"DB_SCHEMA {value!r} is not a plain lower-case schema name ([a-z_][a-z0-9_]*)")
        return value

    @model_validator(mode="after")
    def _no_url_with_credentials(self) -> "Settings":
        if os.environ.get("DATABASE_URL") or (ENV_FILE.exists() and re.search(
                r"(?m)^\s*DATABASE_URL\s*=", ENV_FILE.read_text(encoding="utf-8", errors="replace"))):
            raise ValueError("DATABASE_URL is no longer read: set DB_HOST, DB_PORT, DB_NAME and DB_SCHEMA in "
                             "backend/.env, and DB_USER and DB_PASSWORD in the environment or backend/.env "
                             "(docs/VDI-SETUP.md: backend\\.env)")
        return self

    @property
    def runs_path(self) -> Path:
        """runs_dir as an absolute path, the same whatever the working directory. Refused inside the repository."""
        path = Path(self.runs_dir)
        path = path if path.is_absolute() else (BACKEND_DIR / path).resolve()
        if path.resolve().is_relative_to(Path(self.platform_root).resolve()):
            raise ValueError(f"RUNS_DIR {path} is inside the repository: engagement data must live outside it "
                             "(set RUNS_DIR in backend/.env; 01-ENVIRONMENT-SETUP.md section 9)")
        return path

    @property
    def repos_path(self) -> Path | None:
        """repos_dir as an absolute path, or None when unset. Refused inside the repository or inside RUNS_DIR: the
        clones are the client's repositories, kept apart from the platform's code and its run output."""
        if not self.repos_dir.strip():
            return None
        path = Path(self.repos_dir.strip())
        if not path.is_absolute():
            raise ValueError(f"REPOS_DIR {path} is not an absolute path (docs/VDI-SETUP.md: backend\\.env)")
        if path.resolve().is_relative_to(Path(self.platform_root).resolve()):
            raise ValueError(f"REPOS_DIR {path} is inside the platform's folder: clone the client's repositories "
                             "outside it (docs/VDI-SETUP.md: backend\\.env)")
        if path.resolve().is_relative_to(self.runs_path.resolve()):
            raise ValueError(f"REPOS_DIR {path} is inside RUNS_DIR: keep the clones apart from the run output "
                             "(docs/VDI-SETUP.md: backend\\.env)")
        return path

    @property
    def database_url(self) -> str:
        """The connection URL, without credentials: host, port, database, and the schema as the connection's
        search_path. PGUSER and PGPASSWORD supply the credentials (apply_credentials)."""
        return database_url(self.db_schema, self)

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def nuget_sources_list(self) -> list[str]:
        return [s.strip() for s in self.nuget_sources.split(",") if s.strip()]

    def secrets(self) -> list[str]:
        """The values no message may show: the username and the password."""
        return [v for v in (self.db_user, self.db_password.get_secret_value() if self.db_password else None) if v]


def database_url(schema: str, s: "Settings | None" = None) -> str:
    """A credential-free URL for `schema` in the configured database: the platform's own schema, or a scratch one."""
    s = s or settings
    if not SCHEMA_NAME.match(schema):
        raise ValueError(f"{schema!r} is not a plain lower-case schema name")
    return (f"postgresql+psycopg://{quote(s.db_host)}:{s.db_port}/{quote(s.db_name)}"
            f"?options={quote(f'-csearch_path={schema}', safe='')}")


def apply_credentials(s: "Settings") -> None:
    """DB_USER and DB_PASSWORD into this process's environment as PGUSER and PGPASSWORD, which libpq (psycopg) and
    the step programs read. The only place they go."""
    if s.db_user:
        os.environ["PGUSER"] = s.db_user
    if s.db_password:
        os.environ["PGPASSWORD"] = s.db_password.get_secret_value()


# The .NET SDK the platform runs (builds, tests, the step programs) contacts nothing of its own accord: no usage
# telemetry, no workload update check, and no first-run ASP.NET development certificate, which would be written to
# the user's certificate store (CLAUDE.md rule 14). Set for this process and every process it starts; an explicit
# value in the environment wins. The only destinations left are the database and the package feeds
# (01-ENVIRONMENT-SETUP.md section 10).
QUIET_DOTNET = {
    "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
    "DOTNET_NOLOGO": "1",
    "DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE": "1",
    "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
    "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",
}


def quiet_dotnet() -> None:
    for name, value in QUIET_DOTNET.items():
        os.environ.setdefault(name, value)


def apply_dotnet_root(s: "Settings") -> None:
    """DOTNET_ROOT, when set, for this process and every process it starts: the folder first on PATH, so `dotnet`
    is that SDK's, and DOTNET_ROOT, so the framework-dependent step programs find that runtime. Refuses a folder
    without dotnet.exe, rather than letting builds quietly use another SDK."""
    if not s.dotnet_root:
        return
    root = Path(s.dotnet_root)
    if not (root / ("dotnet.exe" if os.name == "nt" else "dotnet")).is_file():
        raise ValueError(f"DOTNET_ROOT {root} has no dotnet executable: set it to the folder the .NET SDK was installed "
                         "into (docs/VDI-SETUP.md: Account settings), or leave it empty")
    os.environ["DOTNET_ROOT"] = str(root)
    path = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p and Path(p) != root]
    os.environ["PATH"] = os.pathsep.join([str(root), *path])


settings = Settings()
apply_credentials(settings)
quiet_dotnet()
apply_dotnet_root(settings)
