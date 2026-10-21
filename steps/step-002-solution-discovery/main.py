"""Lifecycle step 2 — solution & project discovery per repository.

Reads a StepContext JSON envelope from stdin, writes a StepResult JSON
envelope to stdout — see 11-STEP-CONTRACT.md and
19-SOLUTION-DISCOVERY.md.

Standalone by design (Part B): invoked via the platform's `process` adapter,
but must not import from `backend.app`, and reads `local_path` from the
resolved `repository-inventory` artifact rather than the database — so it
runs on its own against a hand-written sample-context.json with nothing but
a Postgres connection (and not even that, if `database_url` is omitted).

Read-only against the registered folder, same as step 1: this module only
ever opens files under the repository's `local_path` for reading, and
writes exclusively under `output_dir` (plus the discovery tables it owns).
"""

import datetime
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

from discovery import artifact_scanner, framework, persistence, project_parser, solution_parser
from discovery.progress import Progress
from discovery.paths import walk_files
from discovery.project_parser import OUT_OF_SCOPE_STRUCTURAL_TYPES

ARTIFACT_TYPE = "solution-project-inventory"
ARTIFACT_VERSION = "2.1.0"

_WINDOWS_DRIVE_RE = re.compile(r"^/[A-Za-z]:")

_SUMMARY_FIELDS = (
    "solution_count",
    "project_file_count",
    "projects_referenced_count",
    "standalone_project_count",
    "shared_project_count",
    "unresolved_reference_count",
    "out_of_scope_project_count",
    "unknown_project_count",
    "failed_parse_count",
    "legacy_project_count",
    "sdk_project_count",
    "framework_families",
    "artifact_counts",
)


def _local_path_from_uri(uri: str) -> Path:
    """Resolves a `file://` (or bare-path) artifact URI to a local path.
    Duplicated from the engine's adapter base (app/workflow/adapters/base.py)
    — small enough that copying it is cheaper than coupling to backend.app."""
    parsed = urlparse(uri)
    if parsed.scheme not in ("", "file"):
        raise ValueError(f"unsupported artifact URI scheme '{parsed.scheme}' in '{uri}'")
    raw = unquote(parsed.path) if parsed.scheme == "file" else uri
    if _WINDOWS_DRIVE_RE.match(raw):
        raw = raw[1:]  # file:///D:/... parses to a leading-slash path pathlib mishandles on Windows
    return Path(raw)


def _sha256_uri(uri: str) -> str:
    digest = hashlib.sha256(_local_path_from_uri(uri).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _new_id() -> str:
    return str(uuid.uuid4())


# Fixed namespace for project ids. Never change it: every project id in every
# database is derived from it, and changing it orphans all of them.
PROJECT_ID_NAMESPACE = uuid.UUID("5f0c2a8e-6d1b-4c3e-9a7f-2b8d4e6f1a93")


def project_id_for(repository_id: str, relative_path: str) -> str:
    """Stable across rescans: the same project in the same repository always
    gets the same id, so a rescan updates its row instead of replacing it,
    and anything keyed to project_id (item occurrences, decisions, conversion
    executions) survives a rescan mid-migration. Lower-cased because Windows
    paths are case-insensitive, the same key step 2 already resolves solution
    entries and project references by."""
    return str(uuid.uuid5(PROJECT_ID_NAMESPACE, f"{repository_id}:{relative_path.replace(chr(92), '/').lower()}"))


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _failed(message: str) -> dict:
    return {"envelope_version": "1.0", "exit_status": "FAILED", "exit_message": message}


def _resolve_raw_path(raw_path: str, containing_dir: Path, repo_root: Path) -> tuple[str | None, bool]:
    """Normalises backslashes, resolves relative to `containing_dir`, then
    to the repository root. Returns (relative_path_or_None, escapes_root).
    A resolved path escaping the repository root is a distinct outcome from
    "does not exist" (Part F)."""
    normalized = raw_path.replace("\\", "/")
    try:
        resolved = (containing_dir / normalized).resolve()
    except OSError:
        return None, False
    try:
        relative = resolved.relative_to(repo_root).as_posix()
    except ValueError:
        return None, True
    return relative, False


def _scan(repo_root: Path, inventory: dict, repository_id: str, progress: Progress | None = None) -> dict:
    progress = progress or Progress(None)
    progress.phase("find solutions")
    sln_paths = sorted(p for p in walk_files(repo_root) if p.suffix.lower() == ".sln")
    progress.phase("solutions", len(sln_paths))
    parsed_solutions = []
    for p in sln_paths:
        progress.begin(p.relative_to(repo_root).as_posix(), "solution")
        parsed_solutions.append(solution_parser.parse(p, repo_root))

    progress.phase("find projects")
    project_paths = project_parser.find_project_files(repo_root)
    # Each project file is parsed once, however many solutions include it (release 5).
    progress.phase("projects", len(project_paths))
    parsed_projects_raw = []
    for p in project_paths:
        progress.begin(p.relative_to(repo_root).as_posix(), "project")
        parsed_projects_raw.append(project_parser.parse(p, repo_root))
    progress.phase("relate")

    # Ids stable across rescans (project_id_for), indexed by lowercased
    # relative path — Windows filesystems are case-insensitive, and this
    # index is how solution entries and <ProjectReference> paths resolve to a
    # project.
    projects_by_id: dict[str, dict] = {}
    projects_index: dict[str, str] = {}
    for parsed in parsed_projects_raw:
        project_id = project_id_for(repository_id, parsed["relative_path"])
        projects_by_id[project_id] = parsed
        projects_index[parsed["relative_path"].lower()] = project_id

    # ---- Solutions: resolve membership against the project index ----
    db_solution_projects = []
    membership_count = {pid: 0 for pid in projects_by_id}
    solutions_of: dict[str, set] = {pid: set() for pid in projects_by_id}
    solution_rows = []

    for solution_path, parsed_solution in zip(sln_paths, parsed_solutions):
        solution_id = _new_id()
        containing_dir = solution_path.parent
        folder_names_by_guid = {
            e["project_guid"]: e["name"] for e in parsed_solution["entries"] if e["is_folder"]
        }
        member_entries = []
        for entry in parsed_solution["entries"]:
            if entry["is_folder"]:
                continue
            resolved_rel, _escapes = _resolve_raw_path(entry["raw_path"], containing_dir, repo_root)
            project_id = projects_index.get(resolved_rel.lower()) if resolved_rel else None
            resolution_status = "resolved" if project_id else "unresolved"
            if project_id:
                membership_count[project_id] += 1
                solutions_of[project_id].add(solution_id)
            member_entries.append(
                {
                    "id": _new_id(),
                    "solution_id": solution_id,
                    "project_id": project_id,
                    "raw_path": entry["raw_path"],
                    "project_guid": entry["project_guid"],
                    "project_type_guid": entry["type_guid"],
                    "solution_folder": solution_parser.solution_folder_path(
                        entry["project_guid"], parsed_solution["nested"], folder_names_by_guid
                    ),
                    "resolution_status": resolution_status,
                    "resolved_relative_path": resolved_rel,
                }
            )
        db_solution_projects.extend(member_entries)
        solution_rows.append((solution_id, parsed_solution, member_entries))

    db_solutions = []
    artifact_solutions = []
    for solution_id, parsed_solution, member_entries in solution_rows:
        project_count = len(member_entries)
        resolved_count = sum(1 for m in member_entries if m["resolution_status"] == "resolved")
        missing_count = project_count - resolved_count
        folder_count = sum(1 for e in parsed_solution["entries"] if e["is_folder"])
        shared_count = sum(
            1
            for m in member_entries
            if m["resolution_status"] == "resolved" and membership_count[m["project_id"]] > 1
        )
        db_solutions.append(
            {
                "id": solution_id,
                "name": parsed_solution["name"],
                "relative_path": parsed_solution["relative_path"],
                "format_version": parsed_solution["format_version"],
                "visual_studio_version": parsed_solution["visual_studio_version"],
                "minimum_vs_version": parsed_solution["minimum_vs_version"],
                "project_count": project_count,
                "resolved_project_count": resolved_count,
                "missing_project_count": missing_count,
                "solution_folder_count": folder_count,
                "shared_project_count": shared_count,
                "parse_status": parsed_solution["parse_status"],
                "parse_error": parsed_solution["parse_error"],
            }
        )
        artifact_solutions.append(
            {
                "relative_path": parsed_solution["relative_path"],
                "name": parsed_solution["name"],
                "format_version": parsed_solution["format_version"],
                "visual_studio_version": parsed_solution["visual_studio_version"],
                "minimum_vs_version": parsed_solution["minimum_vs_version"],
                "project_count": project_count,
                "resolved_project_count": resolved_count,
                "missing_project_count": missing_count,
                "solution_folder_count": folder_count,
                "shared_project_count": shared_count,
                "parse_status": parsed_solution["parse_status"],
                "parse_error": parsed_solution["parse_error"],
                "projects": sorted(
                    (
                        {
                            "raw_path": m["raw_path"],
                            "relative_path": m["resolved_relative_path"],
                            "project_guid": m["project_guid"],
                            "project_type_guid": m["project_type_guid"],
                            "solution_folder": m["solution_folder"],
                            "resolution_status": m["resolution_status"],
                        }
                        for m in member_entries
                    ),
                    key=lambda m: m["raw_path"],
                ),
            }
        )

    # ---- Projects: resolve <ProjectReference>s, normalise frameworks ----
    db_projects = []
    db_project_references = []
    db_project_packages = []
    artifact_projects = []
    artifact_project_references = []

    for project_id, parsed in projects_by_id.items():
        project_path = repo_root / parsed["relative_path"]
        containing_dir = project_path.parent

        reference_rows = []
        for ref in parsed["project_references"]:
            resolved_rel, escapes = _resolve_raw_path(ref["raw_path"], containing_dir, repo_root)
            if escapes:
                resolution_status, referenced_project_id = "external_repository", None
            elif resolved_rel and resolved_rel.lower() in projects_index:
                resolution_status = "resolved"
                referenced_project_id = projects_index[resolved_rel.lower()]
            else:
                resolution_status, referenced_project_id = "unresolved", None
            reference_rows.append(
                {
                    "id": _new_id(),
                    "source_project_id": project_id,
                    "referenced_project_id": referenced_project_id,
                    "raw_path": ref["raw_path"],
                    "resolution_status": resolution_status,
                }
            )

        framework_family = framework_version = None
        is_multi_targeting = parsed["is_multi_targeting"]
        framework_warning = None
        if parsed["target_frameworks_raw"]:
            framework_family, framework_version, is_multi_targeting, framework_warning = framework.resolve(
                parsed["target_frameworks_raw"]
            )

        parse_warnings = list(parsed["parse_warnings"])
        if framework_warning:
            parse_warnings.append(framework_warning)

        solution_membership = membership_count.get(project_id, 0)
        packages = [{**pkg, "id": _new_id(), "project_id": project_id} for pkg in parsed["packages"]]

        common = {
            "name": parsed["name"],
            "relative_path": parsed["relative_path"],
            "extension": parsed["extension"],
            "structural_type": parsed["structural_type"],
            "project_format": parsed["project_format"],
            "language": parsed["language"],
            "assembly_name": parsed["assembly_name"],
            "root_namespace": parsed["root_namespace"],
            "output_type": parsed["output_type"],
            # 2.1.0: where output_type came from (project, a props file,
            # sdk_default), and the declared SDK ("none" for legacy MSBuild).
            "output_type_source": parsed["output_type_source"],
            "project_sdk": parsed["project_sdk"],
            "target_framework_raw": parsed["target_framework_raw"],
            "target_frameworks_raw": parsed["target_frameworks_raw"],
            # 2.1.0: "project", or the Directory.*.props file the framework came from.
            "target_framework_source": parsed["target_framework_source"],
            "framework_family": framework_family,
            "framework_version": framework_version,
            "is_multi_targeting": is_multi_targeting,
            "solution_membership_count": solution_membership,
            "is_standalone": solution_membership == 0,
            "project_reference_count": len(parsed["project_references"]),
            "package_reference_count": len(packages),
            "package_management_style": parsed["package_management_style"],
            "has_packages_config": parsed["has_packages_config"],
            "parse_status": parsed["parse_status"],
            "parse_warnings": parse_warnings,
        }
        db_projects.append({"id": project_id, **common})
        db_project_packages.extend(packages)

        for row in reference_rows:
            source_solutions = solutions_of.get(row["source_project_id"], set())
            target_solutions = (
                solutions_of.get(row["referenced_project_id"], set()) if row["referenced_project_id"] else set()
            )
            row["is_cross_solution"] = bool(row["referenced_project_id"]) and not (source_solutions & target_solutions)
        db_project_references.extend(reference_rows)

        artifact_projects.append(
            {
                **common,
                "packages": sorted(
                    (
                        {
                            "package_name": pkg["package_name"],
                            "version_raw": pkg["version_raw"],
                            "declaration_source": pkg["declaration_source"],
                            "target_framework_raw": pkg["target_framework_raw"],
                            "is_malformed": pkg["is_malformed"],
                        }
                        for pkg in packages
                    ),
                    key=lambda pkg: (pkg["declaration_source"], pkg["package_name"] or ""),
                ),
            }
        )

        for row in reference_rows:
            referenced_relpath = (
                projects_by_id[row["referenced_project_id"]]["relative_path"] if row["referenced_project_id"] else None
            )
            artifact_project_references.append(
                {
                    "source_relative_path": parsed["relative_path"],
                    "referenced_relative_path": referenced_relpath,
                    "raw_path": row["raw_path"],
                    "resolution_status": row["resolution_status"],
                    "is_cross_solution": row["is_cross_solution"],
                }
            )

    artifact_solutions.sort(key=lambda s: s["relative_path"])
    artifact_projects.sort(key=lambda p: p["relative_path"])
    artifact_project_references.sort(key=lambda r: (r["source_relative_path"], r["raw_path"]))

    # ---- Supporting artifacts ----
    progress.phase("artifacts")
    repository_artifacts = artifact_scanner.scan(repo_root)
    db_repository_artifacts = [{**a, "id": _new_id()} for a in repository_artifacts]
    artifact_repository_artifacts = sorted(repository_artifacts, key=lambda a: a["relative_path"])

    # ---- Repo-wide rollups ----
    solution_count = len(db_solutions)
    project_file_count = len(db_projects)
    out_of_scope_count = sum(1 for p in db_projects if p["structural_type"] in OUT_OF_SCOPE_STRUCTURAL_TYPES)
    unknown_count = sum(1 for p in db_projects if p["structural_type"] == "unknown_project")
    legacy_count = sum(1 for p in db_projects if p["project_format"] == "legacy_msbuild")
    sdk_count = sum(1 for p in db_projects if p["project_format"] == "sdk_style")
    standalone_count = sum(1 for p in db_projects if p["is_standalone"])
    referenced_count = project_file_count - standalone_count
    shared_count_repo = sum(1 for count in membership_count.values() if count > 1)
    unresolved_count = sum(1 for m in db_solution_projects if m["resolution_status"] == "unresolved") + sum(
        1 for r in db_project_references if r["resolution_status"] == "unresolved"
    )

    framework_families: dict[str, int] = {}
    for p in db_projects:
        if p["framework_family"]:
            framework_families[p["framework_family"]] = framework_families.get(p["framework_family"], 0) + 1

    artifact_counts: dict[str, int] = {}
    for a in repository_artifacts:
        artifact_counts[a["category"]] = artifact_counts.get(a["category"], 0) + 1

    parse_warnings_repo = []
    for s in db_solutions:
        if s["parse_error"]:
            parse_warnings_repo.append({"path": s["relative_path"], "warning": f"parse failed: {s['parse_error']}"})
    for p in db_projects:
        for warning in p["parse_warnings"]:
            parse_warnings_repo.append({"path": p["relative_path"], "warning": warning})
    parse_warnings_repo.sort(key=lambda w: (w["path"], w["warning"]))

    # Only a genuine parse failure counts as "failed" now — a recognised
    # non-.NET type (parse_status: success) and an unrecognised extension
    # (parse_status: out_of_scope) are both expected, benign classification
    # outcomes, never scan problems (Part D/H).
    failed_solutions = [s for s in db_solutions if s["parse_status"] == "failed"]
    failed_projects = [p for p in db_projects if p["parse_status"] == "failed"]
    failed_parse_count = len(failed_solutions) + len(failed_projects)

    # The "every project file failed to parse" gate only ever looks at
    # projects we actually attempt to parse — out-of-scope and unknown types
    # were never going to succeed or fail, so they don't participate.
    recognized_projects = [
        p for p in db_projects
        if p["structural_type"] not in OUT_OF_SCOPE_STRUCTURAL_TYPES and p["structural_type"] != "unknown_project"
    ]
    failed_recognized_projects = [p for p in recognized_projects if p["parse_status"] == "failed"]

    diagnostics = [
        {
            "level": "error",
            "code": "SOLUTION_PARSE_FAILED",
            "message": f"parse failed: {s['parse_error']}" if s["parse_error"] else "parse failed",
            "ref": s["relative_path"],
        }
        for s in failed_solutions
    ] + [
        {
            "level": "error",
            "code": "PROJECT_PARSE_FAILED",
            "message": "; ".join(p["parse_warnings"]) or "parse failed",
            "ref": p["relative_path"],
        }
        for p in failed_projects
    ] + [
        {
            "level": "info",
            "code": "PROJECT_OUT_OF_SCOPE",
            "message": "; ".join(p["parse_warnings"]) or "recorded but not analysed (not a .NET project)",
            "ref": p["relative_path"],
        }
        for p in db_projects
        if p["structural_type"] in OUT_OF_SCOPE_STRUCTURAL_TYPES
    ] + [
        {
            "level": "info",
            "code": "PROJECT_UNKNOWN_TYPE",
            "message": "; ".join(p["parse_warnings"]) or "unrecognised project extension, recorded but not analysed",
            "ref": p["relative_path"],
        }
        for p in db_projects
        if p["structural_type"] == "unknown_project"
    ]

    slug = inventory.get("slug", "repository")
    if solution_count == 0 and project_file_count == 0:
        scan_status, exit_status = "complete", "COMPLETED"
        exit_message = f"Repository '{slug}' contains no .NET solution or project files."
        diagnostics = []
    elif recognized_projects and len(failed_recognized_projects) == len(recognized_projects):
        scan_status, exit_status = "failed", "FAILED"
        exit_message = "Every project file failed to parse."
    elif failed_parse_count > 0:
        scan_status, exit_status = "partial", "COMPLETED"
        exit_message = (
            f"Discovered {solution_count} solution(s), {project_file_count} project file(s); "
            f"{failed_parse_count} failed to parse."
        )
    else:
        scan_status, exit_status = "complete", "COMPLETED"
        exit_message = f"Discovered {solution_count} solution(s) and {project_file_count} project file(s)."

    structure = {
        "scan_status": scan_status,
        "solution_count": solution_count,
        "project_file_count": project_file_count,
        "projects_referenced_count": referenced_count,
        "standalone_project_count": standalone_count,
        "shared_project_count": shared_count_repo,
        "unresolved_reference_count": unresolved_count,
        "out_of_scope_project_count": out_of_scope_count,
        "unknown_project_count": unknown_count,
        "failed_parse_count": failed_parse_count,
        "legacy_project_count": legacy_count,
        "sdk_project_count": sdk_count,
        "framework_families": framework_families,
        "artifact_counts": artifact_counts,
        "parse_warnings": parse_warnings_repo,
    }
    summary = {key: structure[key] for key in _SUMMARY_FIELDS}

    metrics = {
        "read_count": project_file_count,
        "write_count": project_file_count,
        "skip_count": failed_parse_count,
        "commit_count": 1,
    }

    return {
        "structure": structure,
        "summary": summary,
        "exit_status": exit_status,
        "exit_message": exit_message,
        "metrics": metrics,
        "diagnostics": diagnostics,
        "db_solutions": db_solutions,
        "db_projects": db_projects,
        "db_solution_projects": db_solution_projects,
        "db_project_references": db_project_references,
        "db_project_packages": db_project_packages,
        "db_repository_artifacts": db_repository_artifacts,
        "artifact_solutions": artifact_solutions,
        "artifact_projects": artifact_projects,
        "artifact_project_references": artifact_project_references,
        "artifact_repository_artifacts": artifact_repository_artifacts,
    }


def run(context: dict) -> dict:
    parameters = context.get("parameters") or {}
    repository_id = parameters.get("repository_id")
    if not repository_id:
        return _failed("parameters.repository_id is required for solution-discovery")

    inputs = context.get("inputs") or {}
    artifact_ref = inputs.get("repository-inventory")
    if artifact_ref is None:
        # The engine resolves `inputs` before invoking a step per its
        # `consumes` declaration; this only fires if the script is invoked
        # standalone without the expected envelope, or the job's flow entry
        # is missing an `inputs:` mapping — see Part H: "Input artifact
        # unresolvable — FAILED — the engine should catch this before invoke".
        return _failed("input 'repository-inventory' was not resolved")

    try:
        inventory_path = _local_path_from_uri(artifact_ref["uri"])
        inventory = json.loads(inventory_path.read_text(encoding="utf-8-sig"))
    except (KeyError, OSError, ValueError) as exc:
        return _failed(f"could not read repository-inventory artifact: {exc}")

    repo_root = Path(inventory["local_path"])
    if not repo_root.is_dir():
        return _failed(f"repository folder '{repo_root}' does not exist or is not a directory")
    repo_root = repo_root.resolve()

    now = _now_iso()
    progress = Progress(context.get("output_dir"))
    try:
        return _run_scan(context, inventory, repository_id, repo_root, now, progress)
    finally:
        progress.finish("ended")


def _run_scan(context: dict, inventory: dict, repository_id, repo_root: Path, now: str, progress: Progress) -> dict:
    outcome = _scan(repo_root, inventory, str(repository_id), progress)

    database_url = context.get("database_url")
    if database_url:
        progress.phase("database")
        persistence.replace_all(
            database_url,
            repository_id,
            structure={**outcome["structure"], "step_execution_id": context.get("step_execution_id"), "scanned_at": now},
            solutions=outcome["db_solutions"],
            projects=outcome["db_projects"],
            solution_projects=outcome["db_solution_projects"],
            project_references=outcome["db_project_references"],
            project_packages=outcome["db_project_packages"],
            repository_artifacts=outcome["db_repository_artifacts"],
        )

    result = {
        "envelope_version": "1.0",
        "exit_status": outcome["exit_status"],
        "exit_message": outcome["exit_message"],
        "metrics": outcome["metrics"],
        "diagnostics": outcome["diagnostics"],
    }

    if outcome["exit_status"] == "FAILED":
        return result

    progress.phase("write")
    output_dir = Path(context["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "solution-project-inventory.json"

    artifact = {
        "artifact_type": ARTIFACT_TYPE,
        "artifact_version": ARTIFACT_VERSION,
        "repository_id": str(repository_id),
        "repository_slug": inventory.get("slug"),
        "scan_status": outcome["structure"]["scan_status"],
        "summary": outcome["summary"],
        "solutions": outcome["artifact_solutions"],
        "projects": outcome["artifact_projects"],
        "project_references": outcome["artifact_project_references"],
        "repository_artifacts": outcome["artifact_repository_artifacts"],
        "parse_warnings": outcome["structure"]["parse_warnings"],
    }
    # generated_at deliberately excluded from the file — see step 1's
    # repository-inventory.json for the same rationale — so unchanged input
    # yields an identical checksum. Carried in the output's metadata instead.
    output_path.write_text(
        json.dumps(artifact, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    checksum = _sha256_uri(output_path.as_uri())

    result["outputs"] = [
        {
            "artifact_type": ARTIFACT_TYPE,
            "artifact_version": ARTIFACT_VERSION,
            "uri": output_path.as_uri(),
            "checksum": checksum,
            "metadata": {"generated_at": now},
        }
    ]
    return result


if __name__ == "__main__":
    # lstrip a BOM: PowerShell's `Get-Content | python main.py` (the README's
    # documented standalone invocation) can inject one depending on console
    # encoding, even when the source file itself has none.
    _raw_context = json.loads(sys.stdin.read().lstrip("﻿"))
    try:
        _result = run(_raw_context)
    except Exception as exc:  # a "process"-style invocation must still emit valid JSON
        _result = {"envelope_version": "1.0", "exit_status": "FAILED", "exit_message": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(_result))
