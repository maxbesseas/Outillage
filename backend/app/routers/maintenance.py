from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, controls, maintenance, notify, reservations, utils
from .. import excel_export
from .. import finance as finance_mod
from ..agencies import agency_scope, check_same_agency, registry_name_for
from ..auth import get_current_manager, get_current_user
from ..database import get_db
from ..history import log_state_change
from ..models import (
    AgencyToolStatus,
    AgencyTool,
    Loan,
    LoanStatus,
    ToolKind,
    ToolStateReason,
    User,
    UserRole,
)
from ..models_p4 import ToolBlackout
from ..models_p6 import Site
from ..models_p5 import (
    ExitRequest,
    MaintenanceAttachment,
    MaintenanceComment,
    MaintenanceTicket,
    StockItem,
    StockMovement,
    ToolAccessory,
)
from ..utils import save_document, save_upload_file

tickets_router = APIRouter(prefix="/maintenance-tickets", tags=["maintenance"])
accessories_router = APIRouter(prefix="/agency-tools", tags=["accessories"])
exit_router = APIRouter(tags=["sortie-de-parc"])
stock_router = APIRouter(prefix="/stock", tags=["stock"])

EXIT_REASONS = ("vendu", "rebut", "donne", "vole", "perdu")
MAINT_ROLES = (UserRole.admin, UserRole.directeur_agence, UserRole.charge_affaires, UserRole.magasinier)


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


def _is_maint(user: User) -> bool:
    return user.role in MAINT_ROLES


# ------------------------------------------------------------------ tickets

class TicketIn(BaseModel):
    tool_kind: str
    tool_id: int
    category: str = "panne"
    severity: str = "moyenne"
    description: Optional[str] = Field(default=None, max_length=2000)
    photo_attached: bool = False


class TicketPatch(BaseModel):
    assigned_to_id: Optional[int] = None
    provider: Optional[str] = None
    warranty_claim: Optional[bool] = None
    warranty_case_number: Optional[str] = None
    sent_at: Optional[datetime] = None
    estimated_cost: Optional[float] = Field(default=None, ge=0)
    actual_cost: Optional[float] = Field(default=None, ge=0)
    parts: Optional[str] = None
    expected_return_date: Optional[datetime] = None
    description: Optional[str] = None
    severity: Optional[str] = None


class TransitionIn(BaseModel):
    status: str
    state_after: Optional[int] = Field(default=None, ge=0, le=5)
    resolution: Optional[str] = None
    comment: Optional[str] = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


def _tool_summary(db: Session, t: MaintenanceTicket) -> dict:
    tool = controls.get_tool(db, t.tool_kind, t.tool_id)
    if tool is None:
        return {"name": "(supprimé)", "code": None, "type": None, "warranty": {"active": False, "expires": None}}
    return {"name": tool.name, "code": tool.unique_code, "type": tool.type, "state": tool.state,
            "warranty": maintenance.warranty_info(tool)}


def _ticket_view(db: Session, t: MaintenanceTicket, names: dict, detail: bool = False) -> dict:
    data = {
        "id": t.id, "tool_kind": t.tool_kind, "tool_id": t.tool_id, "agency_number": t.agency_number,
        "opened_by_id": t.opened_by_id, "opened_by_name": names.get(t.opened_by_id), "opened_at": t.opened_at,
        "category": t.category, "severity": t.severity, "description": t.description, "status": t.status,
        "assigned_to_id": t.assigned_to_id, "assigned_to_name": names.get(t.assigned_to_id), "provider": t.provider,
        "warranty_claim": t.warranty_claim, "warranty_case_number": t.warranty_case_number, "sent_at": t.sent_at,
        "back_at": t.back_at, "estimated_cost": t.estimated_cost, "actual_cost": t.actual_cost, "parts": t.parts,
        "expected_return_date": t.expected_return_date, "closed_at": t.closed_at, "resolution": t.resolution,
        "auto_opened": t.auto_opened, "tool": _tool_summary(db, t),
        "age_days": ((t.closed_at or utils.now()) - t.opened_at).days if t.opened_at else None,
    }
    if detail:
        data["comments"] = [
            {"id": c.id, "user_name": names.get(c.user_id), "body": c.body, "kind": c.kind, "created_at": c.created_at}
            for c in db.query(MaintenanceComment).filter(MaintenanceComment.ticket_id == t.id).order_by(MaintenanceComment.id)
        ]
        data["attachments"] = [
            {"id": a.id, "path": a.path, "kind": a.kind, "filename": a.filename, "created_at": a.created_at}
            for a in db.query(MaintenanceAttachment).filter(MaintenanceAttachment.ticket_id == t.id)
        ]
    return data


def _ticket_or_404(db: Session, user: User, ticket_id: int, write: bool = False) -> MaintenanceTicket:
    ticket = db.query(MaintenanceTicket).filter(MaintenanceTicket.id == ticket_id).first()
    if ticket is None:
        _fail("Ticket introuvable", status.HTTP_404_NOT_FOUND)
    if user.role != UserRole.admin and ticket.agency_number != user.agency_number:
        _fail("Ce ticket appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    if not _is_maint(user) and (write or ticket.opened_by_id != user.id):
        _fail("Accès refusé à ce ticket", status.HTTP_403_FORBIDDEN)
    return ticket


def _apply_report(db: Session, kind: str, tool, category: str, user: User):
    """Effet immédiat d'un signalement sur l'outil (mêmes règles que les changements d'état existants)."""
    if kind == "agency":
        old = tool.status
        if category in ("perte", "vol"):
            tool.status, tool.loss_reason = AgencyToolStatus.hors_service, category
        elif category in ("casse", "panne", "usure", "accessoire_manquant") and tool.status == AgencyToolStatus.disponible:
            tool.status = AgencyToolStatus.reparation
        if tool.status != old:
            log_state_change(db, ToolKind.agency, tool.id, tool.state, tool.state, old.value, tool.status.value,
                             user.id, "signalement", comment=category)
    elif kind == "personal":
        old = tool.state_reason
        if category in ("perte", "vol"):
            tool.state_reason = ToolStateReason.perdu
        elif category in ("casse", "usure") and tool.state_reason == ToolStateReason.normal:
            tool.state_reason = ToolStateReason.endommage
        elif category in ("panne", "accessoire_manquant") and tool.state_reason == ToolStateReason.normal:
            tool.state_reason = ToolStateReason.en_reparation
        if tool.state_reason != old:
            log_state_change(db, ToolKind.personal, tool.id, tool.state, tool.state, old.value, tool.state_reason.value,
                             user.id, "signalement", comment=category)


@tickets_router.post("", status_code=status.HTTP_201_CREATED)
def report_problem(payload: TicketIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if payload.tool_kind not in controls.KINDS:
        _fail("Type d'outil invalide")
    if payload.category not in maintenance.CATEGORIES or payload.severity not in maintenance.SEVERITIES:
        _fail("Catégorie ou gravité invalide")
    tool = controls.get_tool(db, payload.tool_kind, payload.tool_id)
    if tool is None:
        _fail("Outil introuvable", status.HTTP_404_NOT_FOUND)
    if not controls.can_access(db, current_user, payload.tool_kind, tool):
        _fail("Accès refusé à cet outil", status.HTTP_403_FORBIDDEN)
    if payload.category in ("casse", "panne") and payload.severity in ("haute", "critique") and not payload.description:
        _fail("Décrivez le problème pour une gravité haute ou critique")

    ticket = MaintenanceTicket(
        tool_kind=payload.tool_kind, tool_id=tool.id, agency_number=maintenance.tool_agency(db, payload.tool_kind, tool),
        opened_by_id=current_user.id, opened_at=utils.now(), category=payload.category, severity=payload.severity,
        description=payload.description, status="ouvert", warranty_claim=maintenance.warranty_info(tool)["active"],
    )
    db.add(ticket)
    db.flush()
    maintenance.add_comment(db, ticket, current_user.id, "Signalement créé", "status")
    _apply_report(db, payload.tool_kind, tool, payload.category, current_user)
    notify.create_many(
        db, [u for u in notify.agency_managers(db, ticket.agency_number) if u.id != current_user.id], "maintenance_update",
        f"Signalement : {tool.name}", f"{payload.category} ({payload.severity}) — {payload.description or 'sans détail'}",
        severity="critical" if payload.severity == "critique" else "warning", entity_kind="ticket", entity_id=ticket.id,
        link="#/maintenance", dedup_prefix=f"ticket_open:{ticket.id}",
    )
    db.commit()
    return {**_ticket_view(db, ticket, _names(db)), "photo_required": False}


def _names(db: Session) -> dict:
    return {u.id: u.full_name for u in db.query(User).all()}


@tickets_router.get("")
def list_tickets(
    response: Response, status_filter: Optional[str] = None, open_only: bool = False, tool_kind: Optional[str] = None,
    tool_id: Optional[int] = None, limit: int = 100, offset: int = 0, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(MaintenanceTicket)
    if current_user.role != UserRole.admin:
        query = query.filter(MaintenanceTicket.agency_number == current_user.agency_number)
    if not _is_maint(current_user):
        query = query.filter(MaintenanceTicket.opened_by_id == current_user.id)
    if status_filter:
        query = query.filter(MaintenanceTicket.status == status_filter)
    if open_only:
        query = query.filter(MaintenanceTicket.status.in_(maintenance.OPEN_STATUSES))
    if tool_kind:
        query = query.filter(MaintenanceTicket.tool_kind == tool_kind)
    if tool_id is not None:
        query = query.filter(MaintenanceTicket.tool_id == tool_id)
    response.headers["X-Total-Count"] = str(query.count())
    rows = query.order_by(MaintenanceTicket.id.desc()).offset(max(offset, 0)).limit(max(1, min(limit, 500))).all()
    names = _names(db)
    return [_ticket_view(db, t, names) for t in rows]


@tickets_router.get("/stats")
def ticket_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    return maintenance.stats(db, agency_scope(current_user))


@tickets_router.get("/{ticket_id}")
def get_ticket(ticket_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ticket = _ticket_or_404(db, current_user, ticket_id)
    return _ticket_view(db, ticket, _names(db), detail=True)


@tickets_router.patch("/{ticket_id}")
def update_ticket(ticket_id: int, payload: TicketPatch, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_manager)):
    ticket = _ticket_or_404(db, current_user, ticket_id, write=True)
    data = payload.model_dump(exclude_unset=True)
    if "provider" in data and data["provider"] not in (None, *maintenance.PROVIDERS):
        _fail("Prestataire invalide")
    if "severity" in data and data["severity"] not in maintenance.SEVERITIES:
        _fail("Gravité invalide")
    check_same_agency(db, current_user, data.get("assigned_to_id"), ticket.agency_number)
    for key, value in data.items():
        setattr(ticket, key, value)
    if "expected_return_date" in data:
        maintenance._sync_blackout(db, ticket)
    maintenance.add_comment(db, ticket, current_user.id, "Ticket mis à jour : " + ", ".join(sorted(data)), "status")
    db.commit()
    return _ticket_view(db, ticket, _names(db), detail=True)


@tickets_router.post("/{ticket_id}/transition")
def transition_ticket(ticket_id: int, payload: TransitionIn, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_manager)):
    ticket = _ticket_or_404(db, current_user, ticket_id, write=True)
    try:
        maintenance.transition(db, ticket, payload.status, current_user, payload.state_after, payload.resolution, payload.comment)
    except ValueError as exc:
        db.rollback()
        _fail(str(exc))
    db.commit()
    return _ticket_view(db, ticket, _names(db), detail=True)


@tickets_router.post("/{ticket_id}/comments", status_code=status.HTTP_201_CREATED)
def comment_ticket(ticket_id: int, payload: CommentIn, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    ticket = _ticket_or_404(db, current_user, ticket_id)
    maintenance.add_comment(db, ticket, current_user.id, payload.body)
    db.commit()
    return {"ok": True}


@tickets_router.post("/{ticket_id}/attachments", status_code=status.HTTP_201_CREATED)
def attach_to_ticket(ticket_id: int, file: UploadFile, kind: str = "photo", db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    ticket = _ticket_or_404(db, current_user, ticket_id)
    if kind not in ("photo", "devis", "facture", "autre"):
        _fail("Type de pièce jointe invalide")
    if kind in ("devis", "facture") and not _is_maint(current_user):
        _fail("Réservé aux responsables", status.HTTP_403_FORBIDDEN)
    path = save_upload_file(file, "maintenance") if kind == "photo" else save_document(file, "maintenance")
    row = MaintenanceAttachment(ticket_id=ticket.id, path=path, kind=kind, filename=file.filename,
                                uploaded_by_id=current_user.id, created_at=utils.now())
    db.add(row)
    db.commit()
    return {"id": row.id, "path": path}


# ------------------------------------------------------------------ accessoires

class AccessoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=1, ge=1, le=999)
    required: bool = True
    note: Optional[str] = None


def _agency_tool(db: Session, user: User, tool_id: int) -> AgencyTool:
    tool = db.query(AgencyTool).filter(AgencyTool.id == tool_id).first()
    if tool is None:
        _fail("Outil introuvable", status.HTTP_404_NOT_FOUND)
    if user.role != UserRole.admin and tool.agency_number != user.agency_number:
        _fail("Cet outil appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    return tool


@accessories_router.get("/{tool_id}/accessories")
def list_accessories(tool_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _agency_tool(db, current_user, tool_id)
    return [{"id": a.id, "name": a.name, "quantity": a.quantity, "required": a.required, "note": a.note}
            for a in db.query(ToolAccessory).filter(ToolAccessory.tool_id == tool_id).order_by(ToolAccessory.name)]


@accessories_router.post("/{tool_id}/accessories", status_code=status.HTTP_201_CREATED)
def add_accessory(tool_id: int, payload: AccessoryIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    _agency_tool(db, current_user, tool_id)
    row = ToolAccessory(tool_id=tool_id, **payload.model_dump())
    db.add(row)
    db.commit()
    return {"id": row.id}


@accessories_router.delete("/{tool_id}/accessories/{accessory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_accessory(tool_id: int, accessory_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    _agency_tool(db, current_user, tool_id)
    db.query(ToolAccessory).filter(ToolAccessory.id == accessory_id, ToolAccessory.tool_id == tool_id).delete(synchronize_session=False)
    db.commit()
    return None


# ------------------------------------------------------------------ sortie de parc

class ExitIn(BaseModel):
    reason: str
    exit_date: Optional[datetime] = None
    note: Optional[str] = None
    residual_value: Optional[float] = Field(default=None, ge=0)


class DecisionIn(BaseModel):
    comment: Optional[str] = None


def _apply_exit(db: Session, tool: AgencyTool, reason: str, exit_date: Optional[datetime], note: Optional[str],
                residual: Optional[float], user: User):
    from ..appsettings import get_bool

    old_status = tool.status
    tool.status = AgencyToolStatus.sorti_du_parc
    tool.exit_reason, tool.exit_date = reason, exit_date or utils.now()
    tool.exit_note, tool.residual_value = note, residual
    tool.assigned_to_id = None
    previous_code = tool.unique_code
    if get_bool(db, "exit.release_code"):
        tool.exit_note = ((note + " | ") if note else "") + f"Ancien code : {tool.unique_code}"
        tool.unique_code = f"{tool.unique_code}~SORTI{tool.id}"
    future = db.query(Loan).filter(Loan.tool_id == tool.id,
                                   Loan.status.in_((LoanStatus.reserve, LoanStatus.attente_validation))).all()
    for loan in future:
        loan.status = LoanStatus.annule
        loan.comment_return = "Annulée : outil sorti du parc"
        reservations.log_event(db, loan, "cancelled", user.id, {"reason": "sortie de parc"})
        notify.create(db, loan.borrower_id, "generic", f"Réservation annulée : {tool.name}",
                      "L'outil est sorti du parc.", link="#/reservations", dedup_key=f"exit_cancel:{loan.id}")
    db.query(ToolBlackout).filter(ToolBlackout.tool_id == tool.id).delete(synchronize_session=False)
    log_state_change(db, ToolKind.agency, tool.id, tool.state, tool.state, old_status.value, tool.status.value,
                     user.id, "sortie de parc", comment=reason, force=True)
    excel_export.enqueue_sync(db, tool, "exit", registry_name_for(db, tool.agency_number), old_code=previous_code)
    if reason in ("vole", "perdu"):
        finance_mod.create_loss_record(db, tool, "vol" if reason == "vole" else "perte", user.id, tool.exit_date, note)


@exit_router.post("/agency-tools/{tool_id}/exit")
def request_exit(tool_id: int, payload: ExitIn, request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_manager)):
    from ..appsettings import get_bool

    tool = _agency_tool(db, current_user, tool_id)
    if payload.reason not in EXIT_REASONS:
        _fail("Motif de sortie invalide")
    if tool.status == AgencyToolStatus.sorti_du_parc:
        _fail("Cet outil est déjà sorti du parc")
    if tool.status == AgencyToolStatus.emprunte:
        _fail("L'outil est actuellement emprunté : attendez son retour")
    if db.query(ExitRequest).filter(ExitRequest.tool_id == tool.id, ExitRequest.status == "pending").first():
        _fail("Une demande de sortie est déjà en attente")

    direct = current_user.role in (UserRole.admin, UserRole.directeur_agence) or not get_bool(db, "exit.requires_approval")
    req = ExitRequest(tool_id=tool.id, requested_by_id=current_user.id, reason=payload.reason, exit_date=payload.exit_date,
                      note=payload.note, residual_value=payload.residual_value, created_at=utils.now())
    db.add(req)
    db.flush()
    if direct:
        req.status, req.decided_by_id, req.decided_at = "approved", current_user.id, utils.now()
        _apply_exit(db, tool, payload.reason, payload.exit_date, payload.note, payload.residual_value, current_user)
        audit.record(db, "tool_exit", current_user.id, "agency_tool", tool.id, request, {"reason": payload.reason})
    else:
        directors = [u for u in notify.agency_managers(db, tool.agency_number) if u.role == UserRole.directeur_agence]
        notify.create_many(db, directors, "maintenance_update", f"Sortie de parc à valider : {tool.name}",
                           f"{current_user.full_name} propose : {payload.reason}.", entity_kind="exit_request",
                           entity_id=req.id, link="#/maintenance", dedup_prefix=f"exit_request:{req.id}")
    db.commit()
    return {"id": req.id, "status": req.status}


@exit_router.get("/exit-requests")
def list_exit_requests(status_filter: str = "pending", db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    query = db.query(ExitRequest, AgencyTool).join(AgencyTool, AgencyTool.id == ExitRequest.tool_id)
    if current_user.role != UserRole.admin:
        query = query.filter(AgencyTool.agency_number == current_user.agency_number)
    query = query.filter(ExitRequest.status == status_filter)
    names = _names(db)
    return [{"id": r.id, "tool_id": t.id, "tool_name": t.name, "tool_code": t.unique_code, "reason": r.reason,
             "note": r.note, "residual_value": r.residual_value, "requested_by": names.get(r.requested_by_id),
             "status": r.status, "created_at": r.created_at} for r, t in query.order_by(ExitRequest.id.desc()).all()]


def _decide_exit(db: Session, user: User, request_id: int, approve: bool, http_request: Request):
    row = db.query(ExitRequest).filter(ExitRequest.id == request_id).first()
    if row is None:
        _fail("Demande introuvable", status.HTTP_404_NOT_FOUND)
    tool = db.query(AgencyTool).filter(AgencyTool.id == row.tool_id).first()
    if user.role not in (UserRole.admin, UserRole.directeur_agence) or (user.role != UserRole.admin and tool.agency_number != user.agency_number):
        _fail("Seul le directeur de l'agence ou l'administrateur peut décider", status.HTTP_403_FORBIDDEN)
    if row.status != "pending":
        _fail("Cette demande n'est plus en attente")
    if approve and tool.status == AgencyToolStatus.emprunte:
        _fail("L'outil est actuellement emprunté")
    row.status, row.decided_by_id, row.decided_at = ("approved" if approve else "rejected"), user.id, utils.now()
    if approve:
        _apply_exit(db, tool, row.reason, row.exit_date, row.note, row.residual_value, user)
        audit.record(db, "tool_exit", user.id, "agency_tool", tool.id, http_request, {"reason": row.reason})
    notify.create(db, row.requested_by_id, "maintenance_update", f"Sortie de parc {'validée' if approve else 'refusée'} : {tool.name}",
                  "", link="#/maintenance", dedup_key=f"exit_decision:{row.id}")
    db.commit()
    return {"id": row.id, "status": row.status}


@exit_router.post("/exit-requests/{request_id}/approve")
def approve_exit(request_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    return _decide_exit(db, current_user, request_id, True, request)


@exit_router.post("/exit-requests/{request_id}/reject")
def reject_exit(request_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    return _decide_exit(db, current_user, request_id, False, request)


# ------------------------------------------------------------------ stock

class StockItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    reference: Optional[str] = None
    unit: str = "pièce"
    quantity: float = Field(default=0, ge=0)
    threshold: float = Field(default=0, ge=0)
    location: Optional[str] = None


class StockItemPatch(BaseModel):
    name: Optional[str] = None
    reference: Optional[str] = None
    unit: Optional[str] = None
    threshold: Optional[float] = Field(default=None, ge=0)
    location: Optional[str] = None
    is_active: Optional[bool] = None


class MovementIn(BaseModel):
    kind: str
    quantity: float = Field(gt=-0.0000001)
    to_user_id: Optional[int] = None
    site: Optional[str] = None
    site_id: Optional[int] = None
    note: Optional[str] = None


def _stock_view(i: StockItem) -> dict:
    return {"id": i.id, "agency_number": i.agency_number, "name": i.name, "reference": i.reference, "unit": i.unit,
            "quantity": i.quantity, "threshold": i.threshold, "location": i.location, "is_active": i.is_active,
            "low": bool(i.threshold and i.quantity <= i.threshold)}


def _stock_item(db: Session, user: User, item_id: int) -> StockItem:
    item = db.query(StockItem).filter(StockItem.id == item_id).first()
    if item is None:
        _fail("Article introuvable", status.HTTP_404_NOT_FOUND)
    if user.role != UserRole.admin and item.agency_number != user.agency_number:
        _fail("Cet article appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    return item


@stock_router.get("/items")
def list_stock(low_only: bool = False, include_inactive: bool = False, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_manager)):
    query = db.query(StockItem)
    if current_user.role != UserRole.admin:
        query = query.filter(StockItem.agency_number == current_user.agency_number)
    if not include_inactive:
        query = query.filter(StockItem.is_active.is_(True))
    items = [_stock_view(i) for i in query.order_by(StockItem.name).all()]
    return [i for i in items if i["low"]] if low_only else items


@stock_router.post("/items", status_code=status.HTTP_201_CREATED)
def create_stock_item(payload: StockItemIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    item = StockItem(agency_number=current_user.agency_number, **payload.model_dump())
    db.add(item)
    db.flush()
    if payload.quantity:
        db.add(StockMovement(item_id=item.id, kind="entree", quantity=payload.quantity, balance_after=payload.quantity,
                             user_id=current_user.id, note="Stock initial", created_at=utils.now()))
    db.commit()
    return _stock_view(item)


@stock_router.patch("/items/{item_id}")
def update_stock_item(item_id: int, payload: StockItemPatch, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_manager)):
    item = _stock_item(db, current_user, item_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    return _stock_view(item)


@stock_router.post("/items/{item_id}/movements", status_code=status.HTTP_201_CREATED)
def add_movement(item_id: int, payload: MovementIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    item = _stock_item(db, current_user, item_id)
    if payload.kind not in ("entree", "sortie", "inventaire"):
        _fail("Type de mouvement invalide")
    check_same_agency(db, current_user, payload.to_user_id, item.agency_number)
    before = item.quantity
    if payload.kind == "entree":
        if payload.quantity <= 0:
            _fail("La quantité doit être positive")
        item.quantity += payload.quantity
    elif payload.kind == "sortie":
        if payload.quantity <= 0:
            _fail("La quantité doit être positive")
        if payload.quantity > item.quantity:
            _fail(f"Stock insuffisant ({item.quantity:g} {item.unit} disponible)")
        item.quantity -= payload.quantity
    else:
        item.quantity = payload.quantity
    site_name, site_ref = payload.site, None
    if payload.site_id is not None:
        site_row = db.query(Site).filter(Site.id == payload.site_id).first()
        if site_row is None or (site_row.agency_number or None) != (item.agency_number or None):
            _fail("Chantier introuvable dans cette agence")
        site_name, site_ref = site_row.name, site_row.id
    db.add(StockMovement(item_id=item.id, kind=payload.kind, quantity=payload.quantity, balance_after=item.quantity,
                         user_id=current_user.id, to_user_id=payload.to_user_id, site=site_name, site_id=site_ref,
                         note=payload.note, created_at=utils.now()))
    if item.threshold and before > item.threshold >= item.quantity:
        notify.create_many(db, notify.agency_managers(db, item.agency_number), "stock_low", f"Stock bas : {item.name}",
                           f"Il reste {item.quantity:g} {item.unit} (seuil {item.threshold:g}).", entity_kind="stock",
                           entity_id=item.id, link="#/stock",
                           dedup_prefix=f"stock_low:{item.id}:{utils.now().date().isoformat()}")
    db.commit()
    return _stock_view(item)


@stock_router.get("/items/{item_id}/movements")
def list_movements(item_id: int, limit: int = 100, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    _stock_item(db, current_user, item_id)
    names = _names(db)
    rows = db.query(StockMovement).filter(StockMovement.item_id == item_id).order_by(StockMovement.id.desc()).limit(max(1, min(limit, 500))).all()
    return [{"id": m.id, "kind": m.kind, "quantity": m.quantity, "balance_after": m.balance_after, "user_name": names.get(m.user_id),
             "to_user_name": names.get(m.to_user_id), "site": m.site, "note": m.note, "created_at": m.created_at} for m in rows]
