from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .models import Agency


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
