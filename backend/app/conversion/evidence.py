"""Evidence: files, each recorded with its sha256 — 34-CONVERSION-ARCHITECTURE.md
C4. A result record says what was checked and points at the file that shows
it; a figure without a file behind it is a claim, not evidence."""

import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(kind: str, path: Path, root: Path, **result) -> dict:
    """{kind, path (relative to the plan directory), sha256, ...result}."""
    return {"kind": kind, "path": path.relative_to(root).as_posix(), "sha256": sha256(path), **result}


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="")
    return path


def verify(entry: dict, root: Path) -> bool:
    """The file a record points at still has the recorded hash."""
    path = root / entry["path"]
    return path.exists() and sha256(path) == entry["sha256"]
