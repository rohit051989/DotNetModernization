"""Every generated file stands on its own (36-COPILOT-ENHANCED-CONVERSION Part K).

The conversion engine reads one repository's branch and nothing else. A reference to a platform document, a path
on the platform's machine, a lifecycle step or the catalog's own vocabulary points at nothing it can read, and an
author's note is noise it may try to act on. So the generator runs this check before writing anything, and a
finding stops it. Each finding names the file, the line, the check and the text matched.

| Check | Fails on |
|---|---|
| platform document | `docs/...`, a spec file name (`21-APPLICATION-FINGERPRINTING.md`), a `Part X` citation |
| platform path | a path into the platform repository (`backend/`, `steps/`, `catalog/`, `third_party/` ...), a platform module (`app.engine`), `RUNS_DIR` |
| absolute local path | a Windows drive or UNC path, or a home or temp directory, unless the repository's own files contain it: a path the code itself holds is the finding the instruction is about |
| lifecycle step | a lifecycle step's name (`item-detection`), "lifecycle step", "step 6" |
| platform vocabulary | catalog, work item, resolution, occurrence, signal, discovery, engagement, presumptive, matrix entry, input generator, Modernization Platform; a catalog item or resolution id; a signal name |

Allowed: a skill's name (`applying-<id>`, a file in the branch), the `discovery: preload|lazy` key that Copilot's
skill format requires, the attribution paragraph crediting the plugin a template was adapted from ("Adapted from
`agents/...`" to the end of its paragraph), and a vocabulary word inside a backtick code span the repository's own
files hold: eShopOnWeb's `src/Catalog/...` is its code, not the platform's word.
"""
import re
import subprocess
from pathlib import Path

DOCUMENT = (
    re.compile(r"(?<![\w.-])docs/[\w./-]*"),
    re.compile(r"\b\d{2}-[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b|\b\d{2}-[A-Z][A-Z0-9-]*\.md\b"),
    re.compile(r"\bPart [A-Z]\d{0,2}\b"),
)
PLATFORM_PATH = (
    re.compile(r"(?<![\w.-])(?:backend|frontend|steps|catalog|third_party|schemas|probes)/[\w./-]*"),
    re.compile(r"\bapp\.(?:engine|items|experiment|seed|estate|conversion|routers|impact|repositories)\b"),
    re.compile(r"\bRUNS_DIR\b"),
)
TERMINATORS = r"\s`'\"|)<>,;*"
ABSOLUTE_PATH = (
    re.compile(rf"(?<![\w/\\])[A-Za-z]:[\\/][^{TERMINATORS}]*"),
    re.compile(rf"(?<![\w\\])\\\\[A-Za-z0-9._$-]+\\[^{TERMINATORS}]*"),
    re.compile(rf"(?<![\w.:/-])/(?:home|Users|root|tmp)/[^{TERMINATORS}]*"),
    re.compile(rf"(?<![\w.:/-])/[a-zA-Z]/(?:Users|Iris|[A-Z][\w-]*)/[^{TERMINATORS}]*"),
)
STEP_WORDS = re.compile(r"(?i)\blifecycle steps?\b|\bstep \d+\b")
VOCABULARY = re.compile(
    r"(?i)\bcatalog(?:ue)?s?\b|\bwork items?\b|\bresolutions?\b|\boccurrences?\b|\bsignals?\b|\bdiscovery\b"
    r"|\bengagements?\b|\bpresumptive\b|\bmatrix entr(?:y|ies)\b|\binput generator\b|\bModernization Platform\b")

SKILL_NAME = re.compile(r"applying-[a-z0-9-]+")
CODE_SPAN = re.compile(r"`([^`]+)`")
SKILL_DISCOVERY_KEY = re.compile(r"^\s*discovery: (?:preload|lazy)\s*$")
ATTRIBUTION_START = re.compile(r"^Adapted from `agents/")


def _token(word: str) -> re.Pattern:
    return re.compile(rf"(?<![\w-]){re.escape(word)}(?![\w-])")


def _checked_lines(text: str):
    """(line number, line) for the lines a check applies to: the plugin attribution paragraph is skipped, and a
    skill name is blanked out of a line before it is checked."""
    attribution = False
    for number, line in enumerate(text.split("\n"), 1):
        if ATTRIBUTION_START.match(line):
            attribution = True
        if attribution:
            if not line.strip():
                attribution = False
            continue
        if SKILL_DISCOVERY_KEY.match(line):
            continue
        yield number, SKILL_NAME.sub("applying-", line)


class _Repository:
    """The repository's own files: their names, and their text, searched for what the code itself holds."""

    MAX_FILE = 2_000_000

    def __init__(self, root: Path | None):
        self.root = root
        self._texts: list[str] | None = None
        self._names: list[str] = []

    def _corpus(self) -> list[str]:
        # The tracked files, read once. Not `git grep -F`: it mishandles backslashes in a fixed string on Windows.
        if self._texts is None:
            self._texts = []
            listed = subprocess.run(["git", "-C", str(self.root), "ls-files", "-z"], capture_output=True)
            if listed.returncode == 0:
                self._names = [n for n in listed.stdout.decode("utf-8", errors="replace").split("\0") if n]
            else:                                           # not a git checkout: every file in the folder
                self._names = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())
            for name in self._names:
                f = self.root / name
                if f.is_file() and f.stat().st_size <= self.MAX_FILE:
                    self._texts.append(f.read_bytes().decode("utf-8", errors="replace"))
        return self._texts

    def holds(self, text: str) -> bool:
        """Text the repository holds: a tracked file's path (or part of one), or text in a tracked file, verbatim or
        with backslashes escaped (JSON, C# strings)."""
        if self.root is None or not text:
            return False
        texts = self._corpus()
        forms = {text, text.replace("\\", "\\\\")}
        return any(form in name for name in self._names for form in forms) or any(form in t for t in texts for form in forms)


def check(files: dict[str, str], vocabulary: dict | None = None, repository_root: Path | None = None) -> list[dict]:
    """Findings {file, line, check, match} across every generated file; empty when all are self-contained."""
    vocabulary = vocabulary or {}
    ids = [_token(i) for i in sorted(set(vocabulary.get("item_ids", [])) | set(vocabulary.get("resolution_ids", []))) if "-" in i]
    signals = [_token(s) for s in vocabulary.get("signals", []) if "_" in s]
    steps = [_token(s) for s in vocabulary.get("steps", []) if "-" in s]
    repository = _Repository(repository_root)
    findings = []

    def found(path: str, number: int, kind: str, match: str) -> None:
        findings.append({"file": path, "line": number, "check": kind, "match": match.strip()[:120]})

    for path, text in sorted(files.items()):
        for number, line in _checked_lines(text):
            for pattern in DOCUMENT:
                for m in pattern.finditer(line):
                    found(path, number, "platform document", m.group(0))
            for pattern in PLATFORM_PATH:
                for m in pattern.finditer(line):
                    found(path, number, "platform path", m.group(0))
            for pattern in ABSOLUTE_PATH:
                for m in pattern.finditer(line):
                    if not repository.holds(m.group(0)):
                        found(path, number, "absolute local path", m.group(0))
            for m in STEP_WORDS.finditer(line):
                found(path, number, "lifecycle step", m.group(0))
            for pattern in steps:
                for m in pattern.finditer(line):
                    found(path, number, "lifecycle step", m.group(0))
            spans = [(s.start(1), s.end(1), s.group(1)) for s in CODE_SPAN.finditer(line)]
            for m in VOCABULARY.finditer(line):
                quoted = next((text_ for start, end, text_ in spans if start <= m.start() and m.end() <= end), None)
                if quoted is not None and repository.holds(quoted.split(":")[0] if "/" in quoted else quoted):
                    continue
                found(path, number, "platform vocabulary", m.group(0))
            for pattern in ids + signals:
                for m in pattern.finditer(line):
                    found(path, number, "platform vocabulary", m.group(0))
    return findings
