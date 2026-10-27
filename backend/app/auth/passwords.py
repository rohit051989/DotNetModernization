"""Passwords, stored only as salted scrypt hashes (hashlib, no extra dependency):

    scrypt$<n>$<r>$<p>$<salt, base64>$<hash, base64>

A 16-byte random salt per password; n = 2**15, r = 8, p = 1, a 32-byte key. Verification recomputes with the stored
parameters and compares in constant time. The plain password is never stored, logged or returned."""
import base64
import hashlib
import hmac
import secrets

N, R, P, KEY_BYTES = 2 ** 15, 8, 1, 32
MIN_LENGTH = 12


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=KEY_BYTES, maxmem=128 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = _derive(password, salt, N, R, P)
    return f"scrypt${N}${R}${P}${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}"


def verify(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, key = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(key)
        actual = _derive(password, base64.b64decode(salt), int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def weakness(password: str) -> str | None:
    """Why a new password is refused, or None."""
    if len(password) < MIN_LENGTH:
        return f"A password needs at least {MIN_LENGTH} characters."
    if password.strip() != password:
        return "A password may not start or end with a space."
    return None
