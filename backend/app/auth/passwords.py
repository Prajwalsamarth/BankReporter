# backend/app/auth/passwords.py
"""Password hashing with the standard library's scrypt (spec §3.1)."""
import base64
import hashlib
import hmac
import secrets

N, R, P, KEY_LEN = 2**14, 8, 1, 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, dklen=KEY_LEN)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, key = stored.split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(key, validate=True)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt, validate=True),
                                n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)
