"""No generated file contains a secret value (36-COPILOT-ENHANCED-CONVERSION Part D; the entry-point-inventory
rules, 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES C5).

A value is secret by what it is, never by where it came from: its key is sensitive, as discovery classifies keys
(`Secrets.cs`, steps/step-003-fingerprinting/src/Fingerprinting.Analysis), or the value itself has a secret's shape
(a connection string, a URL with credentials in it, a token). A binding name, a host name, a URL, a path or any other
ordinary configuration value is not secret, wherever it is set: a Web Deploy SetParameters file included.

Two checks, both run by the generator before anything is written:

1. **Shapes.** Nothing in a generated file looks like a secret: a connection string, a sensitive key with
   a value, a URL with credentials in it, or a token.
2. **The repository's own secret values.** Every value the repository's configuration holds under a sensitive
   key, every connection string and its credential parts, every password in a URL and every value shaped like a
   secret is read from the repository and must not appear in any generated file. A leak of such a value is caught
   even where it does not look like a secret in the generated text.

A repository value is found only as a whole token ("Application" is not in "ApplicationSettings"), and never inside a
repository-relative path the generator itself wrote: there it is a folder or file name, and replacing it would point
the engine at a file that does not exist. A configuration transform's own attributes (xdt:Transform="Replace") are
never values.

A secret is never written: where a generated file would quote one, the generator puts a reference to where it is
instead (`reference`: its file, key and line), records a warning naming the generated file, and goes on (`redact`,
`redact_files`). It refuses only if a secret would still be written after that.

Values are read only to compare and replace them and are never printed: a finding or a warning names the generated
file, the check and, for the second check, the configuration file, key and line, never the value.
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

# A segment of a configuration key's path, as the generator names keys (EnterpriseAuthentication:Token:SigningKey):
# a sensitive word, a colon with no space, then a PascalCase name. Not a key with a value.
CONFIG_KEY_PATH = re.compile(r"""["']?\w+["']?:[A-Z][A-Za-z0-9]*(?::[A-Z][A-Za-z0-9]*)*`?""")

MIN_VALUE = 6           # shorter values ("true", "1433") would match ordinary text
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


def shapes_in(text: str) -> list[tuple[str, re.Match]]:
    """[(check, match)] for every secret shape in `text`."""
    found = []
    for check_name, shape in SHAPES:
        for m in shape.finditer(text):
            if check_name == "sensitive key with a value" and CONFIG_KEY_PATH.fullmatch(m.group(0)):
                continue        # Token:SigningKey is a configuration key's path, not a token with a value
            found.append((check_name, m))
    return found


def _secret(key: str, value: str, sensitive: bool) -> list[tuple[str, str]]:
    """[(key, value)] of what in one configuration value is secret: all of it under a sensitive key or when it is a
    connection string (with its credential parts), a password in a URL, or a value shaped like a secret. Nothing for
    an ordinary value: a binding name, a host name, a URL, a path."""
    if sensitive or looks_like_connection_string(value):
        return [(key, part) for part in _connection_parts(value)]
    out = _url_passwords(key, value)
    if not out and shapes_in(value):
        out.append((key, value.strip()))
    return out


def _from_json(node, path: str, out: list[tuple[str, str]], sensitive: bool = False) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            child = f"{path}:{k}" if path else k
            _from_json(v, child, out, sensitive or is_sensitive_key(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _from_json(v, f"{path}[{i}]", out, sensitive)
    elif isinstance(node, str):
        out.extend(_secret(path, node, sensitive))
        if sensitive or looks_like_connection_string(node):
            out.extend(_url_passwords(path, node))


XDT = "http://schemas.microsoft.com/XML-Document-Transform"      # xdt:Transform, xdt:Locator: how, never what


def _local(name: str) -> str:
    """An XML name without its namespace: {uri}local -> local."""
    return name.rsplit("}", 1)[-1]


def _from_xml(text: str, out: list[tuple[str, str]]) -> None:
    """A Web Deploy SetParameters file is configuration like any other: a parameter's value is secret when its name
    is sensitive (DbPassword) or the value has a secret's shape, never because a SetParameters file sets it.

    An element's name or key names its attributes' values. An element with neither (<connectionStrings>,
    <clientCredentials>) names only its own text by its tag: its attributes are judged by their own names and values,
    so a tag that sounds sensitive does not make every attribute under it a secret. A configuration transform's own
    attributes (xdt:Transform="Replace", xdt:Locator) say how to transform, never a value, and are ignored."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue                    # a comment or processing instruction
        tag = _local(el.tag)
        named = el.get("name") or el.get("key")
        for attr, value in el.attrib.items():
            if attr.startswith(f"{{{XDT}}}") or attr in ("name", "key") or not value:
                continue
            attr = _local(attr)
            sensitive = attr.lower() == "connectionstring" or is_sensitive_key(attr) or bool(named and is_sensitive_key(named))
            key = f"{named or tag}@{attr}"
            out.extend(_secret(key, value, sensitive))
            if sensitive or looks_like_connection_string(value):
                out.extend(_url_passwords(key, value))
        content = (el.text or "").strip()
        if content:
            out.extend(_secret(named or tag, content, is_sensitive_key(named or tag)))


def _line_of(text: str, key: str, value: str) -> int | None:
    """The line the value is set on: where it first appears, else (escaped in JSON) where its key's last part does."""
    at = text.find(value)
    if at < 0:
        name = key.split("@")[0].split(":")[-1]          # Section:Key, or an XML element's name@attribute
        at = text.find(name) if name else -1
    return text.count("\n", 0, at) + 1 if at >= 0 else None


def repository_values(root: Path) -> list[dict]:
    """[{file, key, line, value}] for every secret value in the repository's configuration."""
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
                _from_xml(text, pairs)
            else:
                for line in text.splitlines():
                    k, sep, v = line.partition("=")
                    if sep:
                        pairs.extend(_secret(k.strip(), v.strip(), is_sensitive_key(k.strip())))
            rel = f.relative_to(root).as_posix()
            found.extend({"file": rel, "key": k, "line": _line_of(text, k, v), "value": v} for k, v in pairs
                         if len(v.strip()) >= MIN_VALUE and not PLAIN_PATH.match(v.strip()))
    unique = {(e["file"], e["key"], e["value"]): e for e in found}
    return [unique[k] for k in sorted(unique)]


# ---------------------------------------------------------------- references in place of secret values

REFERENCE = re.compile(r"\[not copied: [^\]\n]*\]")
MAX_REPLACEMENTS = 1000             # per generated file; what is left after them is refused by `check`


def reference(secret: dict | None = None, place: str | None = None, kind: str | None = None) -> str:
    """What a generated file says in place of a secret value: where to find it, never the value. `secret`: a
    repository value ({file, key, line}); else the `place` it was found at, or the `kind` of shape it had."""
    if secret is not None:
        at = f"{secret['file']}:{secret['line']}" if secret.get("line") else secret["file"]
        return f"[not copied: the value of {secret['key']} in {at}]"
    if place:
        return f"[not copied: the value at {place}]"
    return f"[not copied: a value shaped like a {kind or 'secret'}]"


def whole(value: str) -> re.Pattern:
    """`value` as a whole token: not part of a longer word, so "Application" is not found in "ApplicationSettings".
    A value that starts or ends with punctuation is bounded by its punctuation there."""
    before = r"(?<![A-Za-z0-9_])" if re.match(r"\w", value[:1]) else ""
    after = r"(?![A-Za-z0-9_])" if re.match(r"\w", value[-1:]) else ""
    return re.compile(before + re.escape(value) + after)


def paths_of(model: dict) -> set[str]:
    """Every repository-relative path the generator writes from the model: the repository's files, projects, the files
    of every place, impact and test, the deployment files and the delta sites. A value inside one is part of a path."""
    found = set(model.get("files") or [])
    found |= {p["path"] for p in model.get("projects") or [] if p.get("path")}
    for item in model.get("items") or []:
        for occ in item.get("occurrences") or []:
            found |= {occ.get("file"), occ.get("project")}
        for e in item.get("impact") or []:
            found |= {e.get("file"), e.get("proposed"), e.get("project")}
    for m in model.get("test_mappings") or []:
        found |= {m.get("source_file"), m.get("test_file")}
    found |= {v.get("file") for v in model.get("vault_delivery") or []}
    for d in model.get("deltas") or []:
        for fix_file, consumers in (d.get("sites") or {}).items():
            found |= {fix_file, *consumers}
    for o in model.get("outbound") or []:
        found |= {b.get("file") for b in o.get("bindings") or []}
    return {p for p in found if p}


def repository_paths(root: Path) -> set[str]:
    """The repository's files, relative: the paths a generated file can name when no model says which."""
    return {f.relative_to(root).as_posix() for f in root.rglob("*")
            if f.is_file() and not SKIP_DIRS & set(p.name for p in f.relative_to(root).parents)}


def _in_path(text: str, m: re.Match, paths: set[str]) -> bool:
    """True when the match lies within one of `paths` written in `text`. Only a path holding the matched text can."""
    token = m.group(0)
    for p in paths:
        i = p.find(token)
        while i >= 0:
            start = m.start() - i
            if start >= 0 and text.startswith(p, start):
                return True
            i = p.find(token, i + 1)
    return False


def _found(text: str, value: str, paths: set[str]) -> list[re.Match]:
    """Each place `value` stands as a whole token in `text`, outside the paths the generator wrote. Inside a path it is
    a folder or file name, never replaced: the engine would look for a file that does not exist."""
    return [m for m in whole(value).finditer(text) if not _in_path(text, m, paths)]


def secret_in(value: str | None, values: list[dict]) -> dict | bool | None:
    """The repository secret `value` holds as a whole token ({file, key, line, value}), True when it only has a
    secret's shape, else None."""
    if not value:
        return None
    for secret in sorted(values, key=lambda s: -len(s["value"])):
        if whole(secret["value"]).search(value):
            return secret
    return True if shapes_in(value) or looks_like_connection_string(value) else None


def redact(model: dict, repository_root: Path | None) -> dict:
    """The model with every secret value it would quote replaced by a reference to where it is: each place's value
    and each line's (an instruction's places, the decision sheet's unresolved values, the deployment parameter names
    made from a value). Everything else is kept as it is."""
    values = repository_values(repository_root) if repository_root is not None else []
    items = []
    for item in model.get("items", []):
        occurrences = []
        for occ in item["occurrences"]:
            first = (occ.get("lines") or [{}])[0]
            place = f"{occ.get('file') or occ.get('project')}" + (f":{first['line']}" if first.get("line") else "")
            found = secret_in(occ.get("value"), values)
            occ = {**occ, "value": reference(found if isinstance(found, dict) else None, place)} if found else occ
            lines = []
            for line in occ.get("lines") or []:
                found = secret_in(line.get("value"), values)
                at = f"{occ.get('file') or occ.get('project')}:{line['line']}"
                lines.append({**line, "value": reference(found if isinstance(found, dict) else None, at)} if found else line)
            occurrences.append({**occ, "lines": lines})
        items.append({**item, "occurrences": occurrences})
    return {**model, "items": items}


def _paths(repository_root: Path | None, paths: set[str] | None) -> set[str]:
    if paths is not None:
        return paths
    return repository_paths(repository_root) if repository_root is not None else set()


def redact_files(files: dict[str, str], repository_root: Path | None, paths: set[str] | None = None) -> dict[str, str]:
    """The generated files with any secret value still in them replaced by a reference: a repository value by its
    file, key and line, wherever it stands as a whole token; a value only shaped like a secret by its kind. Never
    inside a path the generator wrote (`paths`; the repository's files when not given). The safety net behind
    `redact`."""
    values = repository_values(repository_root) if repository_root is not None else []
    paths = _paths(repository_root, paths)
    out = {}
    for path, text in files.items():
        for secret in sorted(values, key=lambda s: -len(s["value"])):
            for m in reversed(_found(text, secret["value"], paths)):
                text = text[:m.start()] + reference(secret) + text[m.end():]
        # One at a time, the first in the text each time: two shapes can overlap (a connection string holds a password).
        for _ in range(MAX_REPLACEMENTS):
            found = [(c, m) for c, m in shapes_in(text) if not _in_path(text, m, paths)]
            if not found:
                break
            check_name, m = min(found, key=lambda x: x[1].start())
            text = text[:m.start()] + reference(kind=check_name) + text[m.end():]
        out[path] = text
    return out


def warnings(files: dict[str, str]) -> list[dict]:
    """[{file, references}]: each generated file that names a secret by reference instead of quoting it, and how
    many it names."""
    return [{"file": path, "references": len(REFERENCE.findall(text))}
            for path, text in sorted(files.items()) if REFERENCE.search(text)]


def check(files: dict[str, str], repository_root: Path | None, paths: set[str] | None = None) -> list[dict]:
    """Findings, [{file, check, detail}], for generated `files` ({path: text}). Empty means none
    contains a secret value. No finding carries a value. A repository value counts only as a whole token, and nothing
    inside a path the generator wrote counts (`paths`; the repository's files when not given)."""
    paths = _paths(repository_root, paths)
    findings = []
    for path, text in sorted(files.items()):
        for check_name, m in shapes_in(text):
            if _in_path(text, m, paths):
                continue
            line = text.count("\n", 0, m.start()) + 1
            findings.append({"file": path, "check": check_name, "detail": f"line {line}"})
    if repository_root is not None:
        for secret in repository_values(repository_root):
            for path, text in sorted(files.items()):
                if _found(text, secret["value"], paths):
                    findings.append({"file": path, "check": "repository value",
                                     "detail": f"the value of {secret['key']} in {secret['file']}"})
    return findings
