import json
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from . import appsettings, notify, utils
from .history import log_state_change
from .models import AgencyTool, AgencyToolStatus, Loan, LoanStatus, ToolKind, User, UserRole
from .models_p4 import LoanEvent, ReservationRule, ToolBlackout, WaitlistEntry

IMMEDIATE_TOLERANCE = timedelta(minutes=15)
ACTIVE = (LoanStatus.reserve, LoanStatus.en_cours, LoanStatus.attente_validation)
UNAVAILABLE = (
    AgencyToolStatus.reparation,
    AgencyToolStatus.hors_service,
    AgencyToolStatus.dotation,
    AgencyToolStatus.sorti_du_parc,
)
MAX_SERIES = 60
PAST_TOLERANCE = timedelta(hours=1)
MAX_AHEAD = timedelta(days=730)
ABSOLUTE_MAX_DAYS = 365


class ReservationError(Exception):
    pass


def log_event(db: Session, loan: Loan, kind: str, user_id: Optional[int], detail: Optional[dict] = None):
    db.add(LoanEvent(loan_id=loan.id, kind=kind, user_id=user_id,
                     detail=json.dumps(detail, ensure_ascii=False, default=str) if detail else None, created_at=utils.now()))


def conflicting_loan(db: Session, tool_id: int, start: datetime, end: datetime, exclude_ids=()) -> Optional[Loan]:
    query = db.query(Loan).filter(
        Loan.tool_id == tool_id, Loan.status.in_(ACTIVE),
        Loan.start_datetime < end, Loan.end_datetime_planned > start,
    )
    if exclude_ids:
        query = query.filter(~Loan.id.in_(list(exclude_ids)))
    return query.first()


def blackout_conflict(db: Session, tool_id: int, start: datetime, end: datetime) -> Optional[ToolBlackout]:
    return (
        db.query(ToolBlackout)
        .filter(ToolBlackout.tool_id == tool_id, ToolBlackout.start_datetime < end, ToolBlackout.end_datetime > start)
        .first()
    )


def rules_for(db: Session, tool: AgencyTool) -> dict:
    rows = db.query(ReservationRule).filter(
        (ReservationRule.agency_tool_id == tool.id) | (ReservationRule.tool_type == tool.type)
    ).all()
    tool_level = next((r for r in rows if r.agency_tool_id == tool.id), None)
    type_level = next((r for r in rows if r.agency_tool_id is None and r.tool_type == tool.type), None)
    default_days = appsettings.get_int(db, "loan.max_days_default")
    approval = False
    max_days = default_days or None
    for row in (type_level, tool_level):  # l'outil précis l'emporte
        if row is not None:
            approval = row.requires_approval
            max_days = row.max_days or max_days
    return {"requires_approval": approval, "max_days": max_days}


def active_offer(db: Session, tool_id: int, start: datetime, end: datetime, exclude_entry_id: Optional[int] = None,
                 now: Optional[datetime] = None) -> Optional[WaitlistEntry]:
    now = now or utils.now()
    query = db.query(WaitlistEntry).filter(
        WaitlistEntry.tool_id == tool_id, WaitlistEntry.status == "offered", WaitlistEntry.offer_expires_at >= now,
        WaitlistEntry.start_datetime < end, WaitlistEntry.end_datetime > start,
    )
    if exclude_entry_id is not None:
        query = query.filter(WaitlistEntry.id != exclude_entry_id)
    return query.first()


def children_of(db: Session, tool_id: int) -> List[AgencyTool]:
    return db.query(AgencyTool).filter(AgencyTool.parent_tool_id == tool_id).all()


def sync_children(db: Session, tool: AgencyTool):
    """Les éléments d'un coffret suivent l'état d'emprunt de leur parent."""
    for kid in children_of(db, tool.id):
        if tool.status == AgencyToolStatus.emprunte and kid.status == AgencyToolStatus.disponible:
            kid.status = AgencyToolStatus.emprunte
        elif tool.status == AgencyToolStatus.disponible and kid.status == AgencyToolStatus.emprunte:
            if db.query(Loan).filter(Loan.tool_id == kid.id, Loan.status == LoanStatus.en_cours).first() is None:
                kid.status = AgencyToolStatus.disponible


def check_slot(db: Session, tool: AgencyTool, start: datetime, end: datetime, exclude_ids=(), offer_id: Optional[int] = None):
    other = conflicting_loan(db, tool.id, start, end, exclude_ids)
    if other is not None:
        raise ReservationError("Cet outil est déjà réservé sur ce créneau")
    if tool.parent_tool_id and conflicting_loan(db, tool.parent_tool_id, start, end, exclude_ids) is not None:
        raise ReservationError("Le coffret qui contient cet outil est déjà réservé sur ce créneau")
    for kid in children_of(db, tool.id):
        if conflicting_loan(db, kid.id, start, end, exclude_ids) is not None:
            raise ReservationError(f"Un élément du coffret est déjà réservé sur ce créneau : {kid.name}")
    if active_offer(db, tool.id, start, end, offer_id) is not None:
        raise ReservationError("Ce créneau est proposé à une personne en liste d'attente")
    blackout = blackout_conflict(db, tool.id, start, end)
    if blackout is not None:
        raise ReservationError(f"Outil indisponible sur ce créneau ({blackout.reason})")


def check_dates(actor: User, start: datetime, end: datetime, now: datetime):
    """Le passé reste ouvert à l'administrateur, pour régulariser un oubli."""
    if actor.role != UserRole.admin and start < now - PAST_TOLERANCE:
        raise ReservationError("La date de début est déjà passée")
    if start > now + MAX_AHEAD:
        raise ReservationError("La réservation est trop éloignée dans le temps (2 ans maximum)")


def check_duration(db: Session, tool: AgencyTool, start: datetime, end: datetime):
    if (end - start) > timedelta(days=ABSOLUTE_MAX_DAYS):
        raise ReservationError(f"Durée trop longue : {ABSOLUTE_MAX_DAYS} jours maximum")
    max_days = rules_for(db, tool)["max_days"]
    if max_days and (end - start) > timedelta(days=max_days):
        raise ReservationError(f"Durée maximale de réservation dépassée ({max_days} jour(s) pour ce type d'outil)")


def preflight(db: Session, tool: AgencyTool, start: datetime, end: datetime, now: Optional[datetime] = None) -> Optional[str]:
    """Message d'erreur si la réservation serait refusée, sinon None (aucune écriture)."""
    now = now or utils.now()
    if end <= start:
        return "La date de fin doit être après la date de début"
    if tool.status in UNAVAILABLE:
        return "Cet outil n'est pas disponible"
    if start <= now + IMMEDIATE_TOLERANCE and tool.status != AgencyToolStatus.disponible:
        return "Cet outil n'est pas disponible"
    try:
        check_slot(db, tool, start, end)
        check_duration(db, tool, start, end)
    except ReservationError as exc:
        return str(exc)
    return None


def approvers_for(db: Session, borrower: User) -> List[User]:
    managers = notify.chain_managers(db, borrower) + notify.agency_managers(db, borrower.agency_number)
    seen, result = set(), []
    for m in managers:
        if m.id != borrower.id and m.id not in seen:
            seen.add(m.id)
            result.append(m)
    return result


def create_loan(
    db: Session,
    tool: AgencyTool,
    borrower: User,
    actor: User,
    start: datetime,
    end: datetime,
    site: Optional[str] = None,
    comment: Optional[str] = None,
    state_before: Optional[int] = None,
    series_id: Optional[str] = None,
    now: Optional[datetime] = None,
    offer_id: Optional[int] = None,
) -> Loan:
    now = now or utils.now()
    if end <= start:
        raise ReservationError("La date de fin doit être après la date de début")
    check_dates(actor, start, end, now)
    if tool.status in UNAVAILABLE:
        raise ReservationError("Cet outil n'est pas disponible")
    immediate = start <= now + IMMEDIATE_TOLERANCE
    if immediate and tool.status != AgencyToolStatus.disponible:
        raise ReservationError("Cet outil n'est pas disponible")
    check_slot(db, tool, start, end, offer_id=offer_id)
    check_duration(db, tool, start, end)

    needs_approval = rules_for(db, tool)["requires_approval"] and not _can_self_approve(db, actor, borrower)
    status = LoanStatus.attente_validation if needs_approval else (LoanStatus.en_cours if immediate else LoanStatus.reserve)
    loan = Loan(
        tool_id=tool.id, borrower_id=borrower.id, created_by_id=actor.id, site=site, comment=comment,
        start_datetime=start, end_datetime_planned=end, series_id=series_id,
        state_before=state_before if state_before is not None else tool.state, status=status,
        checked_out_at=now if status == LoanStatus.en_cours else None,
    )
    db.add(loan)
    db.flush()

    if immediate and any(k.status != AgencyToolStatus.disponible for k in children_of(db, tool.id)):
        raise ReservationError("Un élément du coffret n'est pas disponible")

    if status == LoanStatus.en_cours:
        old_status = tool.status
        tool.status = AgencyToolStatus.emprunte
        sync_children(db, tool)
        log_state_change(db, ToolKind.agency, tool.id, tool.state, tool.state, old_status.value, tool.status.value,
                         actor.id, "réservation")
    log_event(db, loan, "created", actor.id, {"status": status.value, "on_behalf": borrower.id != actor.id})

    if needs_approval:
        notify.create_many(
            db, approvers_for(db, borrower), "loan_approval", f"Réservation à valider : {tool.name}",
            f"{borrower.full_name} demande {tool.name} du {start:%d/%m/%Y %H:%M} au {end:%d/%m/%Y %H:%M}.",
            entity_kind="loan", entity_id=loan.id, link="#/validations", dedup_prefix=f"loan_approval:{loan.id}",
        )
    return loan


def _can_self_approve(db: Session, actor: User, borrower: User) -> bool:
    """Les responsables sont eux-mêmes validateurs : leurs réservations (ou celles qu'ils font pour l'équipe) sont acceptées."""
    return actor.role != UserRole.gars_chantier


def release_tool(db: Session, tool: AgencyTool, actor_id: Optional[int], source: str):
    """Remet l'outil à disposition si plus aucun prêt en cours ne le retient."""
    still_out = db.query(Loan).filter(Loan.tool_id == tool.id, Loan.status == LoanStatus.en_cours).first()
    if still_out is None and tool.status in (AgencyToolStatus.emprunte, AgencyToolStatus.reserve):
        old = tool.status
        tool.status = AgencyToolStatus.disponible
        sync_children(db, tool)
        log_state_change(db, ToolKind.agency, tool.id, tool.state, tool.state, old.value, tool.status.value, actor_id, source)


# ------------------------------------------------------------------ liste d'attente

def _tool_free_for(db: Session, tool: AgencyTool, start: datetime, end: datetime, now: datetime) -> bool:
    if tool.status in UNAVAILABLE:
        return False
    if start <= now + IMMEDIATE_TOLERANCE and tool.status != AgencyToolStatus.disponible:
        return False
    return (
        conflicting_loan(db, tool.id, start, end) is None
        and blackout_conflict(db, tool.id, start, end) is None
        and active_offer(db, tool.id, start, end, now=now) is None
    )


def process_waitlist(db: Session, tool_id: int, now: Optional[datetime] = None) -> Optional[WaitlistEntry]:
    now = now or utils.now()
    tool = db.query(AgencyTool).filter(AgencyTool.id == tool_id).first()
    if tool is None:
        return None
    entries = (
        db.query(WaitlistEntry).filter(WaitlistEntry.tool_id == tool_id, WaitlistEntry.status.in_(("waiting", "offered")))
        .order_by(WaitlistEntry.created_at, WaitlistEntry.id).all()
    )
    hours = appsettings.get_int(db, "loan.waitlist_offer_hours")
    for entry in entries:
        if entry.status == "offered" and entry.offer_expires_at and entry.offer_expires_at >= now:
            return None  # une offre est déjà en cours pour cet outil
    for entry in entries:
        if entry.status != "waiting":
            continue
        if entry.end_datetime <= now:
            entry.status = "expired"
            continue
        if _tool_free_for(db, tool, entry.start_datetime, entry.end_datetime, now):
            entry.status = "offered"
            entry.offered_at = now
            entry.offer_expires_at = now + timedelta(hours=hours)
            notify.create(
                db, entry.user_id, "waitlist_available", f"Disponible : {tool.name}",
                f"L'outil que vous attendiez est libre du {entry.start_datetime:%d/%m/%Y %H:%M} au "
                f"{entry.end_datetime:%d/%m/%Y %H:%M}. Confirmez avant le {entry.offer_expires_at:%d/%m/%Y %H:%M}.",
                entity_kind="waitlist", entity_id=entry.id, link="#/reservations", dedup_key=f"waitlist:{entry.id}",
            )
            return entry
    return None


def expire_offers(db: Session, now: Optional[datetime] = None) -> int:
    now = now or utils.now()
    expired = db.query(WaitlistEntry).filter(WaitlistEntry.status == "offered", WaitlistEntry.offer_expires_at < now).all()
    tools = set()
    for entry in expired:
        entry.status = "expired"
        tools.add(entry.tool_id)
    db.flush()
    for tool_id in tools:
        process_waitlist(db, tool_id, now)
    return len(expired)


def expire_no_shows(db: Session, now: Optional[datetime] = None) -> int:
    now = now or utils.now()
    hours = appsettings.get_int(db, "loan.no_show_hours")
    limit = now - timedelta(hours=hours)
    loans = (
        db.query(Loan).filter(Loan.status.in_((LoanStatus.reserve, LoanStatus.attente_validation)), Loan.start_datetime < limit)
        .all()
    )
    count = 0
    for loan in loans:
        pending = loan.status == LoanStatus.attente_validation
        loan.status = LoanStatus.annule
        loan.comment_return = "Annulée automatiquement : " + ("non validée à temps" if pending else "non retirée")
        log_event(db, loan, "no_show", None, {"pending_approval": pending})
        tool = db.query(AgencyTool).filter(AgencyTool.id == loan.tool_id).first()
        if tool:
            notify.create(
                db, loan.borrower_id, "no_show", f"Réservation annulée : {tool.name}", loan.comment_return,
                entity_kind="loan", entity_id=loan.id, link="#/reservations", dedup_key=f"no_show:{loan.id}",
            )
            process_waitlist(db, tool.id, now)
        count += 1
    return count
