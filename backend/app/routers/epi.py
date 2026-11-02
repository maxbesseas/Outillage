import unicodedata
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import audit, controls, schemas
from ..agencies import require_agency
from ..auth import get_current_admin, get_current_manager, get_current_user
from ..database import get_db
from ..history import log_state_change
from ..models import Epi, ToolKind, User, UserRole
from .. import notify
from ..notifications import WORN_STATE_THRESHOLD, notify_magasinier
from ..utils import save_upload_file

router = APIRouter(prefix="/epi", tags=["epi"])


def _ascii_header_safe(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _scope_query(query, current_user: User):
    if current_user.role == UserRole.admin:
        return query
    return query.filter(Epi.agency_number == current_user.agency_number)


def _get_scoped_or_404(db: Session, epi_id: int, current_user: User) -> Epi:
    epi = db.query(Epi).filter(Epi.id == epi_id).first()
    if not epi:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="EPI introuvable")
    if current_user.role != UserRole.admin and epi.agency_number != current_user.agency_number:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cet EPI appartient à une autre agence")
    return epi


@router.get("", response_model=list[schemas.EpiOut])
def list_epi(
    response: Response,
    q: Optional[str] = None,
    type: Optional[str] = None,
    assigned_to_id: Optional[int] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _scope_query(db.query(Epi), current_user)
    if q:
        needle = q.strip().lower()
        query = query.filter(
            func.lower(func.coalesce(Epi.name, "")).contains(needle, autoescape=True)
            | func.lower(func.coalesce(Epi.unique_code, "")).contains(needle, autoescape=True)
            | func.lower(func.coalesce(Epi.brand, "")).contains(needle, autoescape=True)
        )
    if type:
        query = query.filter(Epi.type == type)
    if assigned_to_id is not None:
        query = query.filter(Epi.assigned_to_id == assigned_to_id)

    response.headers["X-Total-Count"] = str(query.count())
    query = query.order_by(Epi.name, Epi.id)
    if limit is not None:
        query = query.offset(max(offset, 0)).limit(max(1, min(limit, 500)))
    return query.all()


@router.get("/types", response_model=list[str])
def list_epi_types(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = _scope_query(db.query(Epi.type), current_user).filter(Epi.type.isnot(None)).distinct().all()
    return sorted(t for (t,) in rows if t)


@router.post("", response_model=schemas.EpiOut, status_code=status.HTTP_201_CREATED)
def create_epi(
    payload: schemas.EpiCreate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if db.query(Epi).filter(Epi.unique_code == payload.unique_code).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce code existe déjà")

    data = payload.model_dump()

    if current_user.role == UserRole.gars_chantier:
        data["assigned_to_id"] = current_user.id
        data["agency_number"] = current_user.agency_number
    elif current_user.role != UserRole.admin:
        if data.get("assigned_to_id"):
            assignee = db.query(User).filter(User.id == data["assigned_to_id"]).first()
            if not assignee or assignee.agency_number != current_user.agency_number:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La personne assignée doit appartenir à votre agence")
        data["agency_number"] = current_user.agency_number
    else:
        if not data.get("agency_number"):
            data["agency_number"] = current_user.agency_number
        else:
            data["agency_number"] = require_agency(db, data["agency_number"])

    epi = Epi(**data)
    db.add(epi)
    db.flush()

    log_state_change(
        db, ToolKind.epi, epi.id, None, epi.state, None, None,
        current_user.id, "création",
    )

    db.commit()
    db.refresh(epi)
    return epi


@router.get("/{epi_id}", response_model=schemas.EpiOut)
def get_epi(epi_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _get_scoped_or_404(db, epi_id, current_user)


@router.patch("/{epi_id}", response_model=schemas.EpiOut)
def update_epi(
    epi_id: int,
    payload: schemas.EpiUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_manager),
):
    epi = _get_scoped_or_404(db, epi_id, current_user)
    data = payload.model_dump(exclude_unset=True)

    old_state = epi.state
    for field, value in data.items():
        setattr(epi, field, value)

    if "state" in data and data["state"] != old_state:
        log_state_change(
            db, ToolKind.epi, epi.id, old_state, epi.state, None, None,
            current_user.id, "édition",
        )

    db.commit()
    db.refresh(epi)
    return epi


@router.post("/{epi_id}/control", response_model=schemas.EpiOut)
def control_epi(
    epi_id: int,
    payload: schemas.EpiControlUpdate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    epi = _get_scoped_or_404(db, epi_id, current_user)

    old_state = epi.state
    was_worn = old_state <= WORN_STATE_THRESHOLD

    epi.state = payload.state
    if payload.comment is not None:
        epi.comment = payload.comment
    epi.last_control_date = datetime.utcnow()
    controls.log_simple_inspection(db, "epi", epi, current_user, payload.comment)

    log_state_change(
        db, ToolKind.epi, epi.id, old_state, epi.state, None, None,
        current_user.id, "contrôle", comment=payload.comment,
    )

    db.commit()
    db.refresh(epi)

    is_worn = epi.state <= WORN_STATE_THRESHOLD
    if is_worn and not was_worn:
        notify.on_tool_problem(db, "epi", epi, current_user.id, "usé")
        ok, message = notify_magasinier(
            db,
            f"EPI usé : {epi.name}",
            f"L'EPI {epi.name} ({epi.unique_code}) est passé en état {epi.state}/5 lors d'un contrôle.\n"
            f"Commentaire : {payload.comment or '-'}",
        )
        db.commit()
        response.headers["X-Notification"] = "ok" if ok else _ascii_header_safe(message)
    else:
        response.headers["X-Notification"] = "ok"

    return epi


@router.post("/{epi_id}/photo", response_model=schemas.EpiOut)
def upload_epi_photo(
    epi_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    epi = _get_scoped_or_404(db, epi_id, current_user)
    epi.photo_path = save_upload_file(file, "epi")
    db.commit()
    db.refresh(epi)
    return epi


@router.delete("/{epi_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_epi(
    epi_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    epi = db.query(Epi).filter(Epi.id == epi_id).first()
    if not epi:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="EPI introuvable")
    audit.record(db, "epi_deleted", current_user.id, "epi", epi.id, request,
                 {"name": epi.name, "code": epi.unique_code})
    db.delete(epi)
    db.commit()
    return None
