from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import audit, schemas, secrets_box
from ..auth import get_current_admin
from ..database import get_db
from ..notifications import get_settings
from ..models import User

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=schemas.SettingsOut)
def read_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    settings = get_settings(db)
    db.commit()
    return schemas.SettingsOut(
        magasinier_email=settings.magasinier_email,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_username=settings.smtp_username,
        smtp_password_set=bool(settings.smtp_password),
        smtp_use_tls=settings.smtp_use_tls,
        smtp_from_email=settings.smtp_from_email,
    )


@router.patch("", response_model=schemas.SettingsOut)
def update_settings(
    payload: schemas.SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    settings = get_settings(db)
    data = payload.model_dump(exclude_unset=True)

    if "smtp_password" in data and not data["smtp_password"]:
        del data["smtp_password"]

    if data.get("smtp_password"):
        data["smtp_password"] = secrets_box.seal(data["smtp_password"])
    for field, value in data.items():
        setattr(settings, field, value)

    audit.record(db, "settings_updated", current_user.id, "settings", 1, request, {"fields": sorted(data.keys())})
    db.commit()
    db.refresh(settings)

    return schemas.SettingsOut(
        magasinier_email=settings.magasinier_email,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_username=settings.smtp_username,
        smtp_password_set=bool(settings.smtp_password),
        smtp_use_tls=settings.smtp_use_tls,
        smtp_from_email=settings.smtp_from_email,
    )
