"""Every generated file stands on its own (36-COPILOT-ENHANCED-CONVERSION Part K).

The conversion engine reads one repository's branch and nothing else. A reference to a platform document, a path
on the platform's machine, a lifecycle step or one of the platform's own identifiers points at nothing it can read,
and an author's note is noise it may try to act on. So the generator runs this check before writing anything, and a
finding stops it. Each finding names the file, the line, the check and the text matched.

Only terms specific to the platform are checked. An ordinary word on its own (catalog, resolution, signal, discovery,
step) is never refused: it is also the client's word, in its project names and its prose.

| Check | Fails on |
|---|---|
| platform document | `docs/...`, a spec file name (`21-APPLICATION-FINGERPRINTING.md`), a `Part X` citation |
| platform path | a path into the platform repository (`backend/`, `steps/`, `catalog/`, `third_party/` ...), a platform module (`app.engine`), `RUNS_DIR` |
| absolute local path | a Windows drive or UNC path, or a home or temp directory, unless the repository's own files contain it: a path the code itself holds is the finding the instruction is about |
| lifecycle step | a lifecycle step's slug (`item-detection`) |
| platform vocabulary | a catalog item or resolution id, a signal name, an internal field name (`detection_state`), the platform's own name |

Every name that comes from the repository itself is allowed wherever it appears: a file or folder name, a file's name
without its extension (a project's, `Catalog.Host`), a path the repository has, a namespace its code declares. A
client's `frontend/` or `docs/` folder, or a project named after a step, is its own.

Commit messages (Part M): every commit the platform makes in a client repository passes the same check, through
`check_commit_message` (app.conversion.gitops.platform_commit), and may carry no co-author trailer: no commit the
platform makes names an AI as a co-author.

Also allowed: a skill's name (`applying-<id>`, a file in the branch), the `discovery: preload|lazy` key that Copilot's
skill format requires, and the attribution paragraph crediting the plugin a template was adapted from ("Adapted from
`agents/...`" to the end of its paragraph).
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
# The platform's own names: its internal field and table names, and its product name. Never an ordinary word.
PLATFORM_TERMS = re.compile(
    r"\b(?:item_id|resolution_id|engagement_id|repository_id|detection_state|consumer_impact|engine_guidance"
    r"|is_recommended|seeded_hash|scope_status|ingest_commit_sha|item_occurrences|work_item_impacts|catalog_items"
    r"|item_resolutions|engagement_decisions|impact_summaries|engagement_patterns|decision_records)\b"
    r"|\bModernization Platform\b")

SKILL_NAME = re.compile(r"applying-[a-z0-9-]+")
NAMESPACE = re.compile(r"(?im)^\s*namespace\s+([A-Za-z_][\w.]*)")
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
        self._own: set[str] = set()

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
                parts = name.split("/")
                self._own.update(parts)
                self._own.add(parts[-1].rsplit(".", 1)[0])  # Catalog.Host.csproj: Catalog.Host
                f = self.root / name
                if f.is_file() and f.stat().st_size <= self.MAX_FILE:
                    text = f.read_bytes().decode("utf-8", errors="replace")
                    self._texts.append(text)
                    if name.lower().endswith((".cs", ".vb")):
                        for namespace in NAMESPACE.findall(text):
                            self._own.add(namespace)
                            self._own.update(namespace.split("."))
        return self._texts

    def names(self, text: str) -> bool:
        """A name that comes from the repository itself: a file or folder name, a file's name without its extension, a
        namespace its code declares, or a path it has (or the start of one)."""
        if self.root is None or not text:
            return False
        self._corpus()
        t = text.rstrip("/.:")
        if t in self._own:
            return True
        # A path: the whole of a tracked file's path, or a run of its folders, on folder boundaries.
        return "/" in t and any(f"/{t}/" in f"/{n}/" for n in self._names)

    def holds(self, text: str) -> bool:
        """Text the repository holds: a tracked file's path (or part of one), or text in a tracked file, verbatim or
        with backslashes escaped (JSON, C# strings)."""
        if self.root is None or not text:
            return False
        texts = self._corpus()
        forms = {text, text.replace("\\", "\\\\")}
        return any(form in name for name in self._names for form in forms) or any(form in t for t in texts for form in forms)


CO_AUTHOR_TRAILER = re.compile(r"(?im)^\s*co-authored-by\s*:.*$")


def vocabulary(db) -> dict:
    """The platform's own names, which no generated file or commit message may contain: catalog ids, signal names and
    lifecycle step names, read from where the platform keeps them."""
    from sqlalchemy import text

    return {
        "item_ids": sorted(x for (x,) in db.execute(text("SELECT id FROM catalog_items"))),
        "resolution_ids": sorted(x for (x,) in db.execute(text("SELECT id FROM item_resolutions"))),
        "signals": sorted(x for (x,) in db.execute(text("SELECT name FROM signal_registry_entries"))),
        "steps": sorted(x for (x,) in db.execute(text("SELECT step_name FROM wf_step_registrations"))),
    }


def check_commit_message(message: str, vocabulary_: dict | None = None) -> list[dict]:
    """Findings for a commit message the platform writes into a client repository: the self-containedness checks, and
    any co-author trailer."""
    findings = check({"commit message": message}, vocabulary_, None)
    for m in CO_AUTHOR_TRAILER.finditer(message):
        findings.append({"file": "commit message", "line": message[:m.start()].count("\n") + 1, "check": "co-author trailer",
                         "match": m.group(0).strip()[:120]})
    return findings


def check(files: dict[str, str], vocabulary: dict | None = None, repository_root: Path | None = None) -> list[dict]:
    """Findings {file, line, check, match} across every generated file; empty when all are self-contained."""
    vocabulary = vocabulary or {}
    ids = [_token(i) for i in sorted(set(vocabulary.get("item_ids", [])) | set(vocabulary.get("resolution_ids", []))) if "-" in i]
    signals = [_token(s) for s in vocabulary.get("signals", []) if "_" in s]
    steps = [_token(s) for s in vocabulary.get("steps", []) if "-" in s]
    repository = _Repository(repository_root)
    findings = []

    def found(path: str, number: int, kind: str, match: str) -> None:
        # A name from the repository itself is its own, wherever it appears.
        if not repository.names(match.strip()):
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
            for pattern in steps:
                for m in pattern.finditer(line):
                    found(path, number, "lifecycle step", m.group(0))
            for m in PLATFORM_TERMS.finditer(line):
                found(path, number, "platform vocabulary", m.group(0))
            for pattern in ids + signals:
                for m in pattern.finditer(line):
                    found(path, number, "platform vocabulary", m.group(0))
    return findings
