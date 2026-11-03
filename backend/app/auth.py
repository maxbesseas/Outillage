import hashlib
from functools import lru_cache
import re
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import PyJWTError as JWTError
import bcrypt
from sqlalchemy.orm import Session

from . import charter, config, utils
from .database import get_db
from .models import RefreshToken, User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

PASSWORD_CHANGE_REQUIRED_DETAIL = "Vous devez changer votre mot de passe avant de continuer"
PASSWORD_CHANGE_HEADER = {"X-Auth-Error": "password_change_required"}
CHARTER_REQUIRED_DETAIL = "Vous devez accepter la charte avant de continuer"
CHARTER_REQUIRED_HEADER = {"X-Auth-Error": "charter_required"}

# Liste courte : refuse les mots de passe les plus employés, y compris avec un chiffre ajouté.
COMMON_PASSWORDS = {
    "password", "motdepasse", "azerty", "qwerty", "admin", "administrateur", "bonjour", "soleil", "fauche", "outillage",
    "chantier", "changeme", "welcome", "letmein", "doudou", "marseille", "toulouse", "nicolas", "thomas", "julien",
}

FILE_COOKIE = "fauche_files"
FILE_COOKIE_AUDIENCE = "uploads"
FILE_COOKIE_HOURS = 8


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8")[:72], hashed_password.encode("ascii"))
    except ValueError:
        return False


def validate_password_strength(password: str, username: Optional[str] = None):
    if len(password) < config.PASSWORD_MIN_LENGTH or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Le mot de passe doit contenir au moins {config.PASSWORD_MIN_LENGTH} caractères dont une lettre et un chiffre",
        )
    if config.IS_PROD and re.sub(r"[\d\W_]+", "", password).lower() in COMMON_PASSWORDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce mot de passe est trop courant, choisissez-en un autre")
    if username and password.lower() == username.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe ne doit pas être identique à l'identifiant",
        )


def generate_temporary_password() -> str:
    letters = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
    digits = "23456789"
    chars = [secrets.choice(letters) for _ in range(8)] + [secrets.choice(digits) for _ in range(4)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


@lru_cache(maxsize=1)
def _decoy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
        verify_password(password, _decoy_hash())  # même durée de réponse : ne révèle pas si le compte existe
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_access_token(user: User) -> str:
    expire = utils.now() + timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims = {"sub": user.username, "tv": user.token_version or 0, "exp": expire}
    return jwt.encode(claims, config.SECRET_KEY, algorithm=config.ALGORITHM)


def issue_refresh_token(db: Session, user: User, request: Optional[Request] = None) -> str:
    raw = secrets.token_urlsafe(48)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            created_at=utils.now(),
            expires_at=utils.now() + timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS),
            ip=client_ip(request),
            user_agent=(request.headers.get("user-agent", "")[:200] if request else None),
        )
    )
    return raw


def revoke_all_refresh_tokens(db: Session, user_id: int):
    now = utils.now()
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    ).update({"revoked_at": now}, synchronize_session=False)


def invalidate_sessions(db: Session, user: User):
    user.token_version = (user.token_version or 0) + 1
    revoke_all_refresh_tokens(db, user.id)


def set_file_cookie(response: Response, request: Request, user: User):
    """Les balises <img> n'envoient pas d'en-tête Authorization : un cookie limité à /uploads les authentifie."""
    expire = utils.now() + timedelta(hours=FILE_COOKIE_HOURS)
    token = jwt.encode({"sub": user.username, "tv": user.token_version or 0, "aud": FILE_COOKIE_AUDIENCE, "exp": expire},
                       config.SECRET_KEY, algorithm=config.ALGORITHM)
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(FILE_COOKIE, token, max_age=FILE_COOKIE_HOURS * 3600, path="/uploads", httponly=True, samesite="lax", secure=secure)


def clear_file_cookie(response: Response):
    response.delete_cookie(FILE_COOKIE, path="/uploads")


def user_from_file_cookie(request: Request, db: Session) -> Optional[User]:
    try:
        payload = jwt.decode(request.cookies.get(FILE_COOKIE, ""), config.SECRET_KEY, algorithms=[config.ALGORITHM], audience=FILE_COOKIE_AUDIENCE)
    except JWTError:
        return None
    user = db.query(User).filter(User.username == payload.get("sub")).first()
    if user is None or not user.is_active or (user.token_version or 0) != payload.get("tv", 0):
        return None
    if user.must_change_password and config.IS_PROD:
        return None
    return user


def client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None or request.client is None:
        return None
    return utils.client_ip(request)


def _decode_user(token: str, db: Session) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Identifiants invalides",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        username = payload.get("sub")
        token_version = payload.get("tv", 0)
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active or (user.token_version or 0) != token_version:
        raise credentials_exception
    return user


def get_current_user_any(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    return _decode_user(token, db)


def get_current_user(user: User = Depends(get_current_user_any)) -> User:
    if user.must_change_password and config.IS_PROD:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PASSWORD_CHANGE_REQUIRED_DETAIL,
            headers=PASSWORD_CHANGE_HEADER,
        )
    if config.CHARTER_ENFORCED and (user.charter_version or 0) < charter.VERSION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CHARTER_REQUIRED_DETAIL, headers=CHARTER_REQUIRED_HEADER)
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé aux administrateurs")
    return user


def get_current_manager(user: User = Depends(get_current_user)) -> User:
    if user.role == UserRole.gars_chantier:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé aux gestionnaires")
    return user
