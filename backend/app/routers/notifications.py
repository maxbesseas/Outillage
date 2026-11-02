from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .. import appsettings, audit, notify, utils, webpush
from ..auth import get_current_admin, get_current_user
from ..database import get_db
from ..hierarchy import visible_user_ids
from ..models import AgencyTool, Loan, LoanStatus, PeerTransfer, PeerTransferStatus, PersonalTool, Transfer, TransferStatus, User, UserRole
from ..models_ext import Notification, NotificationPreference, PushSubscription

router = APIRouter(prefix="/notifications", tags=["notifications"])
push_router = APIRouter(prefix="/push", tags=["push"])
dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])
app_settings_router = APIRouter(prefix="/settings/app", tags=["settings"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    severity: str
    title: str
    body: Optional[str] = None
    entity_kind: Optional[str] = None
    entity_id: Optional[str] = None
    link: Optional[str] = None
    created_at: datetime
    read_at: Optional[datetime] = None


class PreferenceItem(BaseModel):
    type: str
    label: Optional[str] = None
    in_app: bool
    email: bool
    push: bool


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscribeRequest(BaseModel):
    endpoint: str
    keys: PushKeys


class PushUnsubscribeRequest(BaseModel):
    endpoint: str


class SettingsPatch(BaseModel):
    values: dict


def _mine(db: Session, user: User):
    return db.query(Notification).filter(Notification.user_id == user.id, Notification.in_app.is_(True))


@router.get("", response_model=List[NotificationOut])
def list_notifications(
    response: Response,
    unread_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _mine(db, current_user)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    response.headers["X-Total-Count"] = str(query.count())
    return (
        query.order_by(Notification.id.desc()).offset(max(offset, 0)).limit(max(1, min(limit, 200))).all()
    )


@router.get("/count")
def count_notifications(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    unread = _mine(db, current_user).filter(Notification.read_at.is_(None)).count()
    critical = (
        _mine(db, current_user)
        .filter(Notification.read_at.is_(None), Notification.severity == "critical")
        .count()
    )
    return {"unread": unread, "critical": critical}


@router.post("/read-all")
def read_all(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    updated = (
        _mine(db, current_user)
        .filter(Notification.read_at.is_(None))
        .update({"read_at": utils.now()}, synchronize_session=False)
    )
    db.commit()
    return {"updated": updated}


@router.get("/preferences", response_model=List[PreferenceItem])
def get_preferences(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [
        {"type": type_, "label": notify.type_label(type_), **notify.resolve_preference(db, current_user, type_)}
        for type_ in notify.TYPES
        if type_ != "generic"
    ]


@router.put("/preferences", response_model=List[PreferenceItem])
def put_preferences(
    items: List[PreferenceItem],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    for item in items:
        if item.type not in notify.TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Type inconnu : {item.type}")
        row = (
            db.query(NotificationPreference)
            .filter(NotificationPreference.user_id == current_user.id, NotificationPreference.type == item.type)
            .first()
        )
        if row is None:
            row = NotificationPreference(user_id=current_user.id, type=item.type)
            db.add(row)
        row.in_app, row.email, row.push = item.in_app, item.email, item.push
    db.commit()
    return get_preferences(db, current_user)


@router.post("/{notification_id}/read")
def read_one(notification_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == current_user.id)
        .first()
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification introuvable")
    if notification.read_at is None:
        notification.read_at = utils.now()
        db.commit()
    return {"id": notification.id, "read": True}


# ------------------------------------------------------------------ push

@push_router.get("/public-key")
def push_public_key(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    key = webpush.public_key_b64(db)
    db.commit()
    return {"public_key": key}


@push_router.post("/subscribe", status_code=status.HTTP_201_CREATED)
def push_subscribe(
    payload: PushSubscribeRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not payload.endpoint.startswith("https://"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Point de terminaison invalide")
    sub = db.query(PushSubscription).filter(PushSubscription.endpoint == payload.endpoint).first()
    if sub is None:
        sub = PushSubscription(endpoint=payload.endpoint, p256dh=payload.keys.p256dh, auth=payload.keys.auth)
        db.add(sub)
    sub.user_id = current_user.id
    sub.p256dh, sub.auth = payload.keys.p256dh, payload.keys.auth
    sub.user_agent = request.headers.get("user-agent", "")[:200]
    db.commit()
    return {"subscribed": True}


@push_router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
def push_unsubscribe(
    payload: PushUnsubscribeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    db.query(PushSubscription).filter(
        PushSubscription.endpoint == payload.endpoint, PushSubscription.user_id == current_user.id
    ).delete(synchronize_session=False)
    db.commit()
    return None


# ------------------------------------------------------------------ tableau de bord : retards

@dashboard_router.get("/overdue")
def dashboard_overdue(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    now = utils.now()
    ids = visible_user_ids(db, current_user)
    if current_user.role == UserRole.gars_chantier:
        ids = {current_user.id}

    names = {u.id: u.full_name for u in db.query(User).all()}

    loan_query = db.query(Loan).filter(Loan.status == LoanStatus.en_cours, Loan.end_datetime_planned < now)
    if ids is not None:
        loan_query = loan_query.filter(Loan.borrower_id.in_(ids))
    loans = []
    for loan in loan_query.order_by(Loan.end_datetime_planned).all():
        tool = db.query(AgencyTool).filter(AgencyTool.id == loan.tool_id).first()
        loans.append({
            "id": loan.id, "tool_id": loan.tool_id, "tool_name": tool.name if tool else "-",
            "borrower_id": loan.borrower_id, "borrower_name": names.get(loan.borrower_id, "-"),
            "due": loan.end_datetime_planned, "days_late": (now - loan.end_datetime_planned).days,
        })

    transfer_query = db.query(Transfer).filter(
        Transfer.status == TransferStatus.en_cours, Transfer.planned_return_date.isnot(None),
        Transfer.planned_return_date < now,
    )
    if ids is not None:
        transfer_query = transfer_query.filter(Transfer.from_user_id.in_(ids))
    transfers = []
    for transfer in transfer_query.order_by(Transfer.planned_return_date).all():
        tool = (
            db.query(PersonalTool).filter(PersonalTool.id == transfer.tool_id).first()
            if transfer.tool_id else db.query(AgencyTool).filter(AgencyTool.id == transfer.agency_tool_id).first()
        )
        transfers.append({
            "id": transfer.id, "tool_name": tool.name if tool else "-", "from_user_id": transfer.from_user_id,
            "from_name": names.get(transfer.from_user_id, "-"), "recipient": transfer.to_external_name,
            "due": transfer.planned_return_date, "days_late": (now - transfer.planned_return_date).days,
        })

    peer_query = db.query(PeerTransfer).filter(PeerTransfer.status == PeerTransferStatus.en_attente)
    if current_user.role != UserRole.admin:
        peer_query = peer_query.filter(
            (PeerTransfer.from_user_id == current_user.id) | (PeerTransfer.to_user_id == current_user.id)
        )
    peer = [
        {"id": p.id, "declared_by_id": p.declared_by_id, "since": p.transfer_date,
         "needs_my_confirmation": p.declared_by_id != current_user.id}
        for p in peer_query.all()
    ]
    return {"loans": loans, "transfers": transfers, "peer_transfers": peer}


# ------------------------------------------------------------------ réglages applicatifs (admin)

@app_settings_router.get("")
def read_app_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    return appsettings.all_settings(db)


@app_settings_router.patch("")
def patch_app_settings(
    payload: SettingsPatch,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    unknown = [k for k in payload.values if k not in appsettings.DEFAULTS]
    if unknown:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Réglage inconnu : {', '.join(unknown)}")
    for key, value in payload.values.items():
        appsettings.set_value(db, key, value)
    audit.record(db, "app_settings_updated", current_user.id, "settings", None, request, {"keys": sorted(payload.values)})
    db.commit()
    return appsettings.all_settings(db)
