from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import audit, charter, schemas, utils
from ..auth import get_current_user_any
from ..database import get_db
from ..models import User
from ..models_security import CharterAcceptance

router = APIRouter(prefix="/charter", tags=["charte"])


class AcceptIn(BaseModel):
    version: int


@router.get("")
def read_charter(db: Session = Depends(get_db), current_user: User = Depends(get_current_user_any)):
    last = (
        db.query(CharterAcceptance).filter(CharterAcceptance.user_id == current_user.id)
        .order_by(CharterAcceptance.id.desc()).first()
    )
    return {**charter.content(db), "accepted_version": current_user.charter_version or 0, "accepted_at": last.accepted_at if last else None}


@router.post("/accept", response_model=schemas.UserOut)
def accept_charter(payload: AcceptIn, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_any)):
    if payload.version != charter.VERSION:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La charte a changé : relisez la dernière version")
    if (current_user.charter_version or 0) < charter.VERSION:
        db.add(CharterAcceptance(user_id=current_user.id, version=charter.VERSION, accepted_at=utils.now(), ip=utils.client_ip(request)))
        current_user.charter_version = charter.VERSION
        audit.record(db, "charter_accepted", current_user.id, "user", current_user.id, request, {"version": charter.VERSION})
        db.commit()
        db.refresh(current_user)
    return current_user
