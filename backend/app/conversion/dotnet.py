"""Build and test, with results read from files, never from console text.

Build servers are disabled (no MSBuild node reuse, no shared compiler): a
server left running holds files in the scratch worktree open, and Windows
then refuses to delete it.

Tests write TRX; the counts and the failing tests' names come from the TRX
file, which is kept as evidence. Every build log starts with the SDK it ran
on (`sdk`).
"""

import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

NO_SERVERS = ["-nodeReuse:false", "-p:UseSharedCompilation=false", "--disable-build-servers"]
_TRX = "{http://microsoft.com/schemas/VisualStudio/TeamTest/2010}"


@dataclass
class Run:
    ok: bool
    exit_code: int
    log: str


def sdk(worktree: Path) -> str:
    """The SDK `dotnet` resolves to in `worktree` (its global.json applies), and the dotnet that was run — what
    this process actually builds with, DOTNET_ROOT included (app.config.apply_dotnet_root)."""
    done = subprocess.run(["dotnet", "--version"], cwd=worktree, capture_output=True, text=True)
    version = done.stdout.strip() if done.returncode == 0 else f"unknown ({(done.stdout + done.stderr).strip()[:200]})"
    return f"# .NET SDK {version}, {shutil.which('dotnet') or 'dotnet not on PATH'}"


def build(worktree: Path, solution: str, timeout: int = 1800) -> Run:
    args = ["dotnet", "build", solution, "-nologo", "-v", "minimal", *NO_SERVERS]
    header = sdk(worktree)
    done = subprocess.run(args, cwd=worktree, capture_output=True, text=True, timeout=timeout)
    return Run(done.returncode == 0, done.returncode, f"{header}\n$ {' '.join(args)}\n{done.stdout}{done.stderr}")


@dataclass
class TestResults:
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    passed_tests: list[str] = field(default_factory=list)
    failed_tests: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"total": self.total, "passed": self.passed, "failed": self.failed, "skipped": self.skipped,
                "failed_tests": self.failed_tests}


def read_trx(path: Path) -> TestResults:
    root = ET.parse(path).getroot()
    results = TestResults()
    for r in root.iter(f"{_TRX}UnitTestResult"):
        name, outcome = r.get("testName"), r.get("outcome")
        results.total += 1
        if outcome == "Passed":
            results.passed += 1
            results.passed_tests.append(name)
        elif outcome == "Failed":
            results.failed += 1
            results.failed_tests.append(name)
        else:
            results.skipped += 1
    results.passed_tests.sort()
    results.failed_tests.sort()
    return results


def test(worktree: Path, project: str, trx: Path, timeout: int = 1800, filter: str | None = None) -> tuple[Run, TestResults | None]:
    trx.parent.mkdir(parents=True, exist_ok=True)
    args = ["dotnet", "test", project, "--no-build", "-nologo", "--logger", f"trx;LogFileName={trx.name}",
            "--results-directory", str(trx.parent)] + (["--filter", filter] if filter else [])
    done = subprocess.run(args, cwd=worktree, capture_output=True, text=True, timeout=timeout)
    run = Run(done.returncode == 0, done.returncode, f"$ {' '.join(args)}\n{done.stdout}{done.stderr}")
    return run, read_trx(trx) if trx.exists() else None


def method_name(test_name: str) -> str:
    """A TRX test name without its data row: `Valid ("BranchCode","12")` -> `Valid`."""
    return test_name.split(" (", 1)[0].strip()


def rerun(worktree: Path, project: str, names: list[str], trx: Path) -> tuple[list[str], list[str]]:
    """Runs only the named tests of `project` once more (36-COPILOT-ENHANCED-CONVERSION Part N): (passed now,
    still failing). A test that failed and passes on this rerun is flaky: reported as such, never as a failure,
    never silently."""
    methods = sorted({method_name(n) for n in names})
    _, results = test(worktree, project, trx, filter="|".join(f"Name={m}" for m in methods))
    passed = set(results.passed_tests) if results else set()
    return sorted(n for n in names if n in passed), sorted(n for n in names if n not in passed)


def shutdown_build_servers() -> None:
    subprocess.run(["dotnet", "build-server", "shutdown"], capture_output=True, text=True)
