"""The deterministic approaches — 34-CONVERSION-ARCHITECTURE.md Part F,
`deterministic`: re-runnable unattended, no LLM. The retarget, the package
bump (one package, or a group that only resolves together), and the fix for
each framework delta that has a reliable rewrite.

An approach works on one unit's target in a worktree it is given:

- pre_check: whether the unit applies at the branch's current state —
  ("apply", ...), ("not_applicable", reason), ("stale", reason) when what it
  was planned against has changed, or ("refused", reason) when it cannot be
  applied safely;
- apply: the edit; returns what it changed, in words;
- allowed_paths: the only files it may change (B8). Anything else fails the unit;
- post_check: problems with the result, empty when it is right;
- message: the commit message.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.conversion import msbuild


@dataclass(frozen=True)
class PreCheck:
    outcome: str        # apply, not_applicable, stale, refused
    reason: str = ""


def _major(tfm: str) -> int:
    m = re.match(r"^net(?:coreapp)?(\d+)\.", tfm)
    if not m:
        raise ValueError(f"{tfm} is not a .NET (5+) framework")
    return int(m.group(1))


class RetargetTfm:
    """retarget-tfm 0.1.0: from one .NET framework to another, edited in every
    file that declares it (solution-discovery's target_framework_source), and
    the SDK pin in global.json raised to the target's SDK where it is older —
    an SDK can only build frameworks up to its own version."""

    id = "retarget-tfm"
    version = "0.1.0"

    def pre_check(self, root: Path, target: dict) -> PreCheck:
        declared = {d["file"]: msbuild.declared_frameworks(msbuild.read(root / d["file"])) for d in target["declarations"]}
        if all(target["from"] not in v and target["to"] in v for v in declared.values()):
            return PreCheck("not_applicable", f"already {target['to']} in {', '.join(declared)}")
        missing = [f for f, v in declared.items() if target["from"] not in v and target["to"] not in v]
        if missing:
            return PreCheck("stale", f"{', '.join(missing)} no longer declare(s) {target['from']}")
        return PreCheck("apply")

    def apply(self, root: Path, target: dict) -> list[str]:
        done = []
        for d in target["declarations"]:
            path = root / d["file"]
            original = path.read_bytes()
            text, count = msbuild.retarget(msbuild.read(path), target["from"], target["to"])
            msbuild.write(path, original, text)
            done.append(f"{d['file']}: {d['element']} {target['from']} -> {target['to']} ({count} value(s); "
                        f"{len(d['projects'])} project(s) inherit it)")
        pin = self._global_json(root)
        if pin is not None:
            path, original, version = pin
            new_version = f"{_major(target['to'])}.0.100"
            if self._sdk_major(version) < _major(target["to"]):
                text = re.sub(r'("version"\s*:\s*")[^"]*(")', lambda m: m.group(1) + new_version + m.group(2),
                              msbuild.read(path), count=1)
                msbuild.write(path, original, text)
                done.append(f"global.json: SDK {version} -> {new_version} (roll-forward kept)")
        return done

    def allowed_paths(self, target: dict) -> set[str]:
        return {d["file"] for d in target["declarations"]} | {"global.json"}

    def post_check(self, root: Path, target: dict) -> list[str]:
        problems = []
        for d in target["declarations"]:
            values = msbuild.declared_frameworks(msbuild.read(root / d["file"]))
            if target["from"] in values or target["to"] not in values:
                problems.append(f"{d['file']} declares {';'.join(values)}, expected {target['to']}")
        pin = self._global_json(root)
        if pin is not None and self._sdk_major(pin[2]) < _major(target["to"]):
            problems.append(f"global.json still pins SDK {pin[2]}, which cannot build {target['to']}")
        return problems

    def message(self, target: dict) -> str:
        files = ", ".join(d["file"] for d in target["declarations"])
        projects = sum(len(d["projects"]) for d in target["declarations"])
        return (f"Retarget {target['from']} -> {target['to']}\n\nDeclared in {files}, inherited by {projects} project(s).\n"
                "Made by a deterministic conversion, not an AI.")

    @staticmethod
    def _global_json(root: Path):
        path = root / "global.json"
        if not path.exists():
            return None
        original = path.read_bytes()
        version = (json.loads(msbuild.read(path)).get("sdk") or {}).get("version")
        return (path, original, version) if version else None

    @staticmethod
    def _sdk_major(version: str) -> int:
        return int(version.split(".")[0])


class PackageUpgradeSafe:
    """package-upgrade-safe 0.2.0: packages bumped to dependency-assessment's
    recommended versions, each edited where its version is declared.

    A unit's target is one occurrence (package_id, from, to, project,
    declaration), or — for packages that only resolve together — `bumps`, a
    list of those, applied at once in one commit (0.2.0). Under central
    package management a declaration is shared: the first occurrence's unit
    edits it, and the others find it done. A version property shared by other
    packages is bumped only when every package taking it is recommended the
    same version."""

    id = "package-upgrade-safe"
    version = "0.2.0"

    @staticmethod
    def bumps(target: dict) -> list[dict]:
        return target["bumps"] if "bumps" in target else [target]

    def _check(self, root: Path, bump: dict) -> PreCheck:
        try:
            declaration = msbuild.version_declaration(root, bump["project"], bump["package_id"])
        except LookupError as error:
            return PreCheck("stale", str(error))
        where = f"{declaration.file} ({declaration.kind} {declaration.name})"
        if declaration.value == bump["to"]:
            return PreCheck("not_applicable", f"already {bump['to']}, declared in {where}")
        if declaration.value != bump["from"]:
            return PreCheck("stale", f"{bump['package_id']} declared {declaration.value} in {where}, planned from {bump['from']}")
        disagree = {p: v for p, v in (bump.get("shared_recommendations") or {}).items() if v != bump["to"]}
        if declaration.kind == "property" and disagree:
            return PreCheck("refused", f"$({declaration.name}) is shared with packages recommended other versions: "
                                       + ", ".join(f"{p} {v}" for p, v in sorted(disagree.items())))
        return PreCheck("apply")

    def pre_check(self, root: Path, target: dict) -> PreCheck:
        checks = [self._check(root, b) for b in self.bumps(target)]
        for outcome in ("stale", "refused"):
            failing = [c.reason for c in checks if c.outcome == outcome]
            if failing:
                return PreCheck(outcome, "; ".join(failing))
        if all(c.outcome == "not_applicable" for c in checks):
            return PreCheck("not_applicable", "; ".join(c.reason for c in checks))
        return PreCheck("apply")

    def apply(self, root: Path, target: dict) -> list[str]:
        done = []
        for bump in self.bumps(target):
            if self._check(root, bump).outcome == "not_applicable":
                continue   # a shared declaration an earlier bump of this unit already moved
            declaration = msbuild.version_declaration(root, bump["project"], bump["package_id"])
            path = root / declaration.file
            original = path.read_bytes()
            text, changed = msbuild.set_version(msbuild.read(path), declaration, bump["to"])
            if not changed:
                raise RuntimeError(f"{declaration.key}: the declaration was found but not edited")
            msbuild.write(path, original, text)
            shared = f"; shared with {', '.join(declaration.shared_with)}" if declaration.shared_with else ""
            done.append(f"{declaration.file}: {declaration.kind} {declaration.name} {bump['from']} -> {bump['to']}{shared}")
        return done

    def allowed_paths(self, target: dict) -> set[str]:
        return {b["declaration"]["file"] for b in self.bumps(target)}

    def post_check(self, root: Path, target: dict) -> list[str]:
        problems = []
        for bump in self.bumps(target):
            declaration = msbuild.version_declaration(root, bump["project"], bump["package_id"])
            if declaration.value != bump["to"]:
                problems.append(f"{bump['package_id']} resolves to {declaration.value} for {bump['project']}, expected {bump['to']}")
        return problems

    def message(self, target: dict) -> str:
        bumps = self.bumps(target)
        if len(bumps) == 1:
            b = bumps[0]
            d = b["declaration"]
            shared = f"\nShared declaration: also {', '.join(d['shared_with'])}." if d.get("shared_with") else ""
            return (f"Bump {b['package_id']} {b['from']} -> {b['to']}\n\n"
                    f"Declared in {d['file']} ({d['kind']} {d['name']}); used by {b['project']}.{shared}\n"
                    "Made by a deterministic conversion, not an AI.")
        lines = "\n".join(f"- {b['package_id']} {b['from']} -> {b['to']} ({b['declaration']['file']}, "
                          f"{b['declaration']['kind']} {b['declaration']['name']})" for b in bumps)
        return (f"Bump {', '.join(b['package_id'] for b in bumps)} together\n\n"
                f"They only resolve together: {target.get('group_reason', '')}\n{lines}\n"
                "Made by a deterministic conversion, not an AI.")


class PinProgramInternal:
    """pin-program-internal 0.1.0, the fix for framework delta
    net10-public-top-level-program (framework_deltas.yaml): declares
    `internal partial class Program { }` beside a web project's top-level
    statements, so Program keeps on net10.0 the accessibility it has on
    every earlier framework. Builds on both; changes nothing on the current one."""

    id = "pin-program-internal"
    version = "0.1.0"

    _DECLARED = re.compile(r"^\s*(?:(public|internal)\s+)?(?:static\s+)?partial\s+class\s+Program\b", re.MULTILINE)

    def pre_check(self, root: Path, target: dict) -> PreCheck:
        path = root / target["file"]
        if not path.exists():
            return PreCheck("stale", f"{target['file']} no longer exists")
        found = self._DECLARED.findall(msbuild.read(path))
        if "internal" in found:
            return PreCheck("not_applicable", f"{target['file']} already declares internal partial class Program")
        if "public" in found:
            return PreCheck("refused", f"{target['file']} declares public partial class Program: its Program is public on purpose")
        if found:
            return PreCheck("refused", f"{target['file']} declares partial class Program without an accessibility; not rewritten")
        return PreCheck("apply")

    def apply(self, root: Path, target: dict) -> list[str]:
        path = root / target["file"]
        original = path.read_bytes()
        text = msbuild.read(path).rstrip("\n") + "\n\n" + (
            "// Kept internal, as on every framework before .NET 10, which makes a web project's implicit\n"
            "// Program public: a project referencing two of them would see Program twice (CS0433).\n"
            "internal partial class Program { }\n")
        msbuild.write(path, original, text)
        return [f"{target['file']}: internal partial class Program declared (framework delta {target['delta_id']})"]

    def allowed_paths(self, target: dict) -> set[str]:
        return {target["file"]}

    def post_check(self, root: Path, target: dict) -> list[str]:
        if "internal" not in self._DECLARED.findall(msbuild.read(root / target["file"])):
            return [f"{target['file']} does not declare internal partial class Program"]
        return []

    def message(self, target: dict) -> str:
        consumers = ", ".join(target.get("consumers", []))
        return (f"Keep Program internal in {target['file']}\n\n"
                f"Framework delta {target['delta_id']}: from {target['breaks_from']} the implicit Program of a web project\n"
                f"is public, and {consumers} would see two (CS0433). Builds on both frameworks.\n"
                "Made by a deterministic conversion, not an AI.")


# Assisted approaches (package-upgrade-adapt) have no implementation here: the
# deterministic runner never applies an assisted unit (Part F); they are T1b's.
APPROACHES = {a.id: a for a in (RetargetTfm(), PackageUpgradeSafe(), PinProgramInternal())}
