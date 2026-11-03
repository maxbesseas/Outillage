from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from . import controls, notify, reservations, utils
from .history import log_state_change
from .models import AgencyTool, AgencyToolStatus, ToolKind, ToolStateReason, User
from .models_p4 import ToolBlackout
from .models_p5 import MaintenanceComment, MaintenanceTicket, ToolAccessory

OPEN_STATUSES = ("ouvert", "diagnostic", "en_reparation", "attente_piece")
CLOSED_STATUSES = ("repare", "irreparable", "clos")
CATEGORIES = ("casse", "panne", "accessoire_manquant", "usure", "perte", "vol", "autre")
SEVERITIES = ("faible", "moyenne", "haute", "critique")
PROVIDERS = ("interne", "fournisseur", "sav")

TRANSITIONS = {
    "ouvert": ("diagnostic", "en_reparation", "attente_piece", "repare", "irreparable"),
    "diagnostic": ("en_reparation", "attente_piece", "repare", "irreparable"),
    "en_reparation": ("attente_piece", "repare", "irreparable"),
    "attente_piece": ("en_reparation", "repare", "irreparable"),
    "repare": ("clos",),
    "irreparable": ("clos",),
    "clos": (),
}


def tool_agency(db: Session, kind: str, tool) -> Optional[str]:
    return controls.tool_agency(db, kind, tool)


def warranty_info(tool, now: Optional[datetime] = None) -> dict:
    now = now or utils.now()
    expiry = getattr(tool, "warranty_expiration_date", None)
    return {"active": bool(expiry and expiry >= now), "expires": expiry}


def add_comment(db: Session, ticket: MaintenanceTicket, user_id: Optional[int], body: str, kind: str = "comment"):
    db.add(MaintenanceComment(ticket_id=ticket.id, user_id=user_id, body=body, kind=kind, created_at=utils.now()))


def find_open_ticket(db: Session, kind: str, tool_id: int) -> Optional[MaintenanceTicket]:
    return (
        db.query(MaintenanceTicket)
        .filter(MaintenanceTicket.tool_kind == kind, MaintenanceTicket.tool_id == tool_id,
                MaintenanceTicket.status.in_(OPEN_STATUSES))
        .order_by(MaintenanceTicket.id.desc()).first()
    )


def open_ticket_if_needed(db: Session, kind: str, tool, user: Optional[User], reason: str,
                          category: Optional[str] = None, description: Optional[str] = None) -> MaintenanceTicket:
    existing = find_open_ticket(db, kind, tool.id)
    if existing is not None:
        return existing
    hors_service = reason in ("hors_service", "perdu", "vole")
    ticket = MaintenanceTicket(
        tool_kind=kind, tool_id=tool.id, agency_number=tool_agency(db, kind, tool), opened_by_id=user.id if user else None,
        opened_at=utils.now(), category=category or ("casse" if hors_service else "panne"),
        severity="haute" if hors_service else "moyenne",
        description=description or f"Ouvert automatiquement : {tool.name} est passé en « {reason} ».",
        status="ouvert", auto_opened=True,
        warranty_claim=warranty_info(tool)["active"],
    )
    db.add(ticket)
    db.flush()
    add_comment(db, ticket, user.id if user else None, "Ticket ouvert automatiquement", "status")
    notify.create_many(
        db, notify.agency_managers(db, ticket.agency_number), "maintenance_update", f"Nouveau ticket : {tool.name}",
        ticket.description, entity_kind="ticket", entity_id=ticket.id, link="#/maintenance",
        dedup_prefix=f"ticket_open:{ticket.id}",
    )
    return ticket


def report_missing_accessories(db: Session, tool: AgencyTool, user: User, loan) -> Optional[MaintenanceTicket]:
    expected = db.query(ToolAccessory).filter(ToolAccessory.tool_id == tool.id, ToolAccessory.required.is_(True)).all()
    listing = ", ".join(f"{a.name} ×{a.quantity}" for a in expected) or "accessoires non listés"
    ticket = MaintenanceTicket(
        tool_kind="agency", tool_id=tool.id, agency_number=tool.agency_number, opened_by_id=user.id, opened_at=utils.now(),
        category="accessoire_manquant", severity="faible",
        description=f"Retour incomplet de la réservation n°{loan.id}. À vérifier : {listing}.",
        status="ouvert", auto_opened=True,
    )
    db.add(ticket)
    db.flush()
    add_comment(db, ticket, user.id, "Retour déclaré incomplet", "status")
    notify.create_many(
        db, notify.agency_managers(db, tool.agency_number), "maintenance_update", f"Accessoire manquant : {tool.name}",
        ticket.description, entity_kind="ticket", entity_id=ticket.id, link="#/maintenance",
        dedup_prefix=f"ticket_open:{ticket.id}",
    )
    return ticket


def _sync_blackout(db: Session, ticket: MaintenanceTicket):
    ref = f"ticket:{ticket.id}"
    db.query(ToolBlackout).filter(ToolBlackout.ref == ref).delete(synchronize_session=False)
    if ticket.tool_kind == "agency" and ticket.status in OPEN_STATUSES and ticket.expected_return_date:
        start = utils.now()
        if ticket.expected_return_date > start:
            db.add(ToolBlackout(tool_id=ticket.tool_id, start_datetime=start, end_datetime=ticket.expected_return_date,
                                reason="maintenance", note=f"Ticket n°{ticket.id}", source="auto", ref=ref))


def apply_tool_effect(db: Session, ticket: MaintenanceTicket, new_status: str, user: User, state_after: Optional[int]):
    tool = controls.get_tool(db, ticket.tool_kind, ticket.tool_id)
    if tool is None:
        return
    if ticket.tool_kind == "agency":
        old_state, old_status = tool.state, tool.status
        if new_status in ("diagnostic", "en_reparation", "attente_piece", "ouvert"):
            if tool.status in (AgencyToolStatus.disponible,):
                tool.status = AgencyToolStatus.reparation
        elif new_status == "repare":
            tool.status = AgencyToolStatus.disponible
            tool.loss_reason = None
            tool.state = state_after if state_after is not None else max(tool.state, 4)
            tool.last_control_date = utils.now()
            controls.log_simple_inspection(db, "agency", tool, user, f"Contrôle après réparation (ticket n°{ticket.id})")
        elif new_status == "irreparable":
            tool.status = AgencyToolStatus.hors_service
            tool.loss_reason = tool.loss_reason or None
        log_state_change(db, ToolKind.agency, tool.id, old_state, tool.state, old_status.value, tool.status.value,
                         user.id, "maintenance", comment=f"Ticket n°{ticket.id} : {new_status}")
        db.flush()
        if tool.status == AgencyToolStatus.disponible:
            reservations.process_waitlist(db, tool.id)
    elif ticket.tool_kind == "personal":
        old_state, old_reason = tool.state, tool.state_reason
        if new_status == "repare":
            tool.state_reason = ToolStateReason.normal
            tool.state = state_after if state_after is not None else max(tool.state, 4)
            tool.last_control_date = utils.now()
        elif new_status in ("diagnostic", "en_reparation", "attente_piece", "ouvert"):
            if tool.state_reason == ToolStateReason.normal:
                tool.state_reason = ToolStateReason.en_reparation
        log_state_change(db, ToolKind.personal, tool.id, old_state, tool.state, old_reason.value, tool.state_reason.value,
                         user.id, "maintenance", comment=f"Ticket n°{ticket.id} : {new_status}")
    elif ticket.tool_kind == "epi" and new_status == "repare" and state_after is not None:
        old_state = tool.state
        tool.state, tool.last_control_date = state_after, utils.now()
        log_state_change(db, ToolKind.epi, tool.id, old_state, tool.state, None, None, user.id, "maintenance",
                         comment=f"Ticket n°{ticket.id} : {new_status}")


def transition(db: Session, ticket: MaintenanceTicket, new_status: str, user: User, state_after: Optional[int] = None,
               resolution: Optional[str] = None, comment: Optional[str] = None):
    if new_status not in TRANSITIONS.get(ticket.status, ()):
        raise ValueError(f"Passage impossible de « {ticket.status} » à « {new_status} »")
    now = utils.now()
    old = ticket.status
    ticket.status = new_status
    if new_status in ("repare", "irreparable"):
        ticket.back_at = ticket.back_at or now
        if resolution:
            ticket.resolution = resolution
        if new_status == "irreparable":
            tool = controls.get_tool(db, ticket.tool_kind, ticket.tool_id)
            if tool is not None:
                notify.create_many(
                    db, notify.agency_managers(db, ticket.agency_number), "maintenance_update",
                    f"Irréparable : {tool.name}", "Pensez à proposer la sortie de parc (mise au rebut).",
                    entity_kind="ticket", entity_id=ticket.id, link="#/maintenance",
                    dedup_prefix=f"ticket_irreparable:{ticket.id}",
                )
    if new_status == "clos":
        ticket.closed_at = now
    apply_tool_effect(db, ticket, new_status, user, state_after)
    _sync_blackout(db, ticket)
    add_comment(db, ticket, user.id, f"{old} → {new_status}" + (f" : {comment}" if comment else ""), "status")
    if ticket.opened_by_id and ticket.opened_by_id != user.id:
        notify.create(db, ticket.opened_by_id, "maintenance_update", f"Ticket n°{ticket.id} : {new_status}",
                      comment or "Le statut de votre signalement a changé.", entity_kind="ticket", entity_id=ticket.id,
                      link="#/maintenance", dedup_key=f"ticket_status:{ticket.id}:{new_status}")


def stats(db: Session, agency: Optional[str]) -> dict:
    query = db.query(MaintenanceTicket)
    if agency is not None:
        query = query.filter(MaintenanceTicket.agency_number == agency)
    tickets = query.all()
    repaired = [t for t in tickets if t.status in ("repare", "clos") and t.back_at]
    durations = [(t.back_at - t.opened_at).total_seconds() / 86400 for t in repaired if t.opened_at]
    by_type, cost = {}, 0.0
    for t in tickets:
        tool = controls.get_tool(db, t.tool_kind, t.tool_id)
        label = (tool.type if tool and tool.type else "Non renseigné")
        by_type[label] = by_type.get(label, 0) + 1
        cost += t.actual_cost or 0
    return {
        "open": sum(1 for t in tickets if t.status in OPEN_STATUSES),
        "total": len(tickets),
        "avg_repair_days": round(sum(durations) / len(durations), 1) if durations else None,
        "total_cost": round(cost, 2),
        "tickets_by_type": by_type,
    }
