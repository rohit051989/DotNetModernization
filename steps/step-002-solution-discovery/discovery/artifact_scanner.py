"""Supporting-file discovery — presence only, no content interpretation.
See 19-STEP-002-SOLUTION-DISCOVERY.md Part C (`repository_artifacts`).

The step 2 requirements document (referenced but not present in this
checkout) is the authority on the exact category/pattern mapping; the table
below is a reasonable, documented convention covering the common .NET
estate file types, kept intentionally simple to extend.
"""

import fnmatch
from pathlib import Path

from .paths import walk_files

# (category, [fnmatch patterns]) — patterns containing '/' match against the
# full repo-relative path; others match against the bare file name.
_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("pipeline", [".github/workflows/*.yml", ".github/workflows/*.yaml"]),
    ("pipeline", ["azure-pipelines.yml", "azure-pipelines.yaml", ".gitlab-ci.yml", "Jenkinsfile", "bitbucket-pipelines.yml"]),
    ("container", ["Dockerfile", "Dockerfile.*", "docker-compose*.yml", "docker-compose*.yaml", ".dockerignore"]),
    ("deployment", ["*.pubxml", "*.wpp.targets"]),
    ("package", ["packages.config", "*.nuspec", "paket.dependencies", "paket.lock"]),
    ("build", ["*.sln", "Directory.Build.props", "Directory.Build.targets", "*.props", "*.targets", "nuget.config", "NuGet.Config", "global.json"]),
    ("script", ["*.ps1", "*.psm1", "*.sh", "*.cmd", "*.bat"]),
    ("configuration", ["*.config", "appsettings*.json"]),
    ("documentation", ["README*", "CHANGELOG*", "LICENSE*", "*.md"]),
]


def _category_for(relative_path: str, file_name: str) -> str | None:
    for category, patterns in _CATEGORY_PATTERNS:
        for pattern in patterns:
            target = relative_path if "/" in pattern else file_name
            if fnmatch.fnmatch(target, pattern):
                return category
    return None


def scan(repo_root: Path) -> list[dict]:
    """Every file matching a known category, skipping the same directories
    as everything else in phase 0. Each result: {category, relative_path,
    file_name}."""
    artifacts = []
    for path in walk_files(repo_root):
        relative_path = path.relative_to(repo_root).as_posix()
        category = _category_for(relative_path, path.name)
        if category is None:
            continue
        artifacts.append({"category": category, "relative_path": relative_path, "file_name": path.name})
    return artifacts
