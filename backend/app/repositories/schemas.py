import datetime
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.workflow.runtime.schemas import JobExecutionOut

Criticality = Literal["low", "medium", "high", "critical"]
RetirementStatus = Literal["active", "slated_for_retirement", "decommissioned"]
CloneUrlVerification = Literal["verified", "mismatch", "unverifiable", "not_applicable"]
IngestStatus = Literal["registered", "cloning", "scanned", "scan_failed", "path_missing"]
SourceStatus = Literal["active", "archived", "disabled", "inaccessible"]
SourceControlStatus = Literal["GIT", "NONE"]


class PrimaryLanguage(BaseModel):
    language: str = Field(description="Language name mapped from file extension.")
    file_count: int = Field(description="Count of files with a mapped extension for this language.")
    percentage: float = Field(description="Share of counted files, rounded to one decimal.")


# ---------- Path inspection ----------


class InspectPathRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"local_path": "D:\\repos\\order-management"}]})

    local_path: str = Field(
        description="Absolute path on the machine running the platform to inspect.",
        examples=["D:\\repos\\order-management"],
    )


class DuplicateConflict(BaseModel):
    matched_on: Literal["clone_url", "root_folder_name", "local_path"] = Field(
        description="Which duplicate-detection check this path or URL collides on."
    )
    repository_id: str = Field(description="Id of the already-registered repository it collides with.")
    slug: str = Field(description="Slug of the already-registered repository.")
    message: str = Field(description="Human-readable conflict description, ready to render as a blocking form error.")


class InspectPathResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "exists": True,
                    "is_directory": True,
                    "root_folder_name": "order-management",
                    "suggested_name": "order-management",
                    "suggested_slug": "order-management",
                    "has_git": True,
                    "source_control_status": "GIT",
                    "detected_clone_url": "https://github.com/example/order-management.git",
                    "detected_provider": "github",
                    "detected_branch": "main",
                    "detected_commit_sha": "a1b2c3d4e5f6",
                    "estimated_file_count": 1842,
                    "estimated_size_bytes": 48210040,
                    "solution_files_found": 2,
                    "project_files_found": 14,
                    "duplicate_conflict": None,
                    "warnings": [],
                }
            ]
        }
    )

    exists: bool = Field(description="Whether the path exists on disk at all.")
    is_directory: bool = Field(description="Whether the path, if it exists, is a directory.")
    root_folder_name: str | None = Field(description="Last path segment. Null if the path doesn't exist.")
    suggested_name: str | None = Field(description="Prefill for the registration form's name field.")
    suggested_slug: str | None = Field(description="Prefill slug, normalised from root_folder_name.")
    has_git: bool = Field(description="Whether a .git directory was found.")
    source_control_status: SourceControlStatus = Field(
        description="'GIT' if a .git directory was found, 'NONE' otherwise. Tells the form whether clone_url is required."
    )
    detected_clone_url: str | None = Field(description="The folder's git origin remote URL, if any.")
    detected_provider: str | None = Field(description="Host-derived provider for the detected clone URL.")
    detected_branch: str | None = Field(description="Current branch, if git history is present.")
    detected_commit_sha: str | None = Field(description="HEAD commit SHA, if git history is present.")
    estimated_file_count: int | None = Field(
        description="Sampled, capped estimate — not exhaustive. Label as an estimate in the UI."
    )
    estimated_size_bytes: int | None = Field(description="Sampled, capped estimate — not exhaustive.")
    solution_files_found: int | None = Field(description="Shallow count of .sln files — a confidence signal, not analysis.")
    project_files_found: int | None = Field(description="Shallow count of .csproj files — a confidence signal, not analysis.")
    duplicate_conflict: DuplicateConflict | None = Field(
        description="Set when this path or its detected clone URL already matches a registered repository in this engagement."
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-blocking notices: no .git found, folder appears empty, no .sln/.csproj found, or the path looks like a network location.",
    )


# ---------- Registration ----------


class RegisterLocalPathRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "source_type": "local_path",
                    "local_path": "D:\\repos\\order-management",
                    "name": "Order Management",
                    "clone_url": "https://github.com/example/order-management.git",
                    "description": "Core ordering API and background workers",
                    "technical_owner": "A. Kumar",
                    "criticality": "high",
                    "retirement_status": "active",
                    "default_branch": "main",
                    "tags": ["billing"],
                    "notes": "",
                }
            ]
        }
    )

    source_type: Literal["local_path"] = Field(description="Must be 'local_path' — the only implemented source.")
    local_path: str = Field(description="Absolute path to the repository folder. Immutable once registered.")
    name: str | None = Field(default=None, description="Display name. Defaults to the folder's name.")
    clone_url: str | None = Field(
        default=None,
        description=(
            "The repository's canonical URL — https, git@host:org/repo.git or ssh://[user@]host[:port]/org/repo.git "
            "— asserted by the operator and verified against the folder's origin remote. Required when the folder "
            "is a git repository with an origin remote; optional otherwise — a folder never under source control, "
            "or a repository with no remote at all, has nothing to verify against. May still be supplied there; "
            "it is recorded unverified."
        ),
    )
    description: str | None = Field(default=None, description="What this repository contains.")
    technical_owner: str | None = Field(default=None, description="Who to ask about this repository.")
    criticality: Criticality = Field(
        default="medium", description="Business criticality. Feeds review tier assignment (risk-scoring-tier-assignment)."
    )
    retirement_status: RetirementStatus = Field(
        default="active",
        description="Repositories not 'active' are still registered and scanned, but excluded from modernization scope counts on the dashboard.",
    )
    default_branch: str | None = Field(default=None, description="Detected or operator-supplied default branch.")
    tags: list[str] = Field(default_factory=list, description="Free-form labels for filtering.")
    notes: str | None = Field(default=None, description="Free text.")


class RegisterGitCloneRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "source_type": "git_clone",
                    "clone_url": "https://git.client.com/team/order-management.git",
                    "branch": "main",
                    "target_folder": None,
                    "name": "Order Management",
                }
            ]
        }
    )

    source_type: Literal["git_clone"] = Field(description="Register by the repository's git URL: the platform clones it.")
    clone_url: str = Field(
        description=(
            "The repository's git URL: https, git@host:org/repo.git, ssh://[user@]host[:port]/org/repo.git, or "
            "file:/// for a repository in a folder or on a share. Never with a credential in it: git signs in as you, "
            "with Git Credential Manager or your SSH key."
        )
    )
    branch: str | None = Field(default=None, description="The branch to clone and track. Default: the remote's default branch.")
    target_folder: str | None = Field(
        default=None,
        description=(
            "Where to clone it: an absolute folder that does not exist or is empty, or an existing clone of the same "
            "URL, which is used as it is. Default: <REPOS_DIR>/<engagement>/<repository>; required when REPOS_DIR is not set."
        ),
    )
    name: str | None = Field(default=None, description="Display name. Defaults to the repository's name in the URL.")
    description: str | None = Field(default=None, description="What this repository contains.")
    technical_owner: str | None = Field(default=None, description="Who to ask about this repository.")
    criticality: Criticality = Field(default="medium", description="Business criticality.")
    retirement_status: RetirementStatus = Field(default="active", description="Retirement status.")
    tags: list[str] = Field(default_factory=list, description="Free-form labels for filtering.")
    notes: str | None = Field(default=None, description="Free text.")


class InspectUrlRequest(BaseModel):
    clone_url: str = Field(description="The git URL to register.")
    target_folder: str | None = Field(default=None, description="The folder to clone into, when not the default.")


class InspectUrlResponse(BaseModel):
    problems: list[str] = Field(description="Why this URL or target folder cannot be registered. Empty when it can.")
    suggested_name: str | None = Field(description="The repository's name, from the URL.")
    repos_dir: str | None = Field(description="REPOS_DIR, or null when it is not set (the target folder must then be given).")
    target_folder: str | None = Field(description="Where it would be cloned: the folder given, or the default under REPOS_DIR.")
    target_action: Literal["clone", "reuse", "refuse"] | None = Field(
        description="clone: the folder does not exist or is empty. reuse: it is already a clone of this URL, used as it is."
    )
    target_message: str | None = Field(description="What will happen to the target folder, in words.")
    duplicate_conflict: DuplicateConflict | None = Field(description="Set when this URL or folder is already registered in this engagement.")


RegisterRepositoryRequest = Annotated[
    RegisterLocalPathRequest | RegisterGitCloneRequest, Field(discriminator="source_type")
]


class RegisterRepositoryResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "repository_id": "3f2b8c14-9d7e-4a51-b6c2-8e1d4f70a9b3",
                    "slug": "order-management",
                    "ingest_token": "c81d4e2f-6a3b-4f19-9c7d-2e5a8b1f30c6",
                    "job_execution_id": "9c2e6f1a-1234-4a51-b6c2-8e1d4f70a9b3",
                    "clone_url_verification": "verified",
                    "status": "processing",
                }
            ]
        }
    )

    repository_id: str = Field(description="The newly registered repository's id.")
    slug: str = Field(description="Normalised slug identifying the repository within its engagement.")
    ingest_token: str = Field(description="UUID for this registration's discovery run.")
    job_execution_id: str = Field(
        description="Trackable execution id — discovery runs asynchronously; poll GET /api/workflow/executions/{id} or GET /api/repositories/{id}."
    )
    clone_url_verification: CloneUrlVerification = Field(description="Result of verifying clone_url against the folder's git remote.")
    status: Literal["processing"] = Field(description="Always 'processing' — discovery has just been launched.")


# ---------- Repository read/update ----------


class RepositorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(description="This repository's id.")
    engagement_id: str = Field(description="The engagement this repository is registered under.")
    name: str = Field(description="Display name.")
    root_folder_name: str = Field(description="Last path segment of local_path. Immutable.")
    slug: str = Field(description="Normalised slug, unique within the engagement.")
    source_type: Literal["local_path", "git_clone"] = Field(description="How this repository was registered.")
    provider: str | None = Field(description="Derived from the asserted clone URL's host.")
    criticality: Criticality = Field(description="Business criticality.")
    retirement_status: RetirementStatus = Field(description="'active', 'slated_for_retirement', or 'decommissioned'.")
    ingest_status: IngestStatus = Field(description="'registered', 'scanned', 'scan_failed', or 'path_missing'.")
    has_git_history: bool = Field(description="Whether the folder had a .git directory at the last scan.")
    clone_url_verification: CloneUrlVerification = Field(description="Result of the last clone URL verification.")
    size_bytes: int | None = Field(description="Total size at the last scan, skipping .git/node_modules/bin/obj/packages.")
    file_count: int | None = Field(description="Total file count at the last scan, same exclusions.")
    last_scanned_at: datetime.datetime | None = Field(description="When step 1 last ran against this repository.")
    deleted_at: datetime.datetime | None = Field(description="When this repository was soft-deleted, or null if live.")
    clone_progress: str | None = Field(default=None, description="git's latest progress line while the repository is cloned (ingest_status 'cloning').")
    ingest_error: str | None = Field(default=None, description="Why the last discovery's ingest failed, if it did: a clone or fetch error says how to fix it.")


class RepositoryDetail(RepositorySummary):
    local_path: str = Field(description="Absolute path on the operating machine. Identity — never changes.")
    clone_url: str | None = Field(
        description="Operator-asserted canonical URL. Identity — never changes. Null for a folder never under source control, unless the operator supplied one anyway."
    )
    source_control_status: SourceControlStatus = Field(
        description="'GIT' if the folder has a .git directory (re-checked on every scan), 'NONE' otherwise."
    )
    detected_clone_url: str | None = Field(description="What .git actually reports. Null when no git remote.")
    default_branch: str | None = Field(description="Detected or operator-supplied default branch.")
    organization: str | None = Field(
        description="First path segment of the clone URL, e.g. 'acme' from github.com/acme/orders. Null when unparseable."
    )
    last_commit_date: datetime.datetime | None = Field(
        description="Committer date of HEAD at the last scan. Null when has_git_history is false."
    )
    primary_languages: list[PrimaryLanguage] | None = Field(
        description="Top 6 languages by file count from the last scan, descending, same exclusions as size_bytes/file_count. Null before the first scan."
    )
    source_status: SourceStatus | None = Field(
        description="What the source-control platform reports. Only knowable via a provider API — always null for local_path."
    )
    description: str | None = Field(description="What this repository contains.")
    technical_owner: str | None = Field(description="Who to ask about this repository.")
    tags: list[str] = Field(description="Free-form labels.")
    notes: str | None = Field(description="Free text.")
    ingest_commit_sha: str | None = Field(description="HEAD SHA at the last scan. Null when has_git_history is false.")
    ingest_token: str | None = Field(description="Most recent token; correlates to the current job instance.")
    first_registered_at: datetime.datetime | None = Field(description="Set once, at registration.")
    created_at: datetime.datetime = Field(description="Row creation time.")
    updated_at: datetime.datetime = Field(description="Last modification time.")
    deleted_by: str | None = Field(description="Free-text identity that soft-deleted this repository, if any.")
    latest_execution: JobExecutionOut | None = Field(
        default=None, description="The most recent phase0-repository-discovery execution for this repository, if any."
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Existing data a later rule would refuse, reported and left working: for example this checkout also registered in another engagement.",
    )


class RepositoryUpdate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Order Management",
                    "description": "Core ordering API and background workers",
                    "technical_owner": "A. Kumar",
                    "criticality": "high",
                    "retirement_status": "active",
                    "tags": ["billing"],
                    "notes": "",
                    "default_branch": "main",
                }
            ]
        }
    )

    name: str = Field(description="Display name.")
    description: str | None = Field(default=None, description="What this repository contains.")
    technical_owner: str | None = Field(default=None, description="Who to ask about this repository.")
    criticality: Criticality = Field(default="medium", description="Business criticality.")
    retirement_status: RetirementStatus = Field(default="active", description="'active', 'slated_for_retirement', or 'decommissioned'.")
    tags: list[str] = Field(default_factory=list, description="Free-form labels.")
    notes: str | None = Field(default=None, description="Free text.")
    default_branch: str | None = Field(default=None, description="Default branch.")


class RepositorySoftDeleteResponse(BaseModel):
    id: uuid.UUID = Field(description="This repository's id.")
    deleted_at: datetime.datetime | None = Field(description="When the soft delete took effect, or null if restored.")


class RescanResponse(BaseModel):
    repository_id: uuid.UUID = Field(description="The repository being rescanned.")
    ingest_token: str = Field(description="Newly generated token — this rescan is a distinct job instance, not a restart.")
    job_execution_id: uuid.UUID = Field(description="Trackable execution id for this rescan.")
    status: Literal["processing"] = Field(description="Always 'processing' — the rescan has just been launched.")


class VerifyPathResponse(BaseModel):
    repository_id: uuid.UUID = Field(description="The repository checked.")
    exists: bool = Field(description="Whether local_path currently exists as a directory.")
    ingest_status: IngestStatus = Field(description="Set to 'path_missing' when the folder has gone; otherwise unchanged.")
