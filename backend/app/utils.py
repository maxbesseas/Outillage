import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from fastapi import UploadFile

from . import config, storage
from .config import UPLOAD_DIR

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_clock: Optional[Callable[[], datetime]] = None


def safe_text(value):
    """Neutralise l'injection de formules (=, +, -, @) et retire les caractères de contrôle, refusés par les classeurs."""
    if not isinstance(value, str):
        return value
    if value.startswith(DANGEROUS_PREFIXES):
        value = "'" + value
    return CONTROL_CHARS.sub(" ", value)


def now() -> datetime:
    return _clock() if _clock else datetime.utcnow()


def set_clock(fn: Optional[Callable[[], datetime]]):
    global _clock
    _clock = fn


DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
MAX_DOCUMENT_BYTES = config.MAX_UPLOAD_MB * 1024 * 1024


def client_ip(request) -> Optional[str]:
    if request is None:
        return None
    if config.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else None


def image_extension(content: bytes) -> Optional[str]:
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return None


def _strip_jpeg(data: bytes) -> bytes:
    out, i = bytearray(data[:2]), 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return data
        marker = data[i + 1]
        if marker == 0xDA:
            return bytes(out + data[i:])
        size = int.from_bytes(data[i + 2:i + 4], "big")
        if marker not in (0xE1, 0xED):  # EXIF, GPS, XMP, IPTC
            out += data[i:i + 2 + size]
        i += 2 + size
    return data


def _strip_png(data: bytes) -> bytes:
    out, i = bytearray(data[:8]), 8
    while i + 12 <= len(data):
        size = int.from_bytes(data[i:i + 4], "big")
        chunk = data[i + 4:i + 8]
        if chunk not in (b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"tIME"):
            out += data[i:i + 12 + size]
        i += 12 + size
    return bytes(out) if i == len(data) else data


def _strip_webp(data: bytes) -> bytes:
    out, i = bytearray(), 12
    while i + 8 <= len(data):
        chunk = data[i:i + 4]
        size = int.from_bytes(data[i + 4:i + 8], "little")
        block = bytearray(data[i:i + 8 + size + (size & 1)])
        if chunk == b"VP8X" and len(block) > 8:
            block[8] &= ~0x0C  # retire les drapeaux EXIF et XMP
        if chunk not in (b"EXIF", b"XMP "):
            out += block
        i += 8 + size + (size & 1)
    return b"RIFF" + (len(out) + 4).to_bytes(4, "little") + b"WEBP" + bytes(out)


def strip_image_metadata(content: bytes) -> bytes:
    """Retire les métadonnées (GPS compris) des photos, car elles peuvent situer une personne."""
    kind = image_extension(content)
    strip = {".jpg": _strip_jpeg, ".png": _strip_png, ".webp": _strip_webp}.get(kind)
    return strip(content) if strip else content


def _store(subfolder: str, filename: str, content: bytes) -> str:
    if storage.enabled():
        storage.put(f"{subfolder}/{filename}", content)
    else:
        folder = UPLOAD_DIR / subfolder
        folder.mkdir(parents=True, exist_ok=True)
        (folder / filename).write_bytes(content)
    return f"/uploads/{subfolder}/{filename}"


def save_document(file: UploadFile, subfolder: str, allowed=DOCUMENT_EXTENSIONS, max_bytes: int = MAX_DOCUMENT_BYTES) -> str:
    """Enregistre un justificatif (liste blanche d'extensions, taille maximale)."""
    from fastapi import HTTPException

    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Format non autorisé ({', '.join(sorted(allowed))})")
    content = file.file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=400, detail=f"Fichier trop volumineux (maximum {max_bytes // (1024 * 1024)} Mo)")
    if ext == ".pdf" and not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Le fichier n'est pas un PDF valide")
    if ext != ".pdf":
        real = image_extension(content)
        if real is None:
            raise HTTPException(status_code=400, detail="Le fichier n'est pas une image valide")
        ext, content = real, strip_image_metadata(content)

    return _store(subfolder, f"{uuid.uuid4().hex}{ext}", content)


def save_upload_file(file: UploadFile, subfolder: str) -> str:
    from fastapi import HTTPException

    content = file.file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=400, detail=f"Fichier trop volumineux (maximum {MAX_DOCUMENT_BYTES // (1024 * 1024)} Mo)")
    ext = image_extension(content)
    if ext is None:
        raise HTTPException(status_code=400, detail="Le fichier doit être une image JPEG, PNG ou WebP")
    content = strip_image_metadata(content)

    return _store(subfolder, f"{uuid.uuid4().hex}{ext}", content)
