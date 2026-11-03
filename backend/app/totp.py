"""Codes à usage unique (TOTP, RFC 6238), compatibles avec les applications d'authentification courantes."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

PERIOD = 30
DIGITS = 6
WINDOW = 1


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(base64.b32decode(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(now: Optional[float] = None) -> int:
    return int((time.time() if now is None else now) // PERIOD)


def verify(secret: str, code: str, last_step: Optional[int] = None, now: Optional[float] = None) -> Optional[int]:
    """Renvoie le pas de temps du code valide, None sinon. Un code déjà utilisé (pas <= last_step) est refusé."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    base = current_step(now)
    for step in range(base - WINDOW, base + WINDOW + 1):
        if (last_step is None or step > last_step) and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def uri(username: str, secret: str, issuer: str = "Fauché Outillage") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(username)}?secret={secret}&issuer={quote(issuer)}&digits={DIGITS}&period={PERIOD}"
