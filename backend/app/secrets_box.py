"""Chiffre les secrets conservés en base avec une clé dérivée de OUTILLAGE_SECRET_KEY.

Changer cette clé rend ces secrets illisibles : il faut alors ressaisir le mot de passe SMTP et réactiver la double authentification.
"""
import base64
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import config

PREFIX = "enc1:"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = HKDF(hashes.SHA256(), 32, salt=None, info=b"fauche-secrets-en-base").derive(config.SECRET_KEY.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def is_sealed(value: Optional[str]) -> bool:
    return bool(value) and value.startswith(PREFIX)


def seal(value: Optional[str]) -> Optional[str]:
    if not value or is_sealed(value):
        return value
    return PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def unseal(value: Optional[str]) -> Optional[str]:
    """Les valeurs enregistrées avant le chiffrement restent lisibles telles quelles."""
    if not is_sealed(value):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None
