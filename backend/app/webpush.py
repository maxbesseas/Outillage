"""Web Push (RFC 8030 / 8291 aes128gcm / 8292 VAPID) sans dépendance hors `cryptography`."""
import base64
import json
import os
import struct
import urllib.error
import urllib.request
from typing import Callable, Dict, Optional, Tuple
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.orm import Session

from . import appsettings, utils
from .models_ext import PushSubscription

VAPID_KEY_SETTING = "vapid.private_pem"
VAPID_SUBJECT = os.environ.get("OUTILLAGE_VAPID_SUBJECT", "mailto:admin@example.com")
_UNCOMPRESSED = serialization.PublicFormat.UncompressedPoint


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _public_bytes(public_key) -> bytes:
    return public_key.public_bytes(serialization.Encoding.X962, _UNCOMPRESSED)


def get_vapid_key(db: Session):
    pem = os.environ.get("OUTILLAGE_VAPID_PRIVATE_KEY") or appsettings.get(db, VAPID_KEY_SETTING)
    if not pem:
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        appsettings.set_value(db, VAPID_KEY_SETTING, pem)
        db.flush()
    return serialization.load_pem_private_key(pem.encode(), password=None)


def public_key_b64(db: Session) -> str:
    return b64u(_public_bytes(get_vapid_key(db).public_key()))


def encrypt_payload(payload: bytes, p256dh: str, auth: str) -> bytes:
    ua_public_bytes = b64u_decode(p256dh)
    auth_secret = b64u_decode(auth)
    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public_bytes)

    as_private = ec.generate_private_key(ec.SECP256R1())
    as_public_bytes = _public_bytes(as_private.public_key())
    shared = as_private.exchange(ec.ECDH(), ua_public)

    salt = os.urandom(16)
    key_info = b"WebPush: info\x00" + ua_public_bytes + as_public_bytes
    ikm = HKDF(hashes.SHA256(), 32, salt=auth_secret, info=key_info).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)

    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    header = salt + struct.pack(">I", 4096) + bytes([len(as_public_bytes)]) + as_public_bytes
    return header + ciphertext


def decrypt_payload(body: bytes, ua_private, auth: str) -> bytes:
    """Côté navigateur (utilisé par les tests pour vérifier le chiffrement)."""
    auth_secret = b64u_decode(auth)
    salt = body[:16]
    id_len = body[20]
    as_public_bytes = body[21 : 21 + id_len]
    ciphertext = body[21 + id_len :]
    as_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public_bytes)
    shared = ua_private.exchange(ec.ECDH(), as_public)
    ua_public_bytes = _public_bytes(ua_private.public_key())
    key_info = b"WebPush: info\x00" + ua_public_bytes + as_public_bytes
    ikm = HKDF(hashes.SHA256(), 32, salt=auth_secret, info=key_info).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    plaintext = AESGCM(cek).decrypt(nonce, ciphertext, None)
    return plaintext.rstrip(b"\x00")[:-1]


def vapid_headers(db: Session, endpoint: str) -> Dict[str, str]:
    key = get_vapid_key(db)
    parsed = urlparse(endpoint)
    audience = f"{parsed.scheme}://{parsed.netloc}"
    header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u(
        json.dumps(
            {"aud": audience, "exp": int(utils.now().timestamp()) + 12 * 3600, "sub": VAPID_SUBJECT},
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{claims}".encode()
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    token = f"{header}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return {"Authorization": f"vapid t={token}, k={public_key_b64(db)}"}


def _http_transport(endpoint: str, headers: Dict[str, str], body: bytes) -> int:
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


# Remplaçable dans les tests : (endpoint, headers, body) -> code HTTP
transport: Callable[[str, Dict[str, str], bytes], int] = _http_transport


def send_to_user(db: Session, user_id: int, payload: dict, ttl: int = 86400) -> Tuple[int, int]:
    """Envoie une notification push à tous les appareils. Retourne (envoyés, supprimés)."""
    subscriptions = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
    sent = removed = 0
    body_json = json.dumps(payload, ensure_ascii=False).encode()
    for sub in subscriptions:
        try:
            headers = {
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(ttl),
                "Urgency": "normal",
                **vapid_headers(db, sub.endpoint),
            }
            code = transport(sub.endpoint, headers, encrypt_payload(body_json, sub.p256dh, sub.auth))
        except Exception:
            code = 0
        if code in (404, 410):
            db.delete(sub)
            removed += 1
        elif 200 <= code < 300:
            sent += 1
    return sent, removed
