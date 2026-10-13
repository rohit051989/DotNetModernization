"""The vendored code-modernization plugin (36-COPILOT-ENHANCED-CONVERSION Parts C and I).

- The licence, the notice and a modification header on every modified file are present.
- Telemetry is not vendored.
- No vendored file makes a network call: no vendored module imports a network, process or
  dynamic-import facility, and the vendored test suite passes in place with sockets disabled.

Run: python -m unittest tests.test_vendored_plugin
"""
import ast
import subprocess
import sys
import unittest
from pathlib import Path

from app.config import settings

VENDORED = Path(settings.platform_root) / "third_party" / "code-modernization"
SCRIPTS = VENDORED / "scripts"
NETWORK_OR_PROCESS = {"socket", "ssl", "http", "urllib", "urllib2", "urllib3", "requests", "httpx", "ftplib", "smtplib",
                      "poplib", "imaplib", "telnetlib", "xmlrpc", "asyncio", "subprocess", "multiprocessing",
                      "webbrowser", "importlib", "ctypes", "telemetry"}
CALLS = {"system", "popen", "spawnl", "spawnv", "execv", "execl", "startfile", "__import__", "urlopen", "eval", "exec"}


def _imports(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def _calls(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
            if name:
                found.add(name)
    return found


class Obligations(unittest.TestCase):
    def test_licence_and_notice_are_present(self):
        self.assertIn("Apache License", (VENDORED / "LICENSE").read_text(encoding="utf-8"))
        notice = (VENDORED / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("anthropics/claude-plugins-official", notice)
        self.assertIn("f359d43b406057f1a8cdbc4ea93b827642c162e6", notice)
        self.assertIn("2026-10-10", notice)

    def test_every_modified_file_says_so_in_its_header(self):
        notice = (VENDORED / "NOTICE").read_text(encoding="utf-8")
        for path in sorted(VENDORED.rglob("*.py")):
            rel = path.relative_to(VENDORED).as_posix()
            self.assertIn(rel, notice, f"{rel} is not listed in NOTICE")
            line = next(ln for ln in notice.splitlines() if ln.startswith(rel))
            head = path.read_text(encoding="utf-8")[:400]
            if "MODIFIED" in line:
                self.assertTrue(head.startswith("# MODIFIED by the Modernization Platform"), rel)
            else:
                self.assertNotIn("MODIFIED", head, rel)

    def test_telemetry_is_not_vendored(self):
        self.assertEqual([p.name for p in VENDORED.rglob("telemetry*")], [])


class NoNetwork(unittest.TestCase):
    def test_no_vendored_module_imports_a_network_or_process_facility(self):
        for path in sorted(SCRIPTS.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            self.assertEqual(_imports(tree) & NETWORK_OR_PROCESS, set(), path.name)
            self.assertEqual(_calls(tree) & CALLS, set(), path.name)

    def test_vendored_tests_pass_in_place_with_sockets_disabled(self):
        # Its own process, so nothing patched here reaches the platform's tests. Every way out — connect,
        # name resolution — raises; the vendored suite must still pass and nothing may have tried.
        bootstrap = "\n".join([
            'import io, socket, sys, unittest',
            'tried = []',
            'def refuse(*a, **k):',
            '    tried.append(1)',
            "    raise OSError('network disabled: a vendored file tried to connect')",
            'socket.socket.connect = socket.socket.connect_ex = refuse',
            'socket.create_connection = socket.getaddrinfo = socket.gethostbyname = refuse',
            "suite = unittest.defaultTestLoader.discover('.', top_level_dir='.')",
            'result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)',
            'print(result.testsRun, len(result.failures) + len(result.errors), len(tried))',
            'sys.exit(0 if result.wasSuccessful() and not tried else 1)',
        ])
        done = subprocess.run([sys.executable, "-I", "-c", bootstrap], cwd=SCRIPTS / "tests",
                              capture_output=True, text=True, timeout=900)
        ran, broken, tried = (int(x) for x in done.stdout.split()[-3:])
        self.assertEqual((broken, tried), (0, 0), done.stdout + done.stderr[-2000:])
        self.assertGreater(ran, 150)
        self.assertEqual(done.returncode, 0)


if __name__ == "__main__":
    unittest.main()
