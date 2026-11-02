import json
import uuid
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import appsettings, controls, documents, ics, notify, reservations, utils
from .. import sites as sites_mod
from ..auth import get_current_user
from ..database import get_db
from ..hierarchy import visible_user_ids
from ..history import log_state_change
from ..models import AgencyTool, AgencyToolStatus, Loan, LoanStatus, ToolKind, User, UserRole
from ..models_p4 import LoanEvent
from ..notifications import send_email
from ..reservations import ACTIVE, ReservationError
from ..utils import save_upload_file

router = APIRouter(prefix="/loans", tags=["loans"])

ACTIVE_STATUSES = (LoanStatus.reserve, LoanStatus.en_cours)  # rétrocompatibilité


# ------------------------------------------------------------------ schémas

class LoanCreateIn(BaseModel):
    tool_id: int
    site: Optional[str] = None
    site_id: Optional[int] = None
    comment: Optional[str] = None
    start_datetime: datetime
    end_datetime_planned: datetime
    state_before: Optional[int] = Field(default=None, ge=0, le=5)
    borrower_id: Optional[int] = None


class RecurringIn(BaseModel):
    tool_id: int
    start_datetime: datetime
    end_datetime_planned: datetime
    frequency: str = Field(pattern="^(daily|weekly)$")
    until: datetime
    site: Optional[str] = None
    site_id: Optional[int] = None
    comment: Optional[str] = None
    borrower_id: Optional[int] = None


class ReturnIn(BaseModel):
    state_after: int = Field(ge=0, le=5)
    comment_return: Optional[str] = None
    photo_attached: bool = False
    accessories_ok: Optional[bool] = None


class BatchReturnItem(ReturnIn):
    loan_id: int


class BatchReturnIn(BaseModel):
    returns: List[BatchReturnItem] = Field(min_length=1, max_length=100)


class ModifyIn(BaseModel):
    start_datetime: Optional[datetime] = None
    end_datetime_planned: Optional[datetime] = None
    site: Optional[str] = None
    comment: Optional[str] = None


class ExtendIn(BaseModel):
    new_end: datetime


class CheckoutIn(BaseModel):
    state_before: Optional[int] = Field(default=None, ge=0, le=5)


class DecisionIn(BaseModel):
    comment: Optional[str] = None


class SeriesShiftIn(BaseModel):
    delta_minutes: int = Field(ge=-100000, le=100000)


class SignatureIn(BaseModel):
    signature: dict
    signed_name: Optional[str] = Field(default=None, max_length=120)


class EmailIn(BaseModel):
    to: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------------------------------------------------------------------ utilitaires

def _view(loan: Loan) -> dict:
    return {
        "id": loan.id, "tool_id": loan.tool_id, "borrower_id": loan.borrower_id, "site": loan.site, "site_id": loan.site_id, "comment": loan.comment,
        "start_datetime": loan.start_datetime, "end_datetime_planned": loan.end_datetime_planned,
        "actual_return_datetime": loan.actual_return_datetime, "state_before": loan.state_before,
        "state_after": loan.state_after, "comment_return": loan.comment_return, "photo_return_path": loan.photo_return_path,
        "status": loan.status.value, "created_at": loan.created_at, "series_id": loan.series_id,
        "created_by_id": loan.created_by_id, "checked_out_at": loan.checked_out_at, "approved_by_id": loan.approved_by_id,
        "approval_comment": loan.approval_comment, "signed_at": loan.signed_at, "signed_name": loan.signed_name,
        "has_signature": bool(loan.signature_json),
    }


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


def _loan_or_404(db: Session, loan_id: int) -> Loan:
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if loan is None:
        _fail("Réservation introuvable", status.HTTP_404_NOT_FOUND)
    return loan


def _tool_of(db: Session, loan: Loan) -> AgencyTool:
    return db.query(AgencyTool).filter(AgencyTool.id == loan.tool_id).first()


def _can_manage(db: Session, user: User, loan: Loan) -> bool:
    if user.role == UserRole.admin or loan.borrower_id == user.id or loan.created_by_id == user.id:
        return True
    if user.role == UserRole.gars_chantier:
        return False
    ids = visible_user_ids(db, user)
    return ids is not None and loan.borrower_id in ids


def _ensure_manage(db: Session, user: User, loan: Loan):
    if not _can_manage(db, user, loan):
        _fail("Accès refusé à cette réservation", status.HTTP_403_FORBIDDEN)


def _ensure_view(db: Session, user: User, loan: Loan):
    if _can_manage(db, user, loan):
        return
    tool = _tool_of(db, loan)
    if tool is None or tool.agency_number != user.agency_number:
        _fail("Accès refusé à cette réservation", status.HTTP_403_FORBIDDEN)


def _resolve_borrower(db: Session, actor: User, borrower_id: Optional[int]) -> User:
    if borrower_id is None or borrower_id == actor.id:
        return actor
    if actor.role == UserRole.gars_chantier:
        _fail("Seul un responsable peut réserver pour un collègue", status.HTTP_403_FORBIDDEN)
    borrower = db.query(User).filter(User.id == borrower_id, User.is_active.is_(True)).first()
    if borrower is None:
        _fail("Emprunteur introuvable", status.HTTP_404_NOT_FOUND)
    ids = visible_user_ids(db, actor)
    if ids is not None and borrower.id not in ids:
        _fail("Cet emprunteur n'est pas dans votre équipe", status.HTTP_403_FORBIDDEN)
    return borrower


def _scoped_tool(db: Session, user: User, tool_id: int) -> AgencyTool:
    tool = db.query(AgencyTool).filter(AgencyTool.id == tool_id).first()
    if not tool:
        _fail("Outil introuvable", status.HTTP_404_NOT_FOUND)
    if user.role != UserRole.admin and tool.agency_number != user.agency_number:
        _fail("Cet outil appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    return tool


def _warning_header(response: Response, warns: List[str]):
    if warns:
        response.headers["X-Warning"] = "; ".join(warns).encode("ascii", "ignore").decode("ascii")


def _ticket_hook(db: Session, tool: AgencyTool, user: User, reason: str):
    try:
        from .. import maintenance
    except ImportError:
        return
    maintenance.open_ticket_if_needed(db, "agency", tool, user, reason)


def _finish_loan(db: Session, loan: Loan, user: User, payload: ReturnIn):
    if loan.status != LoanStatus.en_cours:
        _fail("Cette réservation n'est pas en cours (retirez d'abord l'outil ou annulez la réservation)")
    if payload.state_after <= 1 and appsettings.get_bool(db, "photo.required_on_bad_return") and not payload.photo_attached:
        _fail("Une photo est obligatoire pour un outil rendu en mauvais état")

    tool = _tool_of(db, loan)
    loan.status = LoanStatus.termine
    loan.actual_return_datetime = utils.now()
    loan.state_after = payload.state_after
    loan.comment_return = payload.comment_return
    old_state, old_status = tool.state, tool.status
    tool.state = payload.state_after
    if payload.state_after == 0:
        tool.status = AgencyToolStatus.hors_service
        tool.loss_reason = "casse"
    elif payload.state_after == 1:
        tool.status = AgencyToolStatus.reparation
    else:
        tool.status = AgencyToolStatus.disponible
    reservations.sync_children(db, tool)

    log_state_change(db, ToolKind.agency, tool.id, old_state, tool.state, old_status.value, tool.status.value,
                     user.id, "retour réservation", comment=payload.comment_return)
    reservations.log_event(db, loan, "returned", user.id, {"state_after": payload.state_after, "accessories_ok": payload.accessories_ok})

    if tool.status in (AgencyToolStatus.reparation, AgencyToolStatus.hors_service):
        notify.on_tool_problem(db, "agency", tool, user.id, tool.status.value)
        _ticket_hook(db, tool, user, tool.status.value)
    if payload.accessories_ok is False:
        try:
            from .. import maintenance

            maintenance.report_missing_accessories(db, tool, user, loan)
        except ImportError:
            pass
    db.flush()
    reservations.process_waitlist(db, tool.id)


# ------------------------------------------------------------------ liste

@router.get("")
def list_loans(
    response: Response,
    tool_id: Optional[int] = None,
    borrower_id: Optional[int] = None,
    scope: str = "mine",
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Loan)

    if scope == "team":
        ids = visible_user_ids(db, current_user)
        if ids is not None:
            query = query.filter(Loan.borrower_id.in_(ids))
    elif scope == "agency":
        if current_user.role != UserRole.admin:
            query = query.join(AgencyTool, Loan.tool_id == AgencyTool.id).filter(
                AgencyTool.agency_number == current_user.agency_number
            )
    else:
        query = query.filter(Loan.borrower_id == current_user.id)

    if tool_id is not None:
        query = query.filter(Loan.tool_id == tool_id)
    if borrower_id is not None and current_user.role == UserRole.admin:
        query = query.filter(Loan.borrower_id == borrower_id)

    response.headers["X-Total-Count"] = str(query.count())
    query = query.order_by(Loan.start_datetime.desc(), Loan.id.desc())
    if limit is not None:
        query = query.offset(max(offset, 0)).limit(max(1, min(limit, 500)))
    return [_view(l) for l in query.all()]


@router.get("/pending-approval")
def pending_approval(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if current_user.role == UserRole.gars_chantier:
        return []
    loans = db.query(Loan).filter(Loan.status == LoanStatus.attente_validation).order_by(Loan.start_datetime).all()
    names = {u.id: u.full_name for u in db.query(User).all()}
    result = []
    for loan in loans:
        borrower = db.query(User).filter(User.id == loan.borrower_id).first()
        tool = _tool_of(db, loan)
        if borrower and tool and (current_user.role == UserRole.admin or current_user in reservations.approvers_for(db, borrower)):
            result.append({**_view(loan), "tool_name": tool.name, "borrower_name": names.get(loan.borrower_id)})
    return result


# ------------------------------------------------------------------ création

@router.post("", status_code=status.HTTP_201_CREATED)
def create_loan(
    payload: LoanCreateIn,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tool = _scoped_tool(db, current_user, payload.tool_id)
    borrower = _resolve_borrower(db, current_user, payload.borrower_id)

    blocks, warns = controls.reservation_checks(db, tool, borrower)
    if blocks:
        _fail(" ; ".join(blocks))
    _warning_header(response, warns)

    site_obj = sites_mod.resolve_for_loan(db, tool, payload.site_id)
    try:
        loan = reservations.create_loan(db, tool, borrower, current_user, payload.start_datetime,
                                        payload.end_datetime_planned, site_obj.name if site_obj else payload.site,
                                        payload.comment, payload.state_before)
    except ReservationError as exc:
        db.rollback()
        _fail(str(exc))
    if site_obj:
        loan.site_id = site_obj.id
    db.commit()
    db.refresh(loan)
    return _view(loan)


@router.post("/recurring", status_code=status.HTTP_201_CREATED)
def create_recurring(
    payload: RecurringIn,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tool = _scoped_tool(db, current_user, payload.tool_id)
    borrower = _resolve_borrower(db, current_user, payload.borrower_id)
    if payload.end_datetime_planned <= payload.start_datetime:
        _fail("La date de fin doit être après la date de début")

    step = timedelta(days=1 if payload.frequency == "daily" else 7)
    duration = payload.end_datetime_planned - payload.start_datetime
    occurrences, current = [], payload.start_datetime
    while current <= payload.until:
        occurrences.append(current)
        current += step
        if len(occurrences) > reservations.MAX_SERIES:
            _fail(f"Une série ne peut pas dépasser {reservations.MAX_SERIES} occurrences")
    if not occurrences:
        _fail("La date de fin de série est antérieure au début")

    blocks, warns = controls.reservation_checks(db, tool, borrower)
    if blocks:
        _fail(" ; ".join(blocks))
    _warning_header(response, warns)

    series_id = uuid.uuid4().hex
    site_obj = sites_mod.resolve_for_loan(db, tool, payload.site_id)
    created = []
    for start in occurrences:
        try:
            created.append(reservations.create_loan(db, tool, borrower, current_user, start, start + duration,
                                                    site_obj.name if site_obj else payload.site, payload.comment, None, series_id))
            if site_obj:
                created[-1].site_id = site_obj.id
        except ReservationError as exc:
            db.rollback()
            _fail(f"Occurrence du {start:%d/%m/%Y %H:%M} impossible : {exc}. Aucune réservation n'a été créée.")
    db.commit()
    return {"series_id": series_id, "count": len(created), "loans": [_view(l) for l in created]}


@router.post("/batch-return")
def batch_return(payload: BatchReturnIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    results = []
    for item in payload.returns:
        try:
            loan = _loan_or_404(db, item.loan_id)
            _ensure_manage(db, current_user, loan)
            _finish_loan(db, loan, current_user, item)
            db.commit()
            results.append({"loan_id": item.loan_id, "ok": True})
        except HTTPException as exc:
            db.rollback()
            results.append({"loan_id": item.loan_id, "ok": False, "detail": exc.detail})
    return {"results": results, "done": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])}


# ------------------------------------------------------------------ séries

def _series_loans(db: Session, series_id: str) -> List[Loan]:
    return db.query(Loan).filter(Loan.series_id == series_id).order_by(Loan.start_datetime).all()


@router.get("/series/{series_id}")
def get_series(series_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    loans = _series_loans(db, series_id)
    if not loans:
        _fail("Série introuvable", status.HTTP_404_NOT_FOUND)
    _ensure_view(db, current_user, loans[0])
    return [_view(l) for l in loans]


@router.patch("/series/{series_id}")
def shift_series(series_id: str, payload: SeriesShiftIn, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    loans = _series_loans(db, series_id)
    if not loans:
        _fail("Série introuvable", status.HTTP_404_NOT_FOUND)
    _ensure_manage(db, current_user, loans[0])
    now = utils.now()
    movable = [l for l in loans if l.status in (LoanStatus.reserve, LoanStatus.attente_validation) and l.start_datetime > now]
    if not movable:
        _fail("Aucune occurrence future modifiable")
    delta = timedelta(minutes=payload.delta_minutes)
    ids = [l.id for l in loans]
    tool = _tool_of(db, movable[0])
    try:
        for loan in movable:
            new_start, new_end = loan.start_datetime + delta, loan.end_datetime_planned + delta
            if new_start <= now:
                raise ReservationError("Une occurrence serait déplacée dans le passé")
            reservations.check_slot(db, tool, new_start, new_end, exclude_ids=ids)
            reservations.check_duration(db, tool, new_start, new_end)
        for loan in movable:
            loan.start_datetime += delta
            loan.end_datetime_planned += delta
            reservations.log_event(db, loan, "modified", current_user.id, {"series_shift_minutes": payload.delta_minutes})
    except ReservationError as exc:
        db.rollback()
        _fail(str(exc))
    db.commit()
    return {"moved": len(movable)}


@router.delete("/series/{series_id}")
def cancel_series(series_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    loans = _series_loans(db, series_id)
    if not loans:
        _fail("Série introuvable", status.HTTP_404_NOT_FOUND)
    _ensure_manage(db, current_user, loans[0])
    count = 0
    for loan in loans:
        if loan.status in (LoanStatus.reserve, LoanStatus.attente_validation):
            loan.status = LoanStatus.annule
            reservations.log_event(db, loan, "cancelled", current_user.id, {"series": True})
            count += 1
    db.flush()
    tool = _tool_of(db, loans[0])
    if tool:
        reservations.process_waitlist(db, tool.id)
    db.commit()
    return {"cancelled": count}


# ------------------------------------------------------------------ une réservation

@router.get("/{loan_id}")
def get_loan(loan_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_view(db, current_user, loan)
    return _view(loan)


@router.get("/{loan_id}/events")
def loan_events(loan_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_view(db, current_user, loan)
    names = {u.id: u.full_name for u in db.query(User).all()}
    rows = db.query(LoanEvent).filter(LoanEvent.loan_id == loan.id).order_by(LoanEvent.id).all()
    return [{"id": e.id, "kind": e.kind, "user_id": e.user_id, "user_name": names.get(e.user_id),
             "detail": json.loads(e.detail) if e.detail else None, "created_at": e.created_at} for e in rows]


@router.get("/{loan_id}/alternatives")
def loan_alternatives(loan_id: int, end: Optional[datetime] = None, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_view(db, current_user, loan)
    tool = _tool_of(db, loan)
    start, finish = loan.start_datetime, end or loan.end_datetime_planned
    now = utils.now()
    result = []
    query = db.query(AgencyTool).filter(AgencyTool.agency_number == tool.agency_number, AgencyTool.id != tool.id,
                                        AgencyTool.type == tool.type)
    for other in query.order_by(AgencyTool.name).all():
        if reservations._tool_free_for(db, other, start, finish, now):
            result.append({"id": other.id, "name": other.name, "code": other.unique_code, "type": other.type})
    return result


@router.patch("/{loan_id}")
def modify_loan(loan_id: int, payload: ModifyIn, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_manage(db, current_user, loan)
    data = payload.model_dump(exclude_unset=True)
    tool = _tool_of(db, loan)
    before = {k: getattr(loan, k) for k in data}

    if loan.status in (LoanStatus.reserve, LoanStatus.attente_validation):
        new_start = data.get("start_datetime", loan.start_datetime)
        new_end = data.get("end_datetime_planned", loan.end_datetime_planned)
        if new_end <= new_start:
            _fail("La date de fin doit être après la date de début")
        try:
            if "start_datetime" in data or "end_datetime_planned" in data:
                reservations.check_slot(db, tool, new_start, new_end, exclude_ids=[loan.id])
                reservations.check_duration(db, tool, new_start, new_end)
        except ReservationError as exc:
            _fail(str(exc))
    elif loan.status == LoanStatus.en_cours:
        if "start_datetime" in data or "end_datetime_planned" in data:
            _fail("Pour une réservation en cours, utilisez la prolongation")
    else:
        _fail("Cette réservation n'est plus modifiable")

    for key, value in data.items():
        setattr(loan, key, value)
    reservations.log_event(db, loan, "modified", current_user.id,
                           {k: {"from": before[k], "to": data[k]} for k in data})
    db.commit()
    return _view(loan)


@router.post("/{loan_id}/extend")
def extend_loan(loan_id: int, payload: ExtendIn, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_manage(db, current_user, loan)
    if loan.status not in (LoanStatus.reserve, LoanStatus.en_cours):
        _fail("Cette réservation ne peut plus être prolongée")
    if payload.new_end <= loan.end_datetime_planned:
        _fail("La nouvelle date de fin doit être postérieure à la fin actuelle")
    tool = _tool_of(db, loan)
    try:
        reservations.check_slot(db, tool, loan.start_datetime, payload.new_end, exclude_ids=[loan.id])
        reservations.check_duration(db, tool, loan.start_datetime, payload.new_end)
    except ReservationError as exc:
        _fail(f"{exc}. Consultez les outils équivalents disponibles.")
    old_end = loan.end_datetime_planned
    loan.end_datetime_planned = payload.new_end
    reservations.log_event(db, loan, "extended", current_user.id, {"from": old_end, "to": payload.new_end})
    db.commit()
    return _view(loan)


@router.post("/{loan_id}/checkout")
def checkout_loan(loan_id: int, payload: CheckoutIn, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_manage(db, current_user, loan)
    if loan.status == LoanStatus.attente_validation:
        _fail("Cette réservation attend encore sa validation")
    if loan.status != LoanStatus.reserve:
        _fail("Cette réservation n'est pas à retirer")
    tool = _tool_of(db, loan)
    if tool.status != AgencyToolStatus.disponible:
        _fail("L'outil n'est pas disponible : il n'a pas encore été rendu ou est indisponible")
    now = utils.now()
    new_start = min(loan.start_datetime, now)
    try:
        reservations.check_slot(db, tool, new_start, loan.end_datetime_planned, exclude_ids=[loan.id])
    except ReservationError as exc:
        _fail(str(exc))
    loan.start_datetime = new_start
    loan.status = LoanStatus.en_cours
    loan.checked_out_at = now
    if payload.state_before is not None:
        loan.state_before = payload.state_before
    old = tool.status
    tool.status = AgencyToolStatus.emprunte
    reservations.sync_children(db, tool)
    log_state_change(db, ToolKind.agency, tool.id, tool.state, tool.state, old.value, tool.status.value,
                     current_user.id, "retrait réservation")
    reservations.log_event(db, loan, "checkout", current_user.id)
    db.commit()
    return _view(loan)


@router.post("/{loan_id}/return")
def return_loan(loan_id: int, payload: ReturnIn, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_manage(db, current_user, loan)
    _finish_loan(db, loan, current_user, payload)
    db.commit()
    return _view(loan)


@router.post("/{loan_id}/return/photo")
def upload_loan_return_photo(loan_id: int, file: UploadFile, db: Session = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_manage(db, current_user, loan)
    loan.photo_return_path = save_upload_file(file, "loan_returns")
    db.commit()
    return _view(loan)


@router.post("/{loan_id}/approve")
def approve_loan(loan_id: int, payload: DecisionIn, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    return _decide(db, current_user, loan_id, payload, approve=True)


@router.post("/{loan_id}/reject")
def reject_loan(loan_id: int, payload: DecisionIn, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    return _decide(db, current_user, loan_id, payload, approve=False)


def _decide(db: Session, user: User, loan_id: int, payload: DecisionIn, approve: bool):
    loan = _loan_or_404(db, loan_id)
    if loan.status != LoanStatus.attente_validation:
        _fail("Cette réservation n'attend pas de validation")
    borrower = db.query(User).filter(User.id == loan.borrower_id).first()
    allowed = user.role == UserRole.admin or user in reservations.approvers_for(db, borrower)
    if not allowed or loan.borrower_id == user.id:
        _fail("Vous ne pouvez pas valider cette réservation", status.HTTP_403_FORBIDDEN)
    tool = _tool_of(db, loan)
    if approve:
        try:
            reservations.check_slot(db, tool, loan.start_datetime, loan.end_datetime_planned, exclude_ids=[loan.id])
        except ReservationError as exc:
            _fail(str(exc))
    loan.status = LoanStatus.reserve if approve else LoanStatus.refuse
    loan.approved_by_id = user.id
    loan.approval_comment = payload.comment
    reservations.log_event(db, loan, "approved" if approve else "rejected", user.id, {"comment": payload.comment})
    notify.create(
        db, loan.borrower_id, "loan_approval",
        f"Réservation {'acceptée' if approve else 'refusée'} : {tool.name}",
        payload.comment or (f"Validée par {user.full_name}." if approve else f"Refusée par {user.full_name}."),
        entity_kind="loan", entity_id=loan.id, link="#/reservations", dedup_key=f"loan_decision:{loan.id}",
    )
    if not approve:
        db.flush()
        reservations.process_waitlist(db, tool.id)
    db.commit()
    return _view(loan)


@router.post("/{loan_id}/remind")
def remind_loan(loan_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    if loan.status != LoanStatus.en_cours:
        _fail("Cette réservation n'est pas en cours")
    if loan.borrower_id == current_user.id or current_user.role == UserRole.gars_chantier:
        _fail("Seul un responsable peut relancer un collègue", status.HTTP_403_FORBIDDEN)
    ids = visible_user_ids(db, current_user)
    if ids is not None and loan.borrower_id not in ids:
        _fail("Cet emprunteur n'est pas dans votre équipe", status.HTTP_403_FORBIDDEN)
    tool = _tool_of(db, loan)
    created = notify.create(
        db, loan.borrower_id, "loan_overdue", f"Rappel de {current_user.full_name} : {tool.name} à rendre",
        f"Retour prévu le {loan.end_datetime_planned:%d/%m/%Y %H:%M}.", entity_kind="loan", entity_id=loan.id,
        link="#/reservations", dedup_key=f"loan_remind:{loan.id}:{utils.now().date().isoformat()}",
    )
    if created is None:
        _fail("Un rappel a déjà été envoyé aujourd'hui")
    db.commit()
    return {"reminded": True}


@router.delete("/{loan_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_loan(loan_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_manage(db, current_user, loan)
    if loan.status not in (LoanStatus.reserve, LoanStatus.en_cours, LoanStatus.attente_validation):
        _fail("Cette réservation n'est pas active")

    was_out = loan.status == LoanStatus.en_cours
    loan.status = LoanStatus.annule
    reservations.log_event(db, loan, "cancelled", current_user.id)
    db.flush()
    tool = _tool_of(db, loan)
    if was_out:
        reservations.release_tool(db, tool, current_user.id, "annulation réservation")
    db.flush()
    reservations.process_waitlist(db, tool.id)
    db.commit()
    return None


# ------------------------------------------------------------------ documents et agenda

@router.post("/{loan_id}/signature")
def sign_loan(loan_id: int, payload: SignatureIn, db: Session = Depends(get_db),
              current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_manage(db, current_user, loan)
    try:
        signature = documents.validate_signature(payload.signature)
    except ValueError as exc:
        _fail(str(exc))
    loan.signature_json = json.dumps(signature)
    loan.signed_name = payload.signed_name
    loan.signed_at = utils.now()
    db.commit()
    return {"signed_at": loan.signed_at}


def _voucher_bytes(db: Session, loan: Loan) -> bytes:
    tool = _tool_of(db, loan)
    borrower = db.query(User).filter(User.id == loan.borrower_id).first()
    issuer = db.query(User).filter(User.id == (loan.created_by_id or loan.borrower_id)).first()
    return documents.voucher_pdf(loan, tool, borrower, issuer.full_name if issuer else None, tool.agency_number)


@router.get("/{loan_id}/voucher.pdf")
def loan_voucher(loan_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_view(db, current_user, loan)
    return Response(_voucher_bytes(db, loan), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="bon-de-sortie-{loan.id}.pdf"'})


@router.post("/{loan_id}/voucher/email")
def email_voucher(loan_id: int, payload: EmailIn, response: Response, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_manage(db, current_user, loan)
    tool = _tool_of(db, loan)
    ok, message = send_email(
        db, payload.to, f"Bon de sortie n°{loan.id} — {tool.name}",
        f"Bonjour,\n\nVeuillez trouver ci-joint le bon de sortie du matériel {tool.name} ({tool.unique_code}).\n",
        attachments=[(f"bon-de-sortie-{loan.id}.pdf", _voucher_bytes(db, loan), "application/pdf")],
    )
    response.headers["X-Notification"] = "ok" if ok else message.encode("ascii", "ignore").decode("ascii")
    return {"sent": ok, "detail": message}


@router.get("/{loan_id}/ics")
def loan_ics(loan_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    loan = _loan_or_404(db, loan_id)
    _ensure_view(db, current_user, loan)
    tool = _tool_of(db, loan)
    body = ics.calendar([ics.event(f"loan-{loan.id}@fauche", loan.start_datetime, loan.end_datetime_planned,
                                   f"Réservation : {tool.name}", loan.comment or "", loan.site or "")])
    return PlainTextResponse(body, media_type="text/calendar; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="reservation-{loan.id}.ics"'})
