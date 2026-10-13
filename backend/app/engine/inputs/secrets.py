"""No generated file contains a secret value (36-COPILOT-ENHANCED-CONVERSION Part D; the step 5 rules,
29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES C5).

Two independent checks, both run by the generator before anything is written:

1. **Shapes.** Nothing in a generated file looks like a secret: a connection string, a sensitive key with
   a value, a URL with credentials in it, or a token. The key list and connection-string test follow
   `Secrets.cs` (steps/step-003-fingerprinting/src/Fingerprinting.Analysis), which discovery itself uses.
2. **The repository's own values.** Every value the repository's configuration holds under a sensitive
   key, every connection string and its parts, and every Web Deploy SetParameters value is read from
   the repository and must not appear in any generated file. This is the proof against this repository
   rather than against a pattern: a leak of a value that looks innocent is still caught.

Values are read only to compare them and are never printed: a finding names the generated file, the
check and, for the second check, the configuration file and key, never the value.
"""
import json
import re
from pathlib import Path
from xml.etree import ElementTree

# Secrets.cs IsSensitiveKey (registry 1.11.0): the key's own name — the last segment of a "Section:Key" path — matches,
# and its last word does not merely describe a secret (ClientCredentialType, TokenEndpoint, SecretsDir are settings).
SENSITIVE_KEY = re.compile(r"(?i)password|pwd|secret|token|apikey|api_key|connectionstring|accountkey|sharedaccesskey|credential")
DESCRIPTIVE_LAST_WORDS = {
    "type", "kind", "mode", "name", "names", "path", "dir", "directory", "folder", "file", "url", "uri",
    "endpoint", "provider", "enabled", "required", "expiry", "expiration", "lifetime", "timeout", "seconds",
    "minutes", "length", "algorithm", "format", "header", "location", "store", "source", "policy", "scheme",
}
KEY_WORDS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def is_sensitive_key(key: str) -> bool:
    name = re.split(r"[:.]", key)[-1]
    if not SENSITIVE_KEY.search(name):
        return False
    words = KEY_WORDS.findall(name)
    return not words or words[-1].lower() not in DESCRIPTIVE_LAST_WORDS
# Secrets.cs LooksLikeConnectionString: two or more `keyword=value` pairs separated by semicolons.
CS_PAIR = re.compile(r"(?i)(?:^|;)\s*([a-z][a-z0-9 _.]{1,40})\s*=\s*([^;]*)")
CS_KEYWORDS = re.compile(r"(?i)^(server|data source|host|address|addr|network address|initial catalog|database|user id|uid|"
                         r"user|username|password|pwd|integrated security|trusted_connection|accountname|accountkey|"
                         r"sharedaccesskey|sharedaccesskeyname|endpoint|defaultendpointsprotocol|port|provider|ssl mode)$")
# The credential parts of a connection string, compared on their own as well as inside the whole string.
# A database or server name is not a secret value on its own, and short names would match ordinary text.
CS_CREDENTIAL_PARTS = {"password", "pwd", "user id", "uid", "user", "username", "accountkey", "sharedaccesskey"}

SHAPES = (
    ("connection string", re.compile(r"(?i)(?:\b(?:server|data source|host)\s*=[^;\n]{1,200};[^\n]{0,200}?"
                                     r"\b(?:initial catalog|database|user id|uid|password|pwd|integrated security|trusted_connection)\s*=)")),
    ("sensitive key with a value", re.compile(
        r"""(?i)["']?\b(?:password|passwd|pwd|secret|client_?secret|token|api_?key|accountkey|sharedaccesskey)\b["']?"""
        r"""\s*[:=]\s*["']?(?!\s|\*|<|\{|\$|["'])[^\s"';,<>]{3,}""")),
    ("credentials in a URL", re.compile(r"(?i)\b[a-z][a-z0-9+.-]{1,20}://[^\s/:@]{1,64}:[^\s/@]{1,128}@")),
    ("token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bsk-[A-Za-z0-9_-]{20,}"
                         r"|\bAKIA[0-9A-Z]{16}\b|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)

MIN_VALUE = 6            # shorter values ("true", "1433") would match ordinary text
# A filesystem path under a sensitive-looking key (ENTERPRISE_VAULT_SECRETS_DIR = D:\Vault\Secrets) is a path, not a
# secret: the step 5 rules keep a value "only for a path", and discovery records it as a hardcoded Windows path.
PLAIN_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)[^;=@\s]*$")
CONFIG_GLOBS = ("appsettings*.json", "*.config", "*.settings.json", "launchSettings.json", "secrets.json",
                "SetParam*.xml", "SetParameters*.xml", "*.pubxml", ".env", "*.env")
SKIP_DIRS = {".git", "bin", "obj", "node_modules", ".vs", "packages"}


def looks_like_connection_string(value: str) -> bool:
    pairs = [k.strip() for k, _ in CS_PAIR.findall(value)]
    return sum(1 for k in pairs if CS_KEYWORDS.match(k)) >= 2


def _connection_parts(value: str) -> list[str]:
    parts = [value.strip()]
    for key, part in CS_PAIR.findall(value):
        if key.strip().lower() in CS_CREDENTIAL_PARTS:
            parts.append(part.strip())
    return parts


URL_USERINFO = re.compile(r"(?i)\b[a-z][a-z0-9+.-]{1,20}://([^\s/:@]{1,64}):([^\s/@]{1,128})@")


def _url_passwords(path: str, value: str) -> list[tuple[str, str]]:
    return [(path, password) for _user, password in URL_USERINFO.findall(value)]


def _from_json(node, path: str, out: list[tuple[str, str]], sensitive: bool = False) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            child = f"{path}:{k}" if path else k
            _from_json(v, child, out, sensitive or is_sensitive_key(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _from_json(v, f"{path}[{i}]", out, sensitive)
    elif isinstance(node, str):
        if sensitive or looks_like_connection_string(node):
            out.extend((path, part) for part in _connection_parts(node))
        out.extend(_url_passwords(path, node))


def _from_xml(text: str, out: list[tuple[str, str]], all_values: bool) -> None:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return
    for el in root.iter():
        name = el.get("name") or el.get("key") or el.tag
        for attr, value in el.attrib.items():
            if attr in ("name", "key") or not value:
                continue
            if all_values or attr.lower() == "connectionstring" or is_sensitive_key(name) or looks_like_connection_string(value):
                out.extend((f"{name}@{attr}", part) for part in _connection_parts(value))
            out.extend(_url_passwords(f"{name}@{attr}", value))


def repository_values(root: Path) -> list[dict]:
    """[{file, key, value}] for every secret-bearing value in the repository's configuration."""
    found = []
    for pattern in CONFIG_GLOBS:
        for f in sorted(root.rglob(pattern)):
            if not f.is_file() or SKIP_DIRS & set(p.name for p in f.relative_to(root).parents):
                continue
            try:
                text = f.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            pairs: list[tuple[str, str]] = []
            if f.suffix.lower() == ".json":
                try:
                    _from_json(json.loads(re.sub(r"(?m)^\s*//.*$", "", text)), "", pairs)
                except ValueError:
                    pass
            elif f.suffix.lower() in (".config", ".xml", ".pubxml"):
                _from_xml(text, pairs, all_values=f.name.lower().startswith("setparam"))
            else:
                for line in text.splitlines():
                    k, sep, v = line.partition("=")
                    if sep and (is_sensitive_key(k.strip()) or looks_like_connection_string(v)):
                        pairs.extend((k.strip(), part) for part in _connection_parts(v))
                    pairs.extend(_url_passwords(k.strip(), v))
            rel = f.relative_to(root).as_posix()
            found.extend({"file": rel, "key": k, "value": v} for k, v in pairs
                         if len(v.strip()) >= MIN_VALUE and not PLAIN_PATH.match(v.strip()))
    unique = {(e["file"], e["key"], e["value"]): e for e in found}
    return [unique[k] for k in sorted(unique)]


def check(files: dict[str, str], repository_root: Path | None) -> list[dict]:
    """Findings, [{file, check, detail}], for generated `files` ({path: text}). Empty means none
    contains a secret value. No finding carries a value."""
    findings = []
    for path, text in sorted(files.items()):
        for check_name, shape in SHAPES:
            for m in shape.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                findings.append({"file": path, "check": check_name, "detail": f"line {line}"})
    if repository_root is not None:
        for secret in repository_values(repository_root):
            for path, text in sorted(files.items()):
                if secret["value"] in text:
                    findings.append({"file": path, "check": "repository value",
                                     "detail": f"the value of {secret['key']} in {secret['file']}"})
    return findings
