"""BOM / encoding detection for legacy-era text files.

See 19-SOLUTION-DISCOVERY.md Part F: "Legacy files are frequently
UTF-8 with BOM, occasionally UTF-16. Detect BOM, fall back to UTF-8 with
replacement, and warn rather than fail."
"""

from pathlib import Path


def read_text_detect_encoding(path: Path) -> tuple[str, str | None]:
    """Returns (text, warning). `warning` is set only when the file had no
    recognised BOM and was not valid UTF-8 either."""
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), None
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le"), None
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be"), None
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return (
            raw.decode("utf-8", errors="replace"),
            "file has no byte-order mark and is not valid UTF-8; decoded with replacement characters",
        )
