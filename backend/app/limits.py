"""Limites anti-abus conservées en base : les instances serverless ne partagent aucune mémoire."""
from datetime import timedelta
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import audit, config, utils
from .database import SessionLocal
from .idempotency import _username
from .models_security import RateEvent

MAX_JSON_BYTES = 1024 * 1024
MAX_MULTIPART_BYTES = (max(config.MAX_UPLOAD_MB, 5) + 2) * 1024 * 1024
UPLOAD_BYTES_PER_DAY = 200 * 1024 * 1024
EXPORTS_PER_HOUR = 30
DENIED_LOGS_PER_HOUR = 50
EXPORT_PATHS = ("/exports/", "/agency-tools/export", "/inspections/registry", "/audit-log/export")


def allow(db: Session, key: str, limit: int, seconds: int, amount: int = 1) -> bool:
    """Enregistre l'événement s'il reste dans le quota ; n'écrit rien sinon, pour qu'un abus ne remplisse pas la table."""
    since = utils.now() - timedelta(seconds=seconds)
    used = db.query(func.coalesce(func.sum(RateEvent.amount), 0)).filter(RateEvent.key == key, RateEvent.created_at >= since).scalar()
    if used + amount > limit:
        return False
    db.add(RateEvent(key=key[:200], amount=amount, created_at=utils.now()))
    db.flush()
    return True


def purge_old(db: Session, days: int = 2) -> int:
    return db.query(RateEvent).filter(RateEvent.created_at < utils.now() - timedelta(days=days)).delete(synchronize_session=False)


def _too_large() -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": "Requête trop volumineuse"})


def _too_many(message: str, retry_after: int) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": message}, headers={"Retry-After": str(retry_after)})


def _quota(key: str, limit: int, seconds: int, amount: int = 1) -> bool:
    db = SessionLocal()
    try:
        allowed = allow(db, key, limit, seconds, amount)
        db.commit()
        return allowed
    finally:
        db.close()


def _content_length(request: Request) -> Optional[int]:
    try:
        return int(request.headers.get("content-length", ""))
    except ValueError:
        return None


def _log_denied(request: Request, username: str):
    db = SessionLocal()
    try:
        if allow(db, f"denied:{username}", DENIED_LOGS_PER_HOUR, 3600):
            audit.record(db, "access_denied", None, "route", request.url.path[:200], request, {"username": username[:150], "method": request.method})
        db.commit()
    finally:
        db.close()


async def limits_middleware(request: Request, call_next):
    length = _content_length(request) or 0
    is_multipart = request.headers.get("content-type", "").startswith("multipart/")
    if length > (MAX_MULTIPART_BYTES if is_multipart else MAX_JSON_BYTES):
        return _too_large()

    username = _username(request)
    if username:
        if is_multipart and request.method == "POST" and not _quota(f"upload:{username}", UPLOAD_BYTES_PER_DAY, 86400, length):
            return _too_many("Quota quotidien d'envoi de fichiers atteint", 3600)
        if request.method == "GET" and request.url.path.startswith(EXPORT_PATHS) and not _quota(f"export:{username}", EXPORTS_PER_HOUR, 3600):
            return _too_many("Trop d'exports, réessayez dans une heure", 3600)
    response = await call_next(request)
    if username and response.status_code == 403:
        _log_denied(request, username)
    return response
