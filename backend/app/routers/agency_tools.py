import unicodedata
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import audit, controls, excel_export, schemas
from ..agencies import check_same_agency, registry_name_for, require_agency
from ..auth import get_current_admin, get_current_manager, get_current_user
from ..database import get_db
from ..excel_export import export_agency_tools_workbook, sync_new_agency_tool
from ..history import log_state_change
from ..models import AgencyLossReason, AgencyTool, AgencyToolStatus, ToolKind, User, UserRole
from .. import notify
from ..notifications import notify_magasinier
from ..utils import save_upload_file

router = APIRouter(prefix="/agency-tools", tags=["agency-tools"])


def _ascii_header_safe(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _tool_view(tool: AgencyTool, user: User) -> schemas.AgencyToolOut:
    """Les montants restent réservés aux responsables, comme l'écran Finances."""
    view = schemas.AgencyToolOut.model_validate(tool)
    if user.role == UserRole.gars_chantier:
        return view.model_copy(update={"purchase_price": None, "daily_rate": None, "residual_value": None})
    return view


def _scope_query(query, current_user: User):
    if current_user.role == UserRole.admin:
        return query
    return query.filter(AgencyTool.agency_number == current_user.agency_number)


def _get_scoped_or_404(db: Session, tool_id: int, current_user: User) -> AgencyTool:
    tool = db.query(AgencyTool).filter(AgencyTool.id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outil introuvable")
    if current_user.role != UserRole.admin and tool.agency_number != current_user.agency_number:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cet outil appartient à une autre agence")
    return tool


@router.get("", response_model=list[schemas.AgencyToolOut])
def list_agency_tools(
    response: Response,
    q: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[AgencyToolStatus] = None,
    loss_reason: Optional[AgencyLossReason] = None,
    include_exited: bool = False,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _scope_query(db.query(AgencyTool), current_user)
    if not include_exited and status != AgencyToolStatus.sorti_du_parc:
        query = query.filter(AgencyTool.status != AgencyToolStatus.sorti_du_parc)
    if q:
        needle = q.strip().lower()
        query = query.filter(
            func.lower(func.coalesce(AgencyTool.name, "")).contains(needle, autoescape=True)
            | func.lower(func.coalesce(AgencyTool.unique_code, "")).contains(needle, autoescape=True)
            | func.lower(func.coalesce(AgencyTool.serial_number, "")).contains(needle, autoescape=True)
            | func.lower(func.coalesce(AgencyTool.description, "")).contains(needle, autoescape=True)
            | func.lower(func.coalesce(AgencyTool.brand, "")).contains(needle, autoescape=True)
        )
    if type:
        query = query.filter(AgencyTool.type == type)
    if status:
        query = query.filter(AgencyTool.status == status)
    if loss_reason:
        query = query.filter(AgencyTool.loss_reason == loss_reason)

    response.headers["X-Total-Count"] = str(query.count())
    query = query.order_by(AgencyTool.name, AgencyTool.id)
    if limit is not None:
        query = query.offset(max(offset, 0)).limit(max(1, min(limit, 500)))
    return [_tool_view(t, current_user) for t in query.all()]


@router.get("/types", response_model=list[str])
def list_agency_tool_types(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        _scope_query(db.query(AgencyTool.type), current_user)
        .filter(AgencyTool.type.isnot(None), AgencyTool.status != AgencyToolStatus.sorti_du_parc)
        .distinct().all()
    )
    return sorted(t for (t,) in rows if t)


@router.get("/financial-summary", response_model=schemas.FinancialSummary)
def financial_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    tools = _scope_query(db.query(AgencyTool), current_user).all()

    total_value = sum(t.purchase_price or 0 for t in tools)
    total_count = len(tools)

    by_type_map = {}
    for t in tools:
        label = t.type or "Non renseigné"
        entry = by_type_map.setdefault(label, {"label": label, "count": 0, "total_value": 0.0})
        entry["count"] += 1
        entry["total_value"] += t.purchase_price or 0
    by_type = sorted(by_type_map.values(), key=lambda e: e["total_value"], reverse=True)

    by_agency = None
    if current_user.role == UserRole.admin:
        by_agency_map = {}
        for t in tools:
            label = t.agency_number or "Non renseignée"
            entry = by_agency_map.setdefault(label, {"label": label, "count": 0, "total_value": 0.0})
            entry["count"] += 1
            entry["total_value"] += t.purchase_price or 0
        by_agency = sorted(by_agency_map.values(), key=lambda e: e["total_value"], reverse=True)

    recent = sorted(
        [t for t in tools if t.purchase_date],
        key=lambda t: t.purchase_date,
        reverse=True,
    )[:10]
    recent_purchases = [
        schemas.RecentPurchase(name=t.name, type=t.type, purchase_price=t.purchase_price, purchase_date=t.purchase_date)
        for t in recent
    ]

    return schemas.FinancialSummary(
        total_value=total_value,
        total_count=total_count,
        by_type=by_type,
        by_agency=by_agency,
        recent_purchases=recent_purchases,
    )


@router.get("/export")
def export_agency_tools(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    tools = _scope_query(db.query(AgencyTool), current_user).order_by(AgencyTool.name).all()
    audit.record(db, "export_agency_tools", current_user.id, "agency_tool", None, request, {"count": len(tools)})
    db.commit()
    buffer = export_agency_tools_workbook(tools)

    filename_scope = current_user.agency_number if current_user.role != UserRole.admin else None
    filename = f"Outillage-{filename_scope or 'toutes-agences'}.xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("", response_model=schemas.AgencyToolOut, status_code=status.HTTP_201_CREATED)
def create_agency_tool(
    payload: schemas.AgencyToolCreate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_manager),
):
    if db.query(AgencyTool).filter(AgencyTool.unique_code == payload.unique_code).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce code existe déjà")

    data = payload.model_dump()
    if current_user.role != UserRole.admin:
        data["agency_number"] = current_user.agency_number
    elif not data.get("agency_number"):
        data["agency_number"] = current_user.agency_number
    else:
        data["agency_number"] = require_agency(db, data["agency_number"])

    tool = AgencyTool(**data)
    db.add(tool)
    db.flush()

    log_state_change(
        db, ToolKind.agency, tool.id, None, tool.state, None, tool.status.value,
        current_user.id, "création",
    )

    db.commit()
    db.refresh(tool)

    ok, message = excel_export.enqueue_sync(db, tool, "append", registry_name_for(db, tool.agency_number))
    db.commit()
    response.headers["X-Excel-Sync"] = "ok" if ok else _ascii_header_safe(message)

    return tool


@router.get("/{tool_id}", response_model=schemas.AgencyToolOut)
def get_agency_tool(tool_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _tool_view(_get_scoped_or_404(db, tool_id, current_user), current_user)


@router.patch("/{tool_id}", response_model=schemas.AgencyToolOut)
def update_agency_tool(
    tool_id: int,
    payload: schemas.AgencyToolUpdate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_manager),
):
    tool = _get_scoped_or_404(db, tool_id, current_user)
    data = payload.model_dump(exclude_unset=True)

    old_state = tool.state
    old_status = tool.status

    new_status = data.get("status", tool.status)
    refusal = controls.status_change_error(current_user, tool.status.value, AgencyToolStatus(new_status).value)
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)

    if "status" in data and new_status != AgencyToolStatus.hors_service and "loss_reason" not in data:
        data["loss_reason"] = None

    if new_status not in (AgencyToolStatus.dotation, AgencyToolStatus.hors_service) and "assigned_to_id" not in data:
        data["assigned_to_id"] = None

    if new_status == AgencyToolStatus.dotation:
        assigned = data.get("assigned_to_id", tool.assigned_to_id)
        if not assigned:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Une personne doit être assignée pour une dotation")
        if not db.query(User).filter(User.id == assigned).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Utilisateur assigné introuvable")

    comment = data.get("comment")
    error = schemas.warranty_error(data.get("purchase_date", tool.purchase_date), data.get("warranty_expiration_date", tool.warranty_expiration_date))
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    check_same_agency(db, current_user, data.get("assigned_to_id"), tool.agency_number)
    if data.get("parent_tool_id") is not None:
        _get_scoped_or_404(db, data["parent_tool_id"], current_user)

    for field, value in data.items():
        setattr(tool, field, value)

    if tool.state != old_state or tool.status != old_status:
        log_state_change(
            db, ToolKind.agency, tool.id, old_state, tool.state,
            old_status.value, tool.status.value,
            current_user.id, "édition", comment=comment,
        )
    if tool.status != old_status:
        audit.record(db, "tool_status_changed", current_user.id, "agency_tool", tool.id, request,
                     {"from": old_status.value, "to": tool.status.value, "source": "édition"})
    if data:
        audit.record(db, "agency_tool_updated", current_user.id, "agency_tool", tool.id, request, {"fields": sorted(data)})

    db.commit()
    db.refresh(tool)

    if data:
        ok, message = excel_export.enqueue_sync(db, tool, "update", registry_name_for(db, tool.agency_number))
        db.commit()
        if not ok:
            response.headers["X-Excel-Sync"] = _ascii_header_safe(message)

    if old_status != tool.status and tool.status in (AgencyToolStatus.reparation, AgencyToolStatus.hors_service):
        notify.on_tool_problem(db, "agency", tool, current_user.id, tool.status.value)
        ok, message = notify_magasinier(
            db,
            f"Outil d'agence signalé : {tool.name}",
            f"L'outil {tool.name} ({tool.unique_code}) est passé en statut {tool.status.value}.\n"
            f"Commentaire : {comment or '-'}",
        )
        db.commit()
        response.headers["X-Notification"] = "ok" if ok else _ascii_header_safe(message)
    else:
        response.headers["X-Notification"] = "ok"

    return tool


@router.post("/{tool_id}/control", response_model=schemas.AgencyToolOut)
def control_agency_tool(
    tool_id: int,
    payload: schemas.AgencyToolControlUpdate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tool = _get_scoped_or_404(db, tool_id, current_user)
    refusal = controls.status_change_error(current_user, tool.status.value, payload.status.value)
    if refusal:
        raise HTTPException(status_code=403, detail=refusal)

    old_state = tool.state
    old_status = tool.status

    tool.state = payload.state
    tool.status = payload.status
    tool.loss_reason = payload.loss_reason if payload.status == AgencyToolStatus.hors_service else None
    if payload.comment is not None:
        tool.comment = payload.comment
    if payload.serial_number is not None:
        tool.serial_number = payload.serial_number
    if payload.description is not None:
        tool.description = payload.description
    tool.last_control_date = datetime.utcnow()
    controls.log_simple_inspection(db, "agency", tool, current_user, payload.comment)

    log_state_change(
        db, ToolKind.agency, tool.id, old_state, tool.state,
        old_status.value, tool.status.value,
        current_user.id, "contrôle", comment=payload.comment,
    )
    if tool.status != old_status:
        audit.record(db, "tool_status_changed", current_user.id, "agency_tool", tool.id, request,
                     {"from": old_status.value, "to": tool.status.value, "source": "contrôle"})

    db.commit()
    db.refresh(tool)

    if old_status != tool.status and tool.status in (AgencyToolStatus.reparation, AgencyToolStatus.hors_service):
        notify.on_tool_problem(db, "agency", tool, current_user.id, tool.status.value)
        ok, message = notify_magasinier(
            db,
            f"Outil d'agence signalé lors du contrôle : {tool.name}",
            f"L'outil {tool.name} ({tool.unique_code}) est passé en statut {tool.status.value} lors d'un contrôle.\n"
            f"Commentaire : {payload.comment or '-'}",
        )
        db.commit()
        response.headers["X-Notification"] = "ok" if ok else _ascii_header_safe(message)
    else:
        response.headers["X-Notification"] = "ok"

    return _tool_view(tool, current_user)


@router.post("/{tool_id}/photo", response_model=schemas.AgencyToolOut)
def upload_agency_tool_photo(
    tool_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tool = _get_scoped_or_404(db, tool_id, current_user)
    tool.photo_path = save_upload_file(file, "agency_tools")
    db.commit()
    db.refresh(tool)
    return _tool_view(tool, current_user)


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agency_tool(
    tool_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    tool = db.query(AgencyTool).filter(AgencyTool.id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outil introuvable")
    audit.record(db, "agency_tool_deleted", current_user.id, "agency_tool", tool.id, request,
                 {"name": tool.name, "code": tool.unique_code})
    db.delete(tool)
    db.commit()
    return None
