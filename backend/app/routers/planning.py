from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, controls, reservations, utils
from ..auth import get_current_manager, get_current_user
from ..database import get_db
from ..models import AgencyTool, Loan, LoanStatus, User, UserRole
from ..models_p4 import ReservationRule, ToolBlackout, ToolKit, ToolKitItem, WaitlistEntry
from .loans import _resolve_borrower, _view, _warning_header

kits_router = APIRouter(prefix="/kits", tags=["kits"])
waitlist_router = APIRouter(prefix="/waitlist", tags=["waitlist"])
blackouts_router = APIRouter(prefix="/blackouts", tags=["blackouts"])
rules_router = APIRouter(prefix="/reservation-rules", tags=["reservation-rules"])

BLACKOUT_REASONS = ("maintenance", "etalonnage", "controle", "autre")


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


def _tool(db: Session, user: User, tool_id: int) -> AgencyTool:
    tool = db.query(AgencyTool).filter(AgencyTool.id == tool_id).first()
    if tool is None:
        _fail("Outil introuvable", status.HTTP_404_NOT_FOUND)
    if user.role != UserRole.admin and tool.agency_number != user.agency_number:
        _fail("Cet outil appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    return tool


# ------------------------------------------------------------------ kits

class KitIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = None
    tool_ids: List[int] = Field(min_length=1, max_length=50)


class KitPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    tool_ids: Optional[List[int]] = Field(default=None, min_length=1, max_length=50)


class KitReserveIn(BaseModel):
    start_datetime: datetime
    end_datetime_planned: datetime
    site: Optional[str] = None
    comment: Optional[str] = None
    borrower_id: Optional[int] = None


def _kit_view(db: Session, kit: ToolKit) -> dict:
    tools = (
        db.query(AgencyTool).join(ToolKitItem, ToolKitItem.tool_id == AgencyTool.id)
        .filter(ToolKitItem.kit_id == kit.id).order_by(AgencyTool.name).all()
    )
    return {"id": kit.id, "name": kit.name, "description": kit.description, "agency_number": kit.agency_number,
            "tools": [{"id": t.id, "name": t.name, "code": t.unique_code, "status": t.status.value} for t in tools]}


def _kit_or_404(db: Session, user: User, kit_id: int) -> ToolKit:
    kit = db.query(ToolKit).filter(ToolKit.id == kit_id).first()
    if kit is None:
        _fail("Kit introuvable", status.HTTP_404_NOT_FOUND)
    if user.role != UserRole.admin and kit.agency_number != user.agency_number:
        _fail("Ce kit appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    return kit


@kits_router.get("")
def list_kits(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(ToolKit)
    if current_user.role != UserRole.admin:
        query = query.filter(ToolKit.agency_number == current_user.agency_number)
    return [_kit_view(db, k) for k in query.order_by(ToolKit.name).all()]


@kits_router.post("", status_code=status.HTTP_201_CREATED)
def create_kit(payload: KitIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    tools = [_tool(db, current_user, tid) for tid in dict.fromkeys(payload.tool_ids)]
    agencies = {t.agency_number for t in tools}
    if len(agencies) != 1:
        _fail("Tous les outils d'un kit doivent appartenir à la même agence")
    kit = ToolKit(name=payload.name, description=payload.description, agency_number=agencies.pop())
    db.add(kit)
    db.flush()
    for tool in tools:
        db.add(ToolKitItem(kit_id=kit.id, tool_id=tool.id))
    db.commit()
    return _kit_view(db, kit)


@kits_router.patch("/{kit_id}")
def update_kit(kit_id: int, payload: KitPatch, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    kit = _kit_or_404(db, current_user, kit_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        kit.name = data["name"]
    if "description" in data:
        kit.description = data["description"]
    if data.get("tool_ids"):
        tools = [_tool(db, current_user, tid) for tid in dict.fromkeys(data["tool_ids"])]
        if {t.agency_number for t in tools} != {kit.agency_number}:
            _fail("Tous les outils d'un kit doivent appartenir à la même agence")
        db.query(ToolKitItem).filter(ToolKitItem.kit_id == kit.id).delete(synchronize_session=False)
        for tool in tools:
            db.add(ToolKitItem(kit_id=kit.id, tool_id=tool.id))
    db.commit()
    return _kit_view(db, kit)


@kits_router.delete("/{kit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kit(kit_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    kit = _kit_or_404(db, current_user, kit_id)
    db.query(ToolKitItem).filter(ToolKitItem.kit_id == kit.id).delete(synchronize_session=False)
    db.delete(kit)
    db.commit()
    return None


@kits_router.post("/{kit_id}/reserve", status_code=status.HTTP_201_CREATED)
def reserve_kit(kit_id: int, payload: KitReserveIn, response: Response, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    kit = _kit_or_404(db, current_user, kit_id)
    borrower = _resolve_borrower(db, current_user, payload.borrower_id)
    tools = db.query(AgencyTool).join(ToolKitItem, ToolKitItem.tool_id == AgencyTool.id).filter(ToolKitItem.kit_id == kit.id).all()
    if not tools:
        _fail("Ce kit est vide")

    problems, warns = [], []
    now = utils.now()
    for tool in tools:
        message = reservations.preflight(db, tool, payload.start_datetime, payload.end_datetime_planned, now)
        blocks, tool_warns = controls.reservation_checks(db, tool, borrower)
        message = message or (" ; ".join(blocks) if blocks else None)
        if message:
            problems.append(f"{tool.name} ({tool.unique_code}) : {message}")
        warns.extend(f"{tool.name}: {w}" for w in tool_warns)
    if problems:
        _fail("Kit indisponible, aucune réservation créée — " + " | ".join(problems))
    _warning_header(response, warns)

    import uuid

    group = f"kit-{uuid.uuid4().hex}"
    loans = []
    try:
        for tool in tools:
            loans.append(reservations.create_loan(db, tool, borrower, current_user, payload.start_datetime,
                                                  payload.end_datetime_planned, payload.site, payload.comment, None, group))
    except reservations.ReservationError as exc:
        db.rollback()
        _fail(str(exc))
    db.commit()
    return {"series_id": group, "count": len(loans), "loans": [_view(l) for l in loans]}


# ------------------------------------------------------------------ liste d'attente

class WaitlistIn(BaseModel):
    tool_id: int
    start_datetime: datetime
    end_datetime: datetime
    site: Optional[str] = None


def _entry_view(db: Session, e: WaitlistEntry) -> dict:
    tool = db.query(AgencyTool).filter(AgencyTool.id == e.tool_id).first()
    return {"id": e.id, "tool_id": e.tool_id, "tool_name": tool.name if tool else "-", "user_id": e.user_id,
            "start_datetime": e.start_datetime, "end_datetime": e.end_datetime, "site": e.site, "status": e.status,
            "offer_expires_at": e.offer_expires_at, "loan_id": e.loan_id, "created_at": e.created_at}


@waitlist_router.post("", status_code=status.HTTP_201_CREATED)
def join_waitlist(payload: WaitlistIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tool = _tool(db, current_user, payload.tool_id)
    now = utils.now()
    if payload.end_datetime <= payload.start_datetime or payload.end_datetime <= now:
        _fail("Créneau invalide")
    if reservations._tool_free_for(db, tool, payload.start_datetime, payload.end_datetime, now):
        _fail("L'outil est disponible sur ce créneau : réservez-le directement")
    duplicate = db.query(WaitlistEntry).filter(
        WaitlistEntry.tool_id == tool.id, WaitlistEntry.user_id == current_user.id,
        WaitlistEntry.status.in_(("waiting", "offered")),
        WaitlistEntry.start_datetime < payload.end_datetime, WaitlistEntry.end_datetime > payload.start_datetime,
    ).first()
    if duplicate:
        _fail("Vous êtes déjà en liste d'attente sur ce créneau")
    entry = WaitlistEntry(tool_id=tool.id, user_id=current_user.id, start_datetime=payload.start_datetime,
                          end_datetime=payload.end_datetime, site=payload.site, created_at=now)
    db.add(entry)
    db.commit()
    return _entry_view(db, entry)


@waitlist_router.get("")
def list_waitlist(scope: str = "mine", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(WaitlistEntry).filter(WaitlistEntry.status.in_(("waiting", "offered")))
    if scope == "agency" and current_user.role != UserRole.gars_chantier:
        if current_user.role != UserRole.admin:
            query = query.join(AgencyTool, AgencyTool.id == WaitlistEntry.tool_id).filter(
                AgencyTool.agency_number == current_user.agency_number)
    else:
        query = query.filter(WaitlistEntry.user_id == current_user.id)
    return [_entry_view(db, e) for e in query.order_by(WaitlistEntry.created_at).all()]


@waitlist_router.post("/{entry_id}/accept", status_code=status.HTTP_201_CREATED)
def accept_offer(entry_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == entry_id, WaitlistEntry.user_id == current_user.id).first()
    if entry is None:
        _fail("Entrée introuvable", status.HTTP_404_NOT_FOUND)
    now = utils.now()
    if entry.status != "offered" or entry.offer_expires_at is None or entry.offer_expires_at < now:
        _fail("Cette offre n'est plus valable")
    tool = _tool(db, current_user, entry.tool_id)
    try:
        loan = reservations.create_loan(db, tool, current_user, current_user, entry.start_datetime, entry.end_datetime,
                                        entry.site, None, None, offer_id=entry.id)
    except reservations.ReservationError as exc:
        entry.status = "waiting"
        db.commit()
        _fail(f"{exc}. Vous restez en liste d'attente.")
    entry.status, entry.loan_id = "fulfilled", loan.id
    db.commit()
    return _view(loan)


@waitlist_router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def leave_waitlist(entry_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.id == entry_id).first()
    if entry is None:
        _fail("Entrée introuvable", status.HTTP_404_NOT_FOUND)
    if entry.user_id != current_user.id and current_user.role not in (UserRole.admin, UserRole.directeur_agence, UserRole.charge_affaires, UserRole.magasinier):
        _fail("Accès refusé", status.HTTP_403_FORBIDDEN)
    tool = _tool(db, current_user, entry.tool_id)
    was_offered = entry.status == "offered"
    entry.status = "cancelled"
    db.flush()
    if was_offered:
        reservations.process_waitlist(db, tool.id)
    db.commit()
    return None


# ------------------------------------------------------------------ indisponibilités

class BlackoutIn(BaseModel):
    tool_id: int
    start_datetime: datetime
    end_datetime: datetime
    reason: str = "autre"
    note: Optional[str] = None


def _blackout_view(b: ToolBlackout) -> dict:
    return {"id": b.id, "tool_id": b.tool_id, "start_datetime": b.start_datetime, "end_datetime": b.end_datetime,
            "reason": b.reason, "note": b.note, "source": b.source}


@blackouts_router.get("")
def list_blackouts(tool_id: Optional[int] = None, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
                   db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(ToolBlackout).join(AgencyTool, AgencyTool.id == ToolBlackout.tool_id)
    if current_user.role != UserRole.admin:
        query = query.filter(AgencyTool.agency_number == current_user.agency_number)
    if tool_id is not None:
        query = query.filter(ToolBlackout.tool_id == tool_id)
    if date_from:
        query = query.filter(ToolBlackout.end_datetime > date_from)
    if date_to:
        query = query.filter(ToolBlackout.start_datetime < date_to)
    return [_blackout_view(b) for b in query.order_by(ToolBlackout.start_datetime).all()]


@blackouts_router.post("", status_code=status.HTTP_201_CREATED)
def create_blackout(payload: BlackoutIn, request: Request, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_manager)):
    tool = _tool(db, current_user, payload.tool_id)
    if payload.end_datetime <= payload.start_datetime:
        _fail("La date de fin doit être après la date de début")
    if payload.reason not in BLACKOUT_REASONS:
        _fail("Motif invalide")
    clash = reservations.conflicting_loan(db, tool.id, payload.start_datetime, payload.end_datetime)
    if clash is not None:
        _fail(f"Une réservation existe déjà sur cette période (n°{clash.id}) : annulez-la ou déplacez-la d'abord")
    row = ToolBlackout(tool_id=tool.id, start_datetime=payload.start_datetime, end_datetime=payload.end_datetime,
                       reason=payload.reason, note=payload.note, source="manual", created_by_id=current_user.id)
    db.add(row)
    db.flush()
    audit.record(db, "blackout_created", current_user.id, "agency_tool", tool.id, request, {"reason": payload.reason})
    db.commit()
    return _blackout_view(row)


@blackouts_router.delete("/{blackout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_blackout(blackout_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    row = db.query(ToolBlackout).filter(ToolBlackout.id == blackout_id).first()
    if row is None:
        _fail("Indisponibilité introuvable", status.HTTP_404_NOT_FOUND)
    tool = _tool(db, current_user, row.tool_id)
    db.delete(row)
    db.flush()
    reservations.process_waitlist(db, tool.id)
    db.commit()
    return None


# ------------------------------------------------------------------ règles de réservation

class RuleIn(BaseModel):
    tool_type: Optional[str] = None
    agency_tool_id: Optional[int] = None
    requires_approval: bool = False
    max_days: Optional[int] = Field(default=None, ge=1, le=365)


@rules_router.get("")
def list_rules(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [{"id": r.id, "tool_type": r.tool_type, "agency_tool_id": r.agency_tool_id,
             "requires_approval": r.requires_approval, "max_days": r.max_days} for r in db.query(ReservationRule).all()]


@rules_router.post("", status_code=status.HTTP_201_CREATED)
def create_rule(payload: RuleIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    if bool(payload.tool_type) == bool(payload.agency_tool_id):
        _fail("Indiquer un type d'outil ou un outil précis")
    if payload.tool_type and current_user.role != UserRole.admin:
        _fail("Une règle par type est réservée à l'administrateur", status.HTTP_403_FORBIDDEN)
    if payload.agency_tool_id:
        _tool(db, current_user, payload.agency_tool_id)
    existing = db.query(ReservationRule).filter(
        ReservationRule.tool_type == payload.tool_type, ReservationRule.agency_tool_id == payload.agency_tool_id).first()
    row = existing or ReservationRule(tool_type=payload.tool_type, agency_tool_id=payload.agency_tool_id)
    row.requires_approval, row.max_days = payload.requires_approval, payload.max_days
    if existing is None:
        db.add(row)
    db.commit()
    return {"id": row.id}


@rules_router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    row = db.query(ReservationRule).filter(ReservationRule.id == rule_id).first()
    if row is None:
        _fail("Règle introuvable", status.HTTP_404_NOT_FOUND)
    if row.tool_type and current_user.role != UserRole.admin:
        _fail("Réservé à l'administrateur", status.HTTP_403_FORBIDDEN)
    if row.agency_tool_id:
        _tool(db, current_user, row.agency_tool_id)
    db.delete(row)
    db.commit()
    return None
