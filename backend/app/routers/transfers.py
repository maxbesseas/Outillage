from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import schemas, utils
from ..auth import get_current_user
from ..database import get_db
from ..hierarchy import visible_user_ids
from ..history import log_state_change
from ..models import (
    AgencyTool,
    AgencyToolStatus,
    PersonalTool,
    ToolKind,
    ToolStateReason,
    Transfer,
    TransferStatus,
    User,
    UserRole,
)

router = APIRouter(prefix="/transfers", tags=["transfers"])

PAST_RETURN_TOLERANCE = timedelta(0)


@router.get("", response_model=list[schemas.TransferOut])
def list_transfers(
    scope: str = "mine",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Transfer)
    if current_user.role == UserRole.gars_chantier:
        scope = "mine"

    if scope == "team":
        ids = visible_user_ids(db, current_user)
        if ids is not None:
            query = query.filter(Transfer.from_user_id.in_(ids))
    elif scope == "agency":
        if current_user.role != UserRole.admin:
            query = query.join(User, Transfer.from_user_id == User.id).filter(
                User.agency_number == current_user.agency_number
            )
    else:
        query = query.filter(Transfer.from_user_id == current_user.id)

    return query.order_by(Transfer.transfer_date.desc()).all()


def _create_transfer_core(
    payload: schemas.TransferCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if bool(payload.tool_id) == bool(payload.agency_tool_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fournir exactement un outil personnel ou d'agence")

    if not payload.to_external_name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le nom du destinataire est requis")
    if payload.planned_return_date and payload.planned_return_date.replace(tzinfo=None).date() < (utils.now() - PAST_RETURN_TOLERANCE).date():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La date de retour prévue est déjà passée")

    data = payload.model_dump()

    if payload.tool_id:
        tool = db.query(PersonalTool).filter(PersonalTool.id == payload.tool_id).first()
        if not tool:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outil introuvable")

        authorized = (
            current_user.role == UserRole.admin
            or tool.current_holder_id == current_user.id
            or (tool.current_holder_id is None and tool.owner_id == current_user.id)
        )
        if not authorized:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à cet outil")

        if tool.state_reason != ToolStateReason.normal:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cet outil est signalé {tool.state_reason.value} et ne peut pas être prêté",
            )

        existing = (
            db.query(Transfer)
            .filter(Transfer.tool_id == tool.id, Transfer.status == TransferStatus.en_cours)
            .first()
        )
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Un prêt externe est déjà en cours sur cet outil")

        from_user_id = tool.current_holder_id or tool.owner_id
        state_before = tool.state

        transfer = Transfer(
            from_user_id=from_user_id,
            state_before=state_before,
            **data,
        )
        db.add(transfer)

        tool.current_holder_id = None

        log_state_change(
            db, ToolKind.personal, tool.id, tool.state, tool.state,
            tool.state_reason.value, tool.state_reason.value,
            current_user.id, "prêt externe",
        )

        db.flush()
        return transfer

    else:
        tool = db.query(AgencyTool).filter(AgencyTool.id == payload.agency_tool_id).first()
        if not tool:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outil introuvable")
        if current_user.role != UserRole.admin and tool.agency_number != current_user.agency_number:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cet outil appartient à une autre agence")
        if tool.status != AgencyToolStatus.disponible:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cet outil n'est pas disponible")

        state_before = tool.state

        transfer = Transfer(
            from_user_id=current_user.id,
            state_before=state_before,
            **data,
        )
        db.add(transfer)

        old_status = tool.status
        tool.status = AgencyToolStatus.emprunte
        log_state_change(
            db, ToolKind.agency, tool.id, tool.state, tool.state,
            old_status.value, tool.status.value,
            current_user.id, "prêt externe",
        )

        db.flush()
        return transfer


@router.post("", response_model=schemas.TransferOut, status_code=status.HTTP_201_CREATED)
def create_transfer(
    payload: schemas.TransferCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transfer = _create_transfer_core(payload, db, current_user)
    db.commit()
    db.refresh(transfer)
    return transfer


@router.post("/{transfer_id}/return", response_model=schemas.TransferOut)
def return_transfer(
    transfer_id: int,
    payload: schemas.TransferReturn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transfer = db.query(Transfer).filter(Transfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prêt introuvable")
    if current_user.role != UserRole.admin and transfer.from_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à ce prêt")

    if transfer.status != TransferStatus.en_cours:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce prêt n'est pas en cours")

    transfer.status = TransferStatus.termine
    transfer.actual_return_date = datetime.utcnow()
    transfer.state_after = payload.state_after
    if payload.comment is not None:
        transfer.comment = payload.comment

    if transfer.tool_id:
        tool = db.query(PersonalTool).filter(PersonalTool.id == transfer.tool_id).first()
        old_state = tool.state
        tool.current_holder_id = transfer.from_user_id
        tool.state = payload.state_after
        if payload.state_after == 0:
            tool.state_reason = ToolStateReason.endommage
        elif payload.state_after == 1:
            tool.state_reason = ToolStateReason.en_reparation
        else:
            tool.state_reason = ToolStateReason.normal

        log_state_change(
            db, ToolKind.personal, tool.id, old_state, tool.state,
            None, tool.state_reason.value,
            current_user.id, "retour prêt externe", comment=payload.comment,
        )
    else:
        tool = db.query(AgencyTool).filter(AgencyTool.id == transfer.agency_tool_id).first()
        old_state = tool.state
        old_status = tool.status
        tool.state = payload.state_after
        if payload.state_after == 0:
            tool.status = AgencyToolStatus.hors_service
            tool.loss_reason = "casse"
        elif payload.state_after == 1:
            tool.status = AgencyToolStatus.reparation
        else:
            tool.status = AgencyToolStatus.disponible

        log_state_change(
            db, ToolKind.agency, tool.id, old_state, tool.state,
            old_status.value, tool.status.value,
            current_user.id, "retour prêt externe", comment=payload.comment,
        )

    db.commit()
    db.refresh(transfer)
    return transfer
