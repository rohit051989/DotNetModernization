import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ScanStatus = Literal["complete", "partial", "failed"]
ParseStatus = Literal["success", "partial", "failed", "out_of_scope"]
ProjectFormat = Literal["legacy_msbuild", "sdk_style", "unknown"]
ProjectLanguage = Literal["csharp", "vb", "fsharp", "sql", "ssis", "cpp", "shared", "unknown"]
SolutionProjectResolution = Literal["resolved", "unresolved"]
ProjectReferenceResolution = Literal["resolved", "unresolved", "external_repository"]
PackageDeclarationSource = Literal["packagereference", "packages_config"]
PackageManagementStyle = Literal["packagereference", "packages_config", "mixed", "none"]
RepositoryArtifactCategory = Literal[
    "build", "package", "pipeline", "container", "script", "configuration", "deployment", "documentation"
]


class ParseWarning(BaseModel):
    path: str = Field(description="Repository-relative path of the file the warning applies to.")
    warning: str = Field(description="Human-readable description of the parse limitation encountered.")


class RepositoryStructureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    repository_id: uuid.UUID = Field(description="The repository this summary belongs to.")
    scan_status: ScanStatus = Field(
        description="'complete' if failed_parse_count is 0, 'partial' if failed_parse_count > 0, "
        "'failed' if every recognised .NET project failed to parse. Out-of-scope and unknown project "
        "types never affect this — they are informational, not scan problems."
    )
    solution_count: int | None = Field(description="`.sln` files found on disk.")
    project_file_count: int | None = Field(description="Every project file found on disk, including out-of-scope and unknown ones.")
    projects_referenced_count: int | None = Field(description="Distinct projects referenced by any solution.")
    standalone_project_count: int | None = Field(description="On disk but referenced by no solution.")
    shared_project_count: int | None = Field(description="Referenced by more than one solution.")
    unresolved_reference_count: int | None = Field(
        description="Solution entries and <ProjectReference> declarations that did not resolve to a file."
    )
    out_of_scope_project_count: int | None = Field(
        description="Recognised non-.NET project type (Docker Compose, Node.js, Python, ...) — present and "
        "intentionally out of scope, not a failure. Does not affect scan_status."
    )
    unknown_project_count: int | None = Field(
        description="`*proj` extension that matches no known type at all, .NET or otherwise — recorded but "
        "not analysed. Does not affect scan_status."
    )
    failed_parse_count: int | None = Field(
        description="Files step 2 should have been able to parse but could not — a malformed .csproj or "
        ".sln, an unreadable encoding. The only category that drives scan_status: partial."
    )
    legacy_project_count: int | None = Field(description="project_format = 'legacy_msbuild'.")
    sdk_project_count: int | None = Field(description="project_format = 'sdk_style'.")
    framework_families: dict[str, int] = Field(description="Project count per normalised framework family.")
    artifact_counts: dict[str, int] = Field(description="Supporting-file count per category.")
    parse_warnings: list[ParseWarning] = Field(description="Every parse limitation hit during the scan, across solutions and projects.")
    scanned_at: datetime.datetime | None = Field(description="When solution-discovery last ran against this repository.")


class SolutionProjectMemberOut(BaseModel):
    raw_path: str = Field(description="As written in the `.sln`, backslashes preserved.")
    project_id: uuid.UUID | None = Field(description="Resolved project id, null when unresolved.")
    relative_path: str | None = Field(description="Resolved repository-relative path, null when unresolved.")
    project_guid: str | None = Field(description="GUID assigned to this entry within the solution.")
    project_type_guid: str | None = Field(description="Raw project-type GUID from the `.sln`. Not interpreted.")
    solution_folder: str | None = Field(description="Logical solution-folder path, null when at solution root.")
    resolution_status: SolutionProjectResolution = Field(description="Whether raw_path resolved to a file on disk.")


class SolutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str = Field(description="Solution file name, without extension.")
    relative_path: str = Field(description="Repository-relative path, forward-slash normalised.")
    format_version: str | None = Field(description="From the 'Format Version' header line.")
    visual_studio_version: str | None = Field(description="`VisualStudioVersion` line, if present.")
    minimum_vs_version: str | None = Field(description="`MinimumVisualStudioVersion` line, if present.")
    project_count: int | None = Field(description="Project entries declared, excluding solution folders.")
    resolved_project_count: int | None = Field(description="Of those, how many resolved to a file on disk.")
    missing_project_count: int | None = Field(description="project_count minus resolved_project_count.")
    solution_folder_count: int | None = Field(description="Entries with the solution-folder type GUID.")
    shared_project_count: int | None = Field(description="Member projects also referenced by another solution.")
    parse_status: ParseStatus
    parse_error: str | None = Field(description="Set when parse_status is 'failed'.")
    projects: list[SolutionProjectMemberOut] = Field(description="Every project entry declared by this solution.")


class ProjectPackageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    package_name: str
    version_raw: str | None = Field(description="Verbatim, including ranges and floating versions.")
    declaration_source: PackageDeclarationSource
    target_framework_raw: str | None = Field(description="From packages.config entries; null for PackageReference.")
    is_malformed: bool = Field(description="True when the declaration is missing a package name.")


class ProjectReferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_project_id: uuid.UUID
    source_relative_path: str = Field(description="Denormalised for display without a second lookup.")
    referenced_project_id: uuid.UUID | None
    referenced_relative_path: str | None = Field(description="Null when unresolved or external.")
    raw_path: str = Field(description="Verbatim from `<ProjectReference Include=...>`.")
    resolution_status: ProjectReferenceResolution
    is_cross_solution: bool = Field(description="True when source and target appear in different solutions.")


class ProjectSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    name: str
    relative_path: str
    extension: str
    structural_type: str = Field(description="Derived from extension only — see docs Part D.")
    project_format: ProjectFormat
    language: ProjectLanguage
    framework_family: str | None
    framework_version: str | None
    is_multi_targeting: bool
    solution_membership_count: int
    is_standalone: bool = Field(description="solution_membership_count = 0.")
    project_reference_count: int
    package_reference_count: int
    package_management_style: PackageManagementStyle
    has_packages_config: bool
    parse_status: ParseStatus


class ProjectDetailOut(ProjectSummaryOut):
    assembly_name: str | None
    root_namespace: str | None
    output_type: str | None = Field(description="Raw value: Library, Exe, WinExe, or null. Uninterpreted.")
    target_framework_raw: str | None = Field(description="First or only declared value, verbatim.")
    target_frameworks_raw: list[str] | None = Field(description="All declared values when multi-targeting.")
    parse_warnings: list[str]
    packages: list[ProjectPackageOut]
    project_references: list[ProjectReferenceOut] = Field(description="This project's own <ProjectReference> declarations.")
    referenced_by: list[ProjectReferenceOut] = Field(description="Other projects whose <ProjectReference> resolves to this one.")


class RepositoryArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: RepositoryArtifactCategory
    relative_path: str
    file_name: str


class EngagementStructureSummaryOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "engagement_id": "client-a-ocp4",
                    "repositories_scanned": 3,
                    "solution_count": 5,
                    "project_file_count": 42,
                    "standalone_project_count": 6,
                    "unresolved_reference_count": 2,
                    "legacy_project_count": 30,
                    "sdk_project_count": 12,
                    "framework_families": {"net-framework": 30, "net": 12},
                }
            ]
        }
    )

    engagement_id: str
    repositories_scanned: int = Field(description="Repositories with a repository_structure row — i.e. solution-discovery has run.")
    solution_count: int = Field(description="Sum of solution_count across scanned repositories.")
    project_file_count: int
    standalone_project_count: int
    unresolved_reference_count: int
    legacy_project_count: int
    sdk_project_count: int
    framework_families: dict[str, int] = Field(description="Project count per framework family, summed across repositories.")
