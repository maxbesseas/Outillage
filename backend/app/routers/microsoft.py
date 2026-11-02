"""Connexion avec un compte Microsoft (OpenID Connect, code et PKCE).

Aucun compte n'est créé ici : l'administrateur crée l'utilisateur et renseigne son e-mail. À la première connexion,
cet e-mail lie le compte à l'identité Microsoft (tid + oid), seule utilisée ensuite. Microsoft déconseille de se fier
à l'e-mail : il n'est retenu que s'il est vérifié, et un compte admin n'est jamais lié automatiquement.
"""
import base64
import hashlib
import secrets
import ssl
from datetime import timedelta
from functools import lru_cache
from typing import Optional
from urllib.parse import urlencode

import certifi
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import audit, config, utils
from ..auth import client_ip, hash_token
from ..database import get_db
from ..models import RefreshToken, User, UserRole
from ..security import record_login_attempt

router = APIRouter(prefix="/auth/microsoft", tags=["auth"])

PERSONAL_ACCOUNTS_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"
AUTHORITY = "https://login.microsoftonline.com"
FLOW_COOKIE = "ms_login"
FLOW_COOKIE_PATH = "/auth/microsoft"
FLOW_AUDIENCE = "microsoft-login-flow"
FLOW_SECONDS = 600
LOGIN_CODE_SECONDS = 60


def enabled() -> bool:
    return bool(config.MS_CLIENT_ID and config.MS_CLIENT_SECRET)


def _require_enabled():
    if not enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connexion Microsoft non configurée")


def _redirect_uri() -> str:
    return f"{config.PUBLIC_URL}/auth/microsoft/callback"


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    context = ssl.create_default_context(cafile=certifi.where())
    return jwt.PyJWKClient(f"{AUTHORITY}/{config.MS_TENANT}/discovery/v2.0/keys", ssl_context=context, timeout=10)


def _signing_key(id_token: str):
    return _jwks_client().get_signing_key_from_jwt(id_token).key


def _redeem_code(code: str, verifier: str) -> Optional[str]:
    response = httpx.post(
        f"{AUTHORITY}/{config.MS_TENANT}/oauth2/v2.0/token",
        data={
            "client_id": config.MS_CLIENT_ID,
            "client_secret": config.MS_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _redirect_uri(),
            "code_verifier": verifier,
            "scope": "openid email profile",
        },
        timeout=10,
    )
    return response.json().get("id_token") if response.status_code == 200 else None


def _verified_claims(id_token: str, expected_nonce: str) -> dict:
    """Vérifie signature, destinataire, expiration, émetteur et nonce ; lève une exception sinon."""
    claims = jwt.decode(
        id_token,
        _signing_key(id_token),
        algorithms=["RS256"],
        audience=config.MS_CLIENT_ID,
        options={"require": ["exp", "iat", "aud", "iss", "tid", "oid", "nonce"]},
    )
    if claims["iss"] != f"{AUTHORITY}/{claims['tid']}/v2.0":
        raise jwt.InvalidIssuerError("Émetteur inattendu")
    if not secrets.compare_digest(str(claims["nonce"]), expected_nonce):
        raise jwt.InvalidTokenError("Nonce inattendu")
    return claims


def _email_is_verified(claims: dict) -> bool:
    return claims["tid"] == PERSONAL_ACCOUNTS_TENANT or claims.get("xms_edov") in (True, 1, "1", "true")


def _find_user(db: Session, claims: dict) -> Optional[User]:
    tid, oid = claims["tid"], claims["oid"]
    linked = db.query(User).filter(User.microsoft_tid == tid, User.microsoft_oid == oid).first()
    if linked is not None:
        return linked

    email = (claims.get("email") or "").strip().lower()
    if not email or not _email_is_verified(claims):
        return None
    matches = db.query(User).filter(func.lower(User.email) == email).limit(2).all()
    if len(matches) != 1:
        return None
    user = matches[0]
    if user.role == UserRole.admin or user.microsoft_oid is not None:
        return None
    user.microsoft_tid, user.microsoft_oid = tid, oid
    return user


def _issue_login_code(db: Session, user: User, request: Request) -> str:
    """Jeton de renouvellement à usage unique et très court : le navigateur l'échange aussitôt via /auth/refresh."""
    raw = secrets.token_urlsafe(48)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            created_at=utils.now(),
            expires_at=utils.now() + timedelta(seconds=LOGIN_CODE_SECONDS),
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:200],
        )
    )
    return raw


def _back_to_login(query: str) -> RedirectResponse:
    response = RedirectResponse(f"/#/login?{query}", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_COOKIE_PATH)
    return response


@router.get("/config")
def microsoft_config():
    return {"enabled": enabled()}


@router.get("/login")
def microsoft_login():
    _require_enabled()
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    params = {
        "client_id": config.MS_CLIENT_ID,
        "response_type": "code",
        "response_mode": "query",
        "redirect_uri": _redirect_uri(),
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    response = RedirectResponse(
        f"{AUTHORITY}/{config.MS_TENANT}/oauth2/v2.0/authorize?{urlencode(params)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    flow = jwt.encode(
        {"state": state, "nonce": nonce, "verifier": verifier, "aud": FLOW_AUDIENCE,
         "exp": utils.now() + timedelta(seconds=FLOW_SECONDS)},
        config.SECRET_KEY,
        algorithm=config.ALGORITHM,
    )
    response.set_cookie(
        FLOW_COOKIE, flow, max_age=FLOW_SECONDS, path=FLOW_COOKIE_PATH, httponly=True, samesite="lax",
        secure=config.PUBLIC_URL.startswith("https://"),
    )
    return response


@router.get("/callback")
def microsoft_callback(request: Request, db: Session = Depends(get_db)):
    _require_enabled()
    params = request.query_params
    try:
        flow = jwt.decode(
            request.cookies.get(FLOW_COOKIE, ""), config.SECRET_KEY, algorithms=[config.ALGORITHM], audience=FLOW_AUDIENCE,
        )
    except jwt.InvalidTokenError:
        return _back_to_login("sso_error=failed")
    if not secrets.compare_digest(params.get("state", ""), flow["state"]):
        return _back_to_login("sso_error=failed")
    if params.get("error") == "access_denied":
        return _back_to_login("sso_error=cancelled")
    if not params.get("code"):
        return _back_to_login("sso_error=failed")

    try:
        id_token = _redeem_code(params["code"], flow["verifier"])
        claims = _verified_claims(id_token, flow["nonce"]) if id_token else None
    except (httpx.HTTPError, ValueError, jwt.PyJWTError):
        claims = None
    if claims is None:
        audit.record(db, "microsoft_login_failed", None, "user", None, request, {"reason": "invalid_token"})
        db.commit()
        return _back_to_login("sso_error=failed")

    user = _find_user(db, claims)
    if user is None or not user.is_active:
        db.rollback()
        audit.record(db, "microsoft_login_refused", user.id if user else None, "user", user.id if user else None, request)
        db.commit()
        return _back_to_login("sso_error=no_account")

    # La personne n'a pas utilisé le mot de passe temporaire : rien à changer pour elle.
    user.must_change_password = False
    record_login_attempt(db, user.username, client_ip(request), True)
    audit.record(db, "login_success", user.id, "user", user.id, request, {"method": "microsoft"})
    code = _issue_login_code(db, user, request)
    db.commit()
    return _back_to_login(urlencode({"sso": code}))
