"""The shared walk skips build output, tooling and restored package folders, by folder name, case-insensitively, as
the C# steps' walk does (FileSystemWalk): a restored Packages\\ folder on Windows holds a package's own project files,
never the repository's."""
import tempfile
import unittest
from pathlib import Path

from discovery.paths import walk_files


class WalkFiles(unittest.TestCase):
    def test_skips_restored_package_folders_whatever_their_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Only "Packages" (a Windows folder is one name whatever its case): the old exact-case match walked it.
            for rel in ("src/App/App.csproj", "Packages/Other.Lib.2.0.0/content/Other.csproj", "src/App/BIN/Debug/App.csproj",
                        "src/App/obj/App.csproj.nuget.g.props"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text("<Project />\n", encoding="utf-8")
            found = sorted(p.relative_to(root).as_posix() for p in walk_files(root))
        self.assertEqual(found, ["src/App/App.csproj"])


if __name__ == "__main__":
    unittest.main()
