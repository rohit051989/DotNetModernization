"""Does every JSON and XML configuration file in a working tree parse? (36-COPILOT-ENHANCED-CONVERSION Part N.)

The verifier asks this of the base commit and of the branch. A file the conversion made unparseable fails the
verification: the application cannot read it, and discovery cannot see inside it, so nothing that was in it can be
counted as resolved.

JSON is read as .NET configuration reads it (System.Text.Json with comments skipped and trailing commas allowed, as
discovery's JsonConfigWalker does), so a comment in appsettings.json is not a failure. XML is read as XML. A failure
names the file and where parsing stopped, never the text there: a configuration file can hold a secret.

    python -m app.engine.configfiles <folder>      lists every file that does not parse; exit 1 if any
"""
import json
import sys
from pathlib import Path
from xml.etree import ElementTree

JSON_SUFFIXES = (".json",)
XML_SUFFIXES = (".config", ".xml", ".pubxml")
SKIP_DIRS = {".git", ".vs", "bin", "obj", "node_modules", "packages", "TestResults"}


def _blank_comments(text: str) -> str:
    """`//` and `/* */` comments outside strings replaced by spaces, newlines kept: every position stays where it was."""
    out, i, n, in_string = list(text), 0, len(text), False
    while i < n:
        c = text[i]
        if in_string:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            for j in range(i, end):
                if out[j] != "\n":
                    out[j] = " "
            i = end
            continue
        i += 1
    return "".join(out)


def _blank_trailing_commas(text: str) -> str:
    """A comma outside strings followed only by whitespace and `}` or `]` replaced by a space."""
    out, in_string, i = list(text), False, 0
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == ",":
            rest = text[i + 1:].lstrip()
            if rest[:1] in ("}", "]"):
                out[i] = " "
        i += 1
    return "".join(out)


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8-sig")


def json_error(data: bytes) -> str | None:
    """None when `data` parses as .NET configuration JSON, else where it stopped."""
    try:
        text = _decode(data)
    except UnicodeDecodeError as err:
        return f"not UTF-8 or UTF-16 text (byte {err.start})"
    if not text.strip():
        return None                     # an empty settings file is read as an empty configuration
    try:
        json.loads(_blank_trailing_commas(_blank_comments(text)))
    except json.JSONDecodeError as err:
        return f"invalid JSON at line {err.lineno}, position {err.colno}: {err.msg}"
    return None


def xml_error(data: bytes) -> str | None:
    """None when `data` parses as XML, else where it stopped."""
    try:
        ElementTree.fromstring(data)
    except ElementTree.ParseError as err:
        line, column = err.position
        reason = str(err).split(":")[0]
        return f"invalid XML at line {line}, position {column + 1}: {reason}"
    return None


def is_config_file(relative: str) -> bool:
    return relative.lower().endswith(JSON_SUFFIXES + XML_SUFFIXES)


def unparseable(root: Path, exclude: tuple[str, ...] = ()) -> dict[str, str]:
    """{repository-relative path ("/" separated): where parsing stopped} for every JSON and XML configuration file
    under `root` that does not parse. Build output, package folders and paths under `exclude` are not read."""
    from app.engine import paths

    found = {}
    for f in sorted(root.rglob("*")):
        if not f.is_file() or not is_config_file(f.name):
            continue
        rel = f.relative_to(root)
        if SKIP_DIRS & set(rel.parts[:-1]):
            continue
        relative = rel.as_posix()
        if exclude and paths.is_under(relative, exclude):
            continue
        try:
            data = f.read_bytes()
        except OSError as err:
            found[relative] = f"unreadable: {err.strerror}"
            continue
        error = json_error(data) if relative.lower().endswith(JSON_SUFFIXES) else xml_error(data)
        if error:
            found[relative] = error
    return found


def counted(root: Path) -> int:
    """How many configuration files `unparseable` reads under `root`."""
    return sum(1 for f in root.rglob("*") if f.is_file() and is_config_file(f.name)
               and not SKIP_DIRS & set(f.relative_to(root).parts[:-1]))


if __name__ == "__main__":
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    bad = unparseable(folder)
    for path, where in bad.items():
        print(f"{path}: {where}")
    print(f"{counted(folder)} configuration file(s), {len(bad)} do not parse")
    sys.exit(1 if bad else 0)
