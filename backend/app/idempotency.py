"""Rejeu idempotent des écritures (en-tête Idempotency-Key) pour la file d'attente hors ligne."""
from datetime import timedelta

from fastapi import Request, Response
from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError

from . import config, utils
from .database import SessionLocal
from .models_p3 import IdempotencyKey

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
MAX_STORED_BYTES = 1024 * 1024


def _username(request: Request):
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    try:
        return jwt.decode(header[7:], config.SECRET_KEY, algorithms=[config.ALGORITHM]).get("sub")
    except JWTError:
        return None


def _replay(row: IdempotencyKey) -> Response:
    return Response(
        content=row.body or b"",
        status_code=row.status_code,
        media_type=row.content_type,
        headers={"Idempotent-Replay": "true"},
    )


async def idempotency_middleware(request: Request, call_next):
    key = request.headers.get("idempotency-key")
    if not key or request.method not in WRITE_METHODS or len(key) > 100:
        return await call_next(request)
    username = _username(request)
    if not username:
        return await call_next(request)

    db = SessionLocal()
    try:
        existing = db.query(IdempotencyKey).filter_by(username=username, key=key).first()
        if existing:
            return _replay(existing)
    finally:
        db.close()

    response = await call_next(request)
    if not 200 <= response.status_code < 300:
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length",)}
    if len(body) <= MAX_STORED_BYTES:
        db = SessionLocal()
        try:
            db.add(IdempotencyKey(
                key=key, username=username, method=request.method, path=request.url.path,
                status_code=response.status_code, content_type=response.headers.get("content-type"),
                body=body, created_at=utils.now(),
            ))
            db.commit()
        except IntegrityError:
            db.rollback()
        finally:
            db.close()
    return Response(content=body, status_code=response.status_code, headers=headers)


def purge_old(db, days: int = 7) -> int:
    n = db.query(IdempotencyKey).filter(IdempotencyKey.created_at < utils.now() - timedelta(days=days)).delete()
    db.commit()
    return n
