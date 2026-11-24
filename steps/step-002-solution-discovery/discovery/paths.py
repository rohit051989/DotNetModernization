"""Shared filesystem walk helpers.

Same exclusions as lifecycle step 1's size walk (backend/app/steps/repository_ingest.py)
— duplicated here rather than imported, since this package must not import
from backend.app (see 19-SOLUTION-DISCOVERY.md Part B).
"""

import os
from pathlib import Path

SKIP_DIR_NAMES = {".git", "node_modules", "bin", "obj", "packages"}


def walk_files(root: Path):
    """Yields every file under `root`, pruning SKIP_DIR_NAMES from traversal
    entirely (not just excluding them from the results). Folder names compare
    case-insensitively, as the C# steps' walk does (FileSystemWalk): a restored
    `Packages\\` folder on Windows is skipped like `packages\\`."""
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIR_NAMES]
        for filename in files:
            yield Path(current_root) / filename
