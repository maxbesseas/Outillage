from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .models import Agency, User, UserRole


def agency_scope(user: User, requested: Optional[str] = None) -> Optional[str]:
    """Agence à filtrer. None (toutes) est réservé à l'admin : un autre compte sans agence obtient "", qui ne correspond à rien."""
    if user.role == UserRole.admin:
        return requested or None
    return user.agency_number or ""


def check_same_agency(db: Session, actor: User, target_id: Optional[int], agency: Optional[str]):
    """Refuse de rattacher une personne d'une autre agence ; l'administrateur n'est pas limité."""
    if target_id is None or actor.role == UserRole.admin:
        return
    target = db.query(User).filter(User.id == target_id).first()
    if target is None or (target.agency_number != agency and target.role != UserRole.admin):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cette personne n'appartient pas à l'agence concernée")


def require_agency(db: Session, name: Optional[str]) -> Optional[str]:
    if name is None or name == "":
        return None
    agency = db.query(Agency).filter(Agency.name == name).first()
    if agency is None or not agency.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Agence inconnue ou inactive : {name}")
    return agency.name


def registry_name_for(db: Session, agency_number: Optional[str]) -> Optional[str]:
    if not agency_number:
        return None
    agency = db.query(Agency).filter(Agency.name == agency_number).first()
    if agency is None:
        return None
    return agency.excel_registry_name or None
