"""Items a deployment file on the branch carries (36-COPILOT-ENHANCED-CONVERSION Part N).

Discovery reads the code, so some items stay found after the conversion has dealt with them in a deployment file
instead. The verifier counts such an occurrence as resolved:

- `console-batch-job`: the console application is run by a CronJob. Some YAML file on the branch declares
  `kind: CronJob` and names the project: its project or assembly name, with dots, dashes or underscores, in any case
  (`Accounts.EncryptionUtility`, `accounts-encryptionutility`).
- `enterprise-vault-secret-reference`: the vault secret is delivered on the branch: by a Vault Agent annotation
  `vault.hashicorp.com/agent-inject-secret-<name>`, or by any vault delivery mechanism
  (app.engine.deployment_assets: an init container and its mapping, a CSI secrets store, an external-secrets sync)
  whose file names the secret the reference names (`vault:<name>`, read from the occurrence's line on the branch).

Each occurrence removed this way is listed as "carried by a deployment file", with the file, in the verification.
"""
import re
from pathlib import Path

YAML_SUFFIXES = (".yaml", ".yml")
SKIP_DIRS = {".git", "bin", "obj", "node_modules"}
CRONJOB = re.compile(r"^\s*kind:\s*[\"']?CronJob[\"']?\s*$", re.MULTILINE)
VAULT_VALUE = re.compile(r"[\"']vault:([^\"']+)[\"']")
INJECT_SECRET = re.compile(r"vault\.hashicorp\.com/agent-inject-secret-([A-Za-z0-9._-]+)")


def _files(root: Path, suffixes: tuple[str, ...] | None = None) -> dict[str, str]:
    out = {}
    for f in sorted(root.rglob("*")):
        rel = f.relative_to(root)
        if not f.is_file() or SKIP_DIRS & set(rel.parts[:-1]) or (suffixes and not f.name.lower().endswith(suffixes)):
            continue
        try:
            out[rel.as_posix()] = f.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
    return out


def _token(name: str) -> str:
    return re.sub(r"[._-]+", "-", name.lower())


def cronjobs(root: Path) -> dict[str, str]:
    """{file: text, normalised} for every YAML file on the branch declaring a CronJob."""
    return {rel: _token(text) for rel, text in _files(root, YAML_SUFFIXES).items() if CRONJOB.search(text)}


def injected_secrets(root: Path) -> dict[str, str]:
    """{secret name: file} for every Vault Agent inject-secret annotation on the branch."""
    found = {}
    for rel, text in _files(root, YAML_SUFFIXES + (".json",)).items():
        for name in INJECT_SECRET.findall(text):
            found.setdefault(name, rel)
    return found


def _vault_name(root: Path, occurrence: dict, line: dict | None) -> str | None:
    if not occurrence.get("file") or not line or not line.get("line"):
        return None
    path = root / occurrence["file"]
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None
    if not 0 < line["line"] <= len(lines):
        return None
    m = VAULT_VALUE.search(lines[line["line"] - 1])
    return m.group(1) if m else None


def carried(model: dict, root: Path) -> tuple[dict, list[dict]]:
    """(the model without the occurrences a deployment file on the branch carries, [{item, project, place, file}])."""
    from app.engine import deployment_assets

    jobs = cronjobs(root)
    secrets = injected_secrets(root)
    mechanisms = deployment_assets.vault_delivery(deployment_assets.read_tree(root))
    items, found = [], []
    for item in model["items"]:
        if item["id"] not in ("console-batch-job", "enterprise-vault-secret-reference"):
            items.append(item)
            continue
        left = []
        for occ in item["occurrences"]:
            if item["id"] == "console-batch-job":
                name = _token(Path(occ["project"]).stem)
                by = next((rel for rel, text in jobs.items() if re.search(rf"(^|[^a-z0-9]){re.escape(name)}($|[^a-z0-9])", text)), None)
                if by:
                    found.append({"item": item["id"], "project": occ["project"], "place": occ["project"], "file": by})
                    continue
                left.append(occ)
                continue
            lines_left = []
            for line in occ["lines"] or []:
                name = _vault_name(root, occ, line)
                by = secrets.get(name) if name else None
                by = by or next((m.file for m in mechanisms if name and m.delivers(name)), None)
                if by:
                    found.append({"item": item["id"], "project": occ["project"], "place": f"{occ['file']}:{line['line']}",
                                  "secret": name, "file": by})
                else:
                    lines_left.append(line)
            if lines_left or not occ["lines"]:
                left.append({**occ, "lines": lines_left})
        if left:
            items.append({**item, "occurrences": left})
    return {**model, "items": items}, found
