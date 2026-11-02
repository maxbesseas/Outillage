from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, notify, utils
from ..auth import get_current_manager, get_current_user
from ..database import get_db
from ..history import log_state_change
from ..models import AgencyTool, AgencyToolStatus, ToolKind, User, UserRole
from ..models_p4 import AgencyTransfer
from ..agencies import require_agency

router = APIRouter(prefix="/agency-transfers", tags=["agency-transfers"])


class AgencyTransferIn(BaseModel):
    tool_id: int
    to_agency: str = Field(min_length=1)
    temporary: bool = False
    planned_return_date: Optional[datetime] = None
    comment: Optional[str] = None


class DecisionIn(BaseModel):
    comment: Optional[str] = None


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


def _view(db: Session, t: AgencyTransfer) -> dict:
    tool = db.query(AgencyTool).filter(AgencyTool.id == t.tool_id).first()
    return {"id": t.id, "tool_id": t.tool_id, "tool_name": tool.name if tool else "-", "tool_code": tool.unique_code if tool else "-",
            "from_agency": t.from_agency, "to_agency": t.to_agency, "requested_by_id": t.requested_by_id, "status": t.status,
            "temporary": t.temporary, "planned_return_date": t.planned_return_date, "decided_by_id": t.decided_by_id,
            "decided_at": t.decided_at, "returned_at": t.returned_at, "comment": t.comment, "created_at": t.created_at}


def _can_decide(user: User, to_agency: str) -> bool:
    return user.role == UserRole.admin or (user.role == UserRole.directeur_agence and user.agency_number == to_agency)


def _get(db: Session, transfer_id: int) -> AgencyTransfer:
    row = db.query(AgencyTransfer).filter(AgencyTransfer.id == transfer_id).first()
    if row is None:
        _fail("Transfert introuvable", status.HTTP_404_NOT_FOUND)
    return row


def _involved(user: User, t: AgencyTransfer) -> bool:
    return user.role == UserRole.admin or user.agency_number in (t.from_agency, t.to_agency)


@router.get("")
def list_transfers(direction: str = "all", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(AgencyTransfer)
    if current_user.role != UserRole.admin:
        agency = current_user.agency_number
        if direction == "incoming":
            query = query.filter(AgencyTransfer.to_agency == agency)
        elif direction == "outgoing":
            query = query.filter(AgencyTransfer.from_agency == agency)
        else:
            query = query.filter((AgencyTransfer.to_agency == agency) | (AgencyTransfer.from_agency == agency))
    return [_view(db, t) for t in query.order_by(AgencyTransfer.id.desc()).all()]


@router.post("", status_code=status.HTTP_201_CREATED)
def request_transfer(payload: AgencyTransferIn, request: Request, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_manager)):
    tool = db.query(AgencyTool).filter(AgencyTool.id == payload.tool_id).first()
    if tool is None:
        _fail("Outil introuvable", status.HTTP_404_NOT_FOUND)
    if current_user.role != UserRole.admin and tool.agency_number != current_user.agency_number:
        _fail("Cet outil appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    to_agency = require_agency(db, payload.to_agency)
    if to_agency == tool.agency_number:
        _fail("L'outil appartient déjà à cette agence")
    if tool.status != AgencyToolStatus.disponible:
        _fail("Seul un outil disponible peut être transféré")
    if db.query(AgencyTransfer).filter(AgencyTransfer.tool_id == tool.id, AgencyTransfer.status == "pending").first():
        _fail("Un transfert est déjà en attente pour cet outil")
    if payload.temporary and payload.planned_return_date is None:
        _fail("Indiquez une date de retour pour un prêt temporaire")

    row = AgencyTransfer(tool_id=tool.id, from_agency=tool.agency_number or "", to_agency=to_agency,
                         requested_by_id=current_user.id, temporary=payload.temporary,
                         planned_return_date=payload.planned_return_date, comment=payload.comment)
    db.add(row)
    db.flush()
    directors = [u for u in notify.agency_managers(db, to_agency) if u.role == UserRole.directeur_agence]
    notify.create_many(
        db, directors, "agency_transfer", f"Demande de transfert : {tool.name}",
        f"L'agence {row.from_agency} propose {tool.name} ({tool.unique_code}) "
        f"{'en prêt temporaire' if row.temporary else 'en transfert définitif'}.",
        entity_kind="agency_transfer", entity_id=row.id, link="#/transferts-agences", dedup_prefix=f"agency_transfer:{row.id}",
    )
    audit.record(db, "agency_transfer_requested", current_user.id, "agency_transfer", row.id, request,
                 {"tool": tool.unique_code, "to": to_agency})
    db.commit()
    return _view(db, row)


@router.post("/{transfer_id}/accept")
def accept(transfer_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = _get(db, transfer_id)
    if not _can_decide(current_user, row.to_agency):
        _fail("Seul le directeur de l'agence destinataire peut accepter", status.HTTP_403_FORBIDDEN)
    if row.status != "pending":
        _fail("Ce transfert n'est plus en attente")
    tool = db.query(AgencyTool).filter(AgencyTool.id == row.tool_id).first()
    if tool.status != AgencyToolStatus.disponible or tool.agency_number != row.from_agency:
        _fail("L'outil n'est plus disponible pour ce transfert")
    old_agency = tool.agency_number
    tool.home_agency = old_agency if row.temporary else None
    tool.agency_number = row.to_agency
    row.status, row.decided_by_id, row.decided_at = "accepted", current_user.id, utils.now()
    log_state_change(db, ToolKind.agency, tool.id, tool.state, tool.state, tool.status.value, tool.status.value,
                     current_user.id, "transfert entre agences", comment=f"{old_agency} → {row.to_agency}", force=True)
    notify.create(db, row.requested_by_id, "agency_transfer", f"Transfert accepté : {tool.name}",
                  f"{row.to_agency} a accepté {tool.name}.", link="#/transferts-agences", dedup_key=f"agency_transfer_done:{row.id}")
    audit.record(db, "agency_transfer_accepted", current_user.id, "agency_transfer", row.id, request,
                 {"tool": tool.unique_code, "from": old_agency, "to": row.to_agency})
    db.commit()
    return _view(db, row)


@router.post("/{transfer_id}/reject")
def reject(transfer_id: int, payload: DecisionIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = _get(db, transfer_id)
    if not _can_decide(current_user, row.to_agency):
        _fail("Seul le directeur de l'agence destinataire peut refuser", status.HTTP_403_FORBIDDEN)
    if row.status != "pending":
        _fail("Ce transfert n'est plus en attente")
    row.status, row.decided_by_id, row.decided_at = "rejected", current_user.id, utils.now()
    if payload.comment:
        row.comment = ((row.comment + " | ") if row.comment else "") + payload.comment
    notify.create(db, row.requested_by_id, "agency_transfer", "Transfert refusé", payload.comment or "Refusé par l'agence destinataire.",
                  link="#/transferts-agences", dedup_key=f"agency_transfer_done:{row.id}")
    db.commit()
    return _view(db, row)


@router.post("/{transfer_id}/cancel")
def cancel(transfer_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    row = _get(db, transfer_id)
    if row.requested_by_id != current_user.id and current_user.role != UserRole.admin:
        _fail("Seul le demandeur peut annuler", status.HTTP_403_FORBIDDEN)
    if row.status != "pending":
        _fail("Ce transfert n'est plus en attente")
    row.status = "cancelled"
    db.commit()
    return _view(db, row)


@router.post("/{transfer_id}/return")
def return_tool(transfer_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    row = _get(db, transfer_id)
    if row.status != "accepted" or not row.temporary:
        _fail("Seul un prêt temporaire accepté peut être rendu")
    if not _involved(current_user, row):
        _fail("Accès refusé", status.HTTP_403_FORBIDDEN)
    tool = db.query(AgencyTool).filter(AgencyTool.id == row.tool_id).first()
    if tool.status != AgencyToolStatus.disponible:
        _fail("L'outil doit être disponible pour être rendu à son agence d'origine")
    tool.agency_number, tool.home_agency = row.from_agency, None
    row.status, row.returned_at = "returned", utils.now()
    log_state_change(db, ToolKind.agency, tool.id, tool.state, tool.state, tool.status.value, tool.status.value,
                     current_user.id, "retour entre agences", comment=f"{row.to_agency} → {row.from_agency}", force=True)
    audit.record(db, "agency_transfer_returned", current_user.id, "agency_transfer", row.id, request, {"tool": tool.unique_code})
    db.commit()
    return _view(db, row)
