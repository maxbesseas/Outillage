import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import audit, config, limits, schemas, secrets_box, totp, utils
from ..auth import (
    authenticate_user,
    clear_file_cookie,
    client_ip,
    create_access_token,
    get_current_user,
    get_current_user_any,
    hash_password,
    hash_token,
    invalidate_sessions,
    issue_refresh_token,
    set_file_cookie,
    validate_password_strength,
    verify_password,
)
from ..database import get_db
from ..models import PasswordResetToken, RefreshToken, User
from ..notifications import send_email
from ..security import check_login_allowed, record_login_attempt

router = APIRouter(prefix="/auth", tags=["auth"])

GENERIC_FORGOT_DETAIL = "Si un compte correspond, un email de réinitialisation a été envoyé."
RESET_MAX_PER_HOUR = 3
FORGOT_MAX_PER_IP_HOUR = 20
MFA_REQUIRED_DETAIL = "Saisissez le code de vérification"


def _token_response(db: Session, user: User, request: Request, response: Response) -> dict:
    refresh = issue_refresh_token(db, user, request)
    set_file_cookie(response, request, user)
    return {
        "access_token": create_access_token(user),
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": user,
    }


@router.post("/login", response_model=schemas.Token)
def login(payload: schemas.LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_login_allowed(db, payload.username, ip)

    user = authenticate_user(db, payload.username, payload.password)
    if not user:
        record_login_attempt(db, payload.username, ip, False)
        audit.record(db, "login_failed", None, "user", None, request, {"username": payload.username})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiant ou mot de passe incorrect")

    if user.totp_enabled:
        if not payload.otp:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=MFA_REQUIRED_DETAIL, headers={"X-Auth-Error": "mfa_required"})
        step = totp.verify(secrets_box.unseal(user.totp_secret) or "", payload.otp, user.totp_last_step)
        if step is None:
            record_login_attempt(db, payload.username, ip, False)
            audit.record(db, "login_failed", user.id, "user", user.id, request, {"reason": "code de vérification"})
            db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Code de vérification incorrect", headers={"X-Auth-Error": "mfa_required"})
        user.totp_last_step = step

    record_login_attempt(db, payload.username, ip, True)
    audit.record(db, "login_success", user.id, "user", user.id, request)
    tokens = _token_response(db, user, request, response)
    db.commit()
    return tokens


@router.post("/refresh", response_model=schemas.Token)
def refresh(payload: schemas.RefreshRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expirée")
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == hash_token(payload.refresh_token)).first()
    if row is None:
        raise invalid

    user = db.query(User).filter(User.id == row.user_id).first()
    now = utils.now()

    if row.revoked_at is not None:
        if user and (now - row.revoked_at) > timedelta(seconds=10):
            invalidate_sessions(db, user)
            audit.record(db, "refresh_token_reuse", user.id, "user", user.id, request)
            db.commit()
        raise invalid

    if row.expires_at < now or user is None or not user.is_active:
        raise invalid

    row.revoked_at = now
    tokens = _token_response(db, user, request, response)
    db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: schemas.RefreshRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    clear_file_cookie(response)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == hash_token(payload.refresh_token)).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = utils.now()
        # Invalide les jetons d'accès en cours ; les autres appareils en obtiennent un nouveau par leur renouvellement.
        user = db.query(User).filter(User.id == row.user_id).first()
        if user is not None:
            user.token_version = (user.token_version or 0) + 1
        audit.record(db, "logout", row.user_id, "user", row.user_id, request)
        db.commit()
    return None


@router.post("/file-cookie", status_code=status.HTTP_204_NO_CONTENT)
def file_cookie(request: Request, response: Response, current_user: User = Depends(get_current_user)):
    """Pose le cookie des fichiers pour une session ouverte avant son introduction."""
    set_file_cookie(response, request, current_user)


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: User = Depends(get_current_user_any)):
    return current_user


@router.patch("/me", response_model=schemas.UserOut)
def update_me(
    payload: schemas.ProfileUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = payload.model_dump(exclude_unset=True)
    current_password = data.pop("current_password", None)
    if "email" in data and (data["email"] or "").lower() != (current_user.email or "").lower():
        ip = client_ip(request)
        check_login_allowed(db, current_user.username, ip)
        if not current_password or not verify_password(current_password, current_user.hashed_password):
            record_login_attempt(db, current_user.username, ip, False)
            db.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mot de passe actuel requis pour changer d'e-mail")
        if data["email"] and db.query(User).filter(func.lower(User.email) == data["email"].lower(), User.id != current_user.id).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cet e-mail est déjà utilisé par un autre compte")
        current_user.microsoft_tid = current_user.microsoft_oid = None
    for field, value in data.items():
        setattr(current_user, field, value or None)
    audit.record(db, "profile_updated", current_user.id, "user", current_user.id, request, {"fields": sorted(data.keys())})
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/change-password", response_model=schemas.Token)
def change_password(
    payload: schemas.ChangePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_any),
):
    ip = client_ip(request)
    check_login_allowed(db, current_user.username, ip)

    if not verify_password(payload.current_password, current_user.hashed_password):
        record_login_attempt(db, current_user.username, ip, False)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le mot de passe actuel est incorrect")

    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le nouveau mot de passe doit être différent de l'ancien",
        )
    validate_password_strength(payload.new_password, current_user.username)

    current_user.hashed_password = hash_password(payload.new_password)
    current_user.must_change_password = False
    invalidate_sessions(db, current_user)
    record_login_attempt(db, current_user.username, ip, True)
    audit.record(db, "password_changed", current_user.id, "user", current_user.id, request)
    tokens = _token_response(db, current_user, request, response)
    db.commit()
    return tokens


@router.post("/forgot-password")
def forgot_password(payload: schemas.ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    allowed = limits.allow(db, f"forgot:{client_ip(request)}", FORGOT_MAX_PER_IP_HOUR, 3600)
    db.commit()
    if not allowed:
        return {"detail": GENERIC_FORGOT_DETAIL}

    identifier = payload.identifier.strip().lower()
    user = (
        db.query(User)
        .filter((func.lower(User.username) == identifier) | (func.lower(User.email) == identifier))
        .first()
    )

    audit.record(db, "password_reset_requested", user.id if user else None, "user",
                 user.id if user else None, request, {"identifier": identifier})

    if user and user.is_active and user.email:
        recent = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at > utils.now() - timedelta(hours=1),
            )
            .count()
        )
        if recent < RESET_MAX_PER_HOUR:
            raw = secrets.token_urlsafe(32)
            db.add(
                PasswordResetToken(
                    user_id=user.id,
                    token_hash=hash_token(raw),
                    created_at=utils.now(),
                    expires_at=utils.now() + timedelta(minutes=config.PASSWORD_RESET_EXPIRE_MINUTES),
                )
            )
            link = f"{config.PUBLIC_URL}/#/reinitialiser?token={raw}"
            body = (
                f"Bonjour {user.full_name},\n\n"
                "Une réinitialisation de votre mot de passe a été demandée pour l'application Fauché — Gestion Outillage.\n"
                f"Ce lien est valable {config.PASSWORD_RESET_EXPIRE_MINUTES} minutes et ne peut être utilisé qu'une fois :\n\n"
                f"{link}\n\n"
                "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message."
            )
            db.flush()
            ok, message = send_email(db, user.email, "Réinitialisation de votre mot de passe", body)
            if not ok:
                audit.record(db, "password_reset_email_failed", user.id, "user", user.id, request, {"reason": message})

    db.commit()
    return {"detail": GENERIC_FORGOT_DETAIL}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(payload: schemas.ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    invalid = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lien invalide ou expiré")
    row = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == hash_token(payload.token)).first()
    if row is None or row.used_at is not None or row.expires_at < utils.now():
        raise invalid

    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None or not user.is_active:
        raise invalid

    validate_password_strength(payload.new_password, user.username)

    row.used_at = utils.now()
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)).update(
        {"used_at": row.used_at}, synchronize_session=False)
    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    invalidate_sessions(db, user)
    audit.record(db, "password_reset_done", user.id, "user", user.id, request)
    db.commit()
    return {"detail": "Mot de passe mis à jour. Vous pouvez vous connecter."}


class MfaSetupIn(schemas.BaseModel):
    current_password: str = schemas.Field(max_length=1000)


class MfaCodeIn(schemas.BaseModel):
    code: str = schemas.Field(max_length=12)


class MfaDisableIn(MfaSetupIn, MfaCodeIn):
    pass


@router.post("/mfa/setup")
def mfa_setup(payload: MfaSetupIn, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.totp_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La double authentification est déjà active")
    ip = client_ip(request)
    check_login_allowed(db, current_user.username, ip)
    if not verify_password(payload.current_password, current_user.hashed_password):
        record_login_attempt(db, current_user.username, ip, False)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le mot de passe actuel est incorrect")
    secret = totp.new_secret()
    current_user.totp_secret = secrets_box.seal(secret)
    db.commit()
    return {"secret": secret, "uri": totp.uri(current_user.username, secret)}


@router.post("/mfa/enable", response_model=schemas.UserOut)
def mfa_enable(payload: MfaCodeIn, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    secret = secrets_box.unseal(current_user.totp_secret)
    step = totp.verify(secret, payload.code) if secret else None
    if step is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code de vérification incorrect")
    current_user.totp_enabled = True
    current_user.totp_last_step = step
    audit.record(db, "mfa_enabled", current_user.id, "user", current_user.id, request)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/mfa/disable", response_model=schemas.UserOut)
def mfa_disable(payload: MfaDisableIn, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ip = client_ip(request)
    check_login_allowed(db, current_user.username, ip)
    valid = verify_password(payload.current_password, current_user.hashed_password) and totp.verify(
        secrets_box.unseal(current_user.totp_secret) or "", payload.code) is not None
    if not valid:
        record_login_attempt(db, current_user.username, ip, False)
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mot de passe ou code incorrect")
    current_user.totp_enabled, current_user.totp_secret, current_user.totp_last_step = False, None, None
    audit.record(db, "mfa_disabled", current_user.id, "user", current_user.id, request)
    db.commit()
    db.refresh(current_user)
    return current_user
