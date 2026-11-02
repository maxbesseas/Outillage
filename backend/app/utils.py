import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from fastapi import UploadFile

from . import config, storage
from .config import UPLOAD_DIR

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

_clock: Optional[Callable[[], datetime]] = None


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

    return _store(subfolder, f"{uuid.uuid4().hex}{ext}", content)


def save_upload_file(file: UploadFile, subfolder: str) -> str:
    from fastapi import HTTPException

    content = file.file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=400, detail=f"Fichier trop volumineux (maximum {MAX_DOCUMENT_BYTES // (1024 * 1024)} Mo)")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".jpg"

    return _store(subfolder, f"{uuid.uuid4().hex}{ext}", content)
