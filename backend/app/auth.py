import hashlib
import re
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import config, utils
from .database import get_db
from .models import RefreshToken, User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

PASSWORD_CHANGE_REQUIRED_DETAIL = "Vous devez changer votre mot de passe avant de continuer"
PASSWORD_CHANGE_HEADER = {"X-Auth-Error": "password_change_required"}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def validate_password_strength(password: str, username: Optional[str] = None):
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit contenir au moins 8 caractères dont une lettre et un chiffre",
        )
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


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.is_active:
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
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé aux administrateurs")
    return user


def get_current_manager(user: User = Depends(get_current_user)) -> User:
    if user.role == UserRole.gars_chantier:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé aux gestionnaires")
    return user
