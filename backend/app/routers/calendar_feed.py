import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from .. import audit, config, ics, utils
from ..auth import get_current_user
from ..database import get_db
from ..models import AgencyTool, Loan, LoanStatus, PersonalTool, Transfer, TransferStatus, User

router = APIRouter(prefix="/calendar", tags=["calendar"])


def _url(token: str) -> str:
    return f"{config.PUBLIC_URL}/calendar/feed/{token}.ics"


@router.get("/token")
def get_token(current_user: User = Depends(get_current_user)):
    return {"url": _url(current_user.calendar_token) if current_user.calendar_token else None}


@router.post("/token")
def regenerate_token(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.calendar_token = secrets.token_urlsafe(32)
    audit.record(db, "calendar_token_regenerated", current_user.id, "user", current_user.id, request)
    db.commit()
    return {"url": _url(current_user.calendar_token)}


@router.delete("/token", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    current_user.calendar_token = None
    audit.record(db, "calendar_token_revoked", current_user.id, "user", current_user.id, request)
    db.commit()
    return None


@router.get("/feed/{token}.ics")
def feed(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.calendar_token == token, User.is_active.is_(True)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flux introuvable")
    now = utils.now()
    events = []
    loans = (
        db.query(Loan)
        .filter(Loan.borrower_id == user.id,
                Loan.status.in_((LoanStatus.reserve, LoanStatus.en_cours, LoanStatus.attente_validation)),
                Loan.end_datetime_planned >= now - timedelta(days=30))
        .all()
    )
    for loan in loans:
        tool = db.query(AgencyTool).filter(AgencyTool.id == loan.tool_id).first()
        name = tool.name if tool else "outil"
        pending = loan.status == LoanStatus.attente_validation
        events.append(ics.event(
            f"loan-{loan.id}@fauche", loan.start_datetime, loan.end_datetime_planned,
            f"{'(à valider) ' if pending else ''}Réservation : {name}",
            loan.comment or "", loan.site or "", status="TENTATIVE" if pending else "CONFIRMED", now=now,
        ))
    transfers = (
        db.query(Transfer)
        .filter(Transfer.from_user_id == user.id, Transfer.status == TransferStatus.en_cours,
                Transfer.planned_return_date.isnot(None))
        .all()
    )
    for transfer in transfers:
        tool = db.query(PersonalTool).filter(PersonalTool.id == transfer.tool_id).first() if transfer.tool_id \
            else db.query(AgencyTool).filter(AgencyTool.id == transfer.agency_tool_id).first()
        start = transfer.planned_return_date.replace(hour=9, minute=0, second=0, microsecond=0)
        events.append(ics.event(
            f"transfer-{transfer.id}@fauche", start, start + timedelta(minutes=30),
            f"Retour prêt externe : {tool.name if tool else 'outil'}",
            f"Prêté à {transfer.to_external_name}", "", now=now,
        ))
    body = ics.calendar(events, name=f"Fauché — {user.full_name}")
    return PlainTextResponse(body, media_type="text/calendar; charset=utf-8", headers={"Cache-Control": "no-store"})
