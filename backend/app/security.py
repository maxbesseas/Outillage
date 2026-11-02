from datetime import timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from starlette.requests import Request

from . import config, utils
from .models import LoginAttempt

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
)

BLOCK_BASE_SECONDS = 60
BLOCK_MAX_SECONDS = 3600


def apply_security_headers(response, request: Request):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
        response.headers.setdefault("Content-Security-Policy", CSP)
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


def _consecutive_failures(db: Session, column, value: str):
    rows = (
        db.query(LoginAttempt)
        .filter(column == value)
        .order_by(LoginAttempt.id.desc())
        .limit(50)
        .all()
    )
    count = 0
    last_failure = None
    for row in rows:
        if row.success:
            break
        count += 1
        if last_failure is None:
            last_failure = row.created_at
    return count, last_failure


def _remaining_block(count: int, threshold: int, last_failure) -> int:
    if count < threshold or last_failure is None:
        return 0
    seconds = min(BLOCK_BASE_SECONDS * (2 ** (count - threshold)), BLOCK_MAX_SECONDS)
    until = last_failure + timedelta(seconds=seconds)
    remaining = int((until - utils.now()).total_seconds())
    return max(remaining, 0)


def check_login_allowed(db: Session, username: str, ip: Optional[str]):
    remaining = 0
    count, last = _consecutive_failures(db, LoginAttempt.identifier, username.lower())
    remaining = max(remaining, _remaining_block(count, config.LOGIN_MAX_FAILURES_USER, last))
    if ip:
        count, last = _consecutive_failures(db, LoginAttempt.ip, ip)
        remaining = max(remaining, _remaining_block(count, config.LOGIN_MAX_FAILURES_IP, last))

    if remaining > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Trop de tentatives. Réessayez dans {remaining} seconde(s).",
            headers={"Retry-After": str(remaining)},
        )


def record_login_attempt(db: Session, username: str, ip: Optional[str], success: bool):
    db.add(LoginAttempt(identifier=username.lower(), ip=ip, success=success, created_at=utils.now()))
