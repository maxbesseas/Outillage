"""Rejeu idempotent des écritures (en-tête Idempotency-Key) pour la file d'attente hors ligne."""
from datetime import timedelta

from fastapi import Request, Response
from fastapi.responses import JSONResponse
import jwt
from jwt import PyJWTError as JWTError
from sqlalchemy.exc import IntegrityError

from . import config, utils
from .database import SessionLocal
from .models import User
from .models_p3 import IdempotencyKey

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
MAX_STORED_BYTES = 1024 * 1024
# Réponses contenant des secrets : jamais conservées, jamais rejouées.
NEVER_STORED = ("/auth/", "/api-keys", "/imports", "/reset-password", "/calendar/token")


def _claims(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return {}
    try:
        return jwt.decode(header[7:], config.SECRET_KEY, algorithms=[config.ALGORITHM])
    except JWTError:
        return {}


def _username(request: Request):
    return _claims(request).get("sub")


def _replay(row: IdempotencyKey) -> Response:
    return Response(
        content=row.body or b"",
        status_code=row.status_code,
        media_type=row.content_type,
        headers={"Idempotent-Replay": "true"},
    )


async def idempotency_middleware(request: Request, call_next):
    key = request.headers.get("idempotency-key")
    path = request.url.path
    if not key or request.method not in WRITE_METHODS or len(key) > 100 or any(part in path for part in NEVER_STORED):
        return await call_next(request)
    claims = _claims(request)
    username = claims.get("sub")
    if not username:
        return await call_next(request)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user is None or not user.is_active or (user.token_version or 0) != claims.get("tv", 0):
            return await call_next(request)  # la route répondra 401
        existing = db.query(IdempotencyKey).filter_by(username=username, key=key).first()
        if existing:
            if existing.method != request.method or existing.path != path:
                return JSONResponse(status_code=409, content={"detail": "Clé d'idempotence déjà utilisée pour une autre opération"})
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
