from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..history import log_state_change
from ..models import PeerTransfer, PeerTransferStatus, PersonalTool, ToolKind, ToolStateReason, User, UserRole

router = APIRouter(prefix="/peer-transfers", tags=["peer-transfers"])

ACTIVE_STATUSES = (PeerTransferStatus.en_attente, PeerTransferStatus.confirme)


@router.get("", response_model=list[schemas.PeerTransferOut])
def list_peer_transfers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(PeerTransfer)
    if current_user.role != UserRole.admin:
        query = query.filter(
            or_(PeerTransfer.from_user_id == current_user.id, PeerTransfer.to_user_id == current_user.id)
        )
    return query.order_by(PeerTransfer.transfer_date.desc()).all()


@router.post("", response_model=schemas.PeerTransferOut, status_code=status.HTTP_201_CREATED)
def create_peer_transfer(
    payload: schemas.PeerTransferCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tool = db.query(PersonalTool).filter(PersonalTool.unique_code == payload.tool_code).first()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aucun outil trouvé pour ce code")

    if tool.state_reason != ToolStateReason.normal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cet outil est signalé {tool.state_reason.value} et ne peut pas être transféré",
        )

    counterpart = db.query(User).filter(User.id == payload.counterpart_id).first()
    if not counterpart or counterpart.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Collègue invalide")

    if payload.direction == "je_donne":
        from_user_id = current_user.id
        to_user_id = counterpart.id
        if current_user.role != UserRole.admin and tool.current_holder_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vous ne détenez pas cet outil")
    else:
        from_user_id = counterpart.id
        to_user_id = current_user.id
        if tool.current_holder_id != counterpart.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce collègue ne détient pas cet outil")

    existing = (
        db.query(PeerTransfer)
        .filter(PeerTransfer.tool_id == tool.id, PeerTransfer.status.in_(ACTIVE_STATUSES))
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Un transfert est déjà en cours sur cet outil")

    transfer = PeerTransfer(
        tool_id=tool.id,
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        declared_by_id=current_user.id,
        status=PeerTransferStatus.en_attente,
        state_before=tool.state,
        planned_return_date=payload.planned_return_date,
        comment=payload.comment,
    )
    db.add(transfer)
    db.commit()
    db.refresh(transfer)
    return transfer


@router.post("/{transfer_id}/confirm", response_model=schemas.PeerTransferOut)
def confirm_peer_transfer(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transfer = db.query(PeerTransfer).filter(PeerTransfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfert introuvable")

    if current_user.role != UserRole.admin:
        if transfer.declared_by_id == current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vous ne pouvez pas confirmer votre propre déclaration")
        if current_user.id not in (transfer.from_user_id, transfer.to_user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à ce transfert")

    if transfer.status != PeerTransferStatus.en_attente:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce transfert n'est pas en attente")

    transfer.status = PeerTransferStatus.confirme
    transfer.confirmed_at = datetime.utcnow()

    tool = db.query(PersonalTool).filter(PersonalTool.id == transfer.tool_id).first()
    if tool.current_holder_id != transfer.from_user_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="L'outil a changé de détenteur depuis cette déclaration")
    tool.current_holder_id = transfer.to_user_id

    db.commit()
    db.refresh(transfer)
    return transfer


@router.post("/{transfer_id}/reject", response_model=schemas.PeerTransferOut)
def reject_peer_transfer(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transfer = db.query(PeerTransfer).filter(PeerTransfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfert introuvable")

    if current_user.role != UserRole.admin:
        if transfer.declared_by_id == current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Vous ne pouvez pas traiter votre propre déclaration")
        if current_user.id not in (transfer.from_user_id, transfer.to_user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à ce transfert")

    if transfer.status != PeerTransferStatus.en_attente:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce transfert n'est pas en attente")

    transfer.status = PeerTransferStatus.refuse
    db.commit()
    db.refresh(transfer)
    return transfer


@router.post("/{transfer_id}/return", response_model=schemas.PeerTransferOut)
def return_peer_transfer(
    transfer_id: int,
    payload: schemas.PeerTransferReturn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transfer = db.query(PeerTransfer).filter(PeerTransfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transfert introuvable")

    if current_user.role != UserRole.admin and current_user.id not in (transfer.from_user_id, transfer.to_user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à ce transfert")

    if transfer.status != PeerTransferStatus.confirme:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce transfert n'est pas confirmé")

    transfer.status = PeerTransferStatus.termine
    transfer.actual_return_date = datetime.utcnow()
    transfer.state_after = payload.state_after
    if payload.comment is not None:
        transfer.comment = payload.comment

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
        current_user.id, "retour entre collègues", comment=payload.comment,
    )

    db.commit()
    db.refresh(transfer)
    return transfer
