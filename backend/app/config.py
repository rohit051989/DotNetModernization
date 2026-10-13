from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _default_platform_root() -> str:
    # backend/app/config.py -> backend/app -> backend -> repository root.
    return str(Path(__file__).resolve().parents[2])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"
    # Where every engagement's run output, verifications and experiments live: engagement data, never the
    # repository's. A relative value is resolved against backend/; a client deployment sets an absolute folder
    # outside the repository (01-ENVIRONMENT-SETUP.md section 9). Read it through runs_path.
    runs_dir: str = "./runs"
    # What this deployment is. The platform ships to each client as code and that client's data
    # lives only in its database, so the default is a client deployment. Only an explicit
    # DEPLOYMENT=demo lets the demo reset (app.seed.reset_demo) clear engagements and repositories.
    deployment: str = "client"
    artifact_inline_max_bytes: int = 5 * 1024 * 1024

    # The single machine this platform runs on (CLAUDE.md's operating model).
    # A relative `command` or `cwd` in a process-adapter step's adapter_config
    # is resolved against this, never against the backend process's own
    # working directory — see 11-STEP-CONTRACT.md's "process" adapter section.
    # Defaults to the repository root two levels above this file; override in
    # .env only if the backend package is ever relocated relative to the repo.
    platform_root: str = Field(default_factory=_default_platform_root)

    @property
    def runs_path(self) -> Path:
        """runs_dir as an absolute path, the same whatever the working directory."""
        path = Path(self.runs_dir)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
