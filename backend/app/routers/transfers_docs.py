import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import documents, limits, schemas, utils
from ..auth import get_current_user
from ..database import get_db
from ..hierarchy import visible_user_ids
from ..models import AgencyTool, PersonalTool, Transfer, User, UserRole
from ..notifications import send_email
from .transfers import _create_transfer_core

router = APIRouter(prefix="/transfers", tags=["transfers"])

MAILS_PER_HOUR = 20


class SignatureIn(BaseModel):
    signature: dict
    signed_name: Optional[str] = Field(default=None, max_length=120)


class EmailIn(BaseModel):
    to: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class BatchTransferIn(schemas.TransferFields):
    tool_ids: List[int] = []
    agency_tool_ids: List[int] = []


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


def _transfer_or_404(db: Session, user: User, transfer_id: int) -> Transfer:
    transfer = db.query(Transfer).filter(Transfer.id == transfer_id).first()
    if transfer is None:
        _fail("Prêt introuvable", status.HTTP_404_NOT_FOUND)
    allowed = user.role == UserRole.admin or transfer.from_user_id == user.id
    if not allowed and user.role != UserRole.gars_chantier:
        ids = visible_user_ids(db, user)
        allowed = ids is not None and transfer.from_user_id in ids
    if not allowed:
        _fail("Accès refusé à ce prêt", status.HTTP_403_FORBIDDEN)
    return transfer


def _tool_and_kind(db: Session, transfer: Transfer):
    if transfer.tool_id:
        return db.query(PersonalTool).filter(PersonalTool.id == transfer.tool_id).first(), False
    return db.query(AgencyTool).filter(AgencyTool.id == transfer.agency_tool_id).first(), True


def _discharge_bytes(db: Session, transfer: Transfer) -> bytes:
    tool, is_agency = _tool_and_kind(db, transfer)
    lender = db.query(User).filter(User.id == transfer.from_user_id).first()
    agency = tool.agency_number if is_agency else (lender.agency_number if lender else None)
    return documents.discharge_pdf(transfer, tool, lender.full_name if lender else "-", is_agency, agency)


@router.post("/batch", status_code=status.HTTP_201_CREATED)
def batch_transfer(payload: BatchTransferIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not payload.tool_ids and not payload.agency_tool_ids:
        _fail("Sélectionnez au moins un outil")
    common = payload.model_dump(exclude={"tool_ids", "agency_tool_ids"})
    created = []
    try:
        for tool_id in payload.tool_ids:
            created.append(_create_transfer_core(schemas.TransferCreate(tool_id=tool_id, **common), db, current_user))
        for tool_id in payload.agency_tool_ids:
            created.append(_create_transfer_core(schemas.TransferCreate(agency_tool_id=tool_id, **common), db, current_user))
    except HTTPException as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=f"Prêt groupé annulé : {exc.detail}")
    db.commit()
    return {"count": len(created), "transfer_ids": [t.id for t in created]}


@router.post("/{transfer_id}/signature")
def sign_transfer(transfer_id: int, payload: SignatureIn, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    transfer = _transfer_or_404(db, current_user, transfer_id)
    try:
        signature = documents.validate_signature(payload.signature)
    except ValueError as exc:
        _fail(str(exc))
    transfer.signature_json = json.dumps(signature)
    transfer.signed_name = payload.signed_name or transfer.to_external_name
    transfer.signed_at = utils.now()
    db.commit()
    return {"signed_at": transfer.signed_at}


@router.get("/{transfer_id}/discharge.pdf")
def discharge_pdf(transfer_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    transfer = _transfer_or_404(db, current_user, transfer_id)
    return Response(_discharge_bytes(db, transfer), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="decharge-{transfer.id}.pdf"'})


@router.post("/{transfer_id}/discharge/email")
def email_discharge(transfer_id: int, payload: EmailIn, response: Response, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    transfer = _transfer_or_404(db, current_user, transfer_id)
    if not limits.allow(db, f"mail:{current_user.id}", MAILS_PER_HOUR, 3600):
        _fail("Trop d'envois d'e-mails, réessayez plus tard", status.HTTP_429_TOO_MANY_REQUESTS)
    db.commit()
    tool, _ = _tool_and_kind(db, transfer)
    ok, message = send_email(
        db, payload.to, f"Décharge de responsabilité n°{transfer.id} — {tool.name}",
        f"Bonjour {transfer.to_external_name},\n\nVeuillez trouver ci-joint la décharge de responsabilité relative au prêt de {tool.name}.\n",
        attachments=[(f"decharge-{transfer.id}.pdf", _discharge_bytes(db, transfer), "application/pdf")],
    )
    response.headers["X-Notification"] = "ok" if ok else message.encode("ascii", "ignore").decode("ascii")
    return {"sent": ok, "detail": message}
