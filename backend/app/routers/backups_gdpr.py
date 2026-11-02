"""Phase 8 : sauvegardes (administration), tâches de reprise Excel, RGPD (export et anonymisation)."""
import json
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import audit, backups, excel_export, utils
from ..auth import get_current_admin, get_current_user, hash_password, invalidate_sessions
from ..database import get_db
from ..models import (
    AgencyTool, Epi, Loan, LoanStatus, PersonalTool, PeerTransfer, PeerTransferStatus, RefreshToken, Transfer, TransferStatus,
    User, UserRole,
)
from ..models_ext import Notification, PushSubscription
from ..models_p2 import Inspection, UserQualification
from ..models_p5 import MaintenanceTicket
from ..models_p8 import ExcelSyncTask
from ..models_p9 import AssistantAction, AssistantMessage
from .users import _holdings

backups_router = APIRouter(prefix="/admin/backups", tags=["sauvegardes"])
excel_router = APIRouter(prefix="/admin/excel-sync", tags=["excel"])
gdpr_router = APIRouter(prefix="/gdpr", tags=["rgpd"])


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


# ------------------------------------------------------------------ sauvegardes

@backups_router.get("")
def list_backups(current_user: User = Depends(get_current_admin)):
    return backups.list_backups()


@backups_router.post("", status_code=status.HTTP_201_CREATED)
def create_backup(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    path = backups.create_backup("manuel")
    audit.record(db, "backup_created", current_user.id, "backup", path.name, request, {"size": path.stat().st_size})
    db.commit()
    return {"name": path.name, "size": path.stat().st_size}


@backups_router.get("/{name}/verify")
def verify_backup(name: str, current_user: User = Depends(get_current_admin)):
    path = backups.resolve(name)
    if path is None:
        _fail("Sauvegarde introuvable", status.HTTP_404_NOT_FOUND)
    return backups.verify(path)


@backups_router.get("/{name}")
def download_backup(name: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    path = backups.resolve(name)
    if path is None:
        _fail("Sauvegarde introuvable", status.HTTP_404_NOT_FOUND)
    audit.record(db, "backup_downloaded", current_user.id, "backup", name, request)
    db.commit()
    return FileResponse(path, media_type="application/zip", filename=path.name)


@backups_router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backup(name: str, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    path = backups.resolve(name)
    if path is None:
        _fail("Sauvegarde introuvable", status.HTTP_404_NOT_FOUND)
    path.unlink()
    audit.record(db, "backup_deleted", current_user.id, "backup", name, request)
    db.commit()


# ------------------------------------------------------------------ reprise de la synchronisation Excel

@excel_router.get("")
def excel_tasks(status_filter: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    query = db.query(ExcelSyncTask)
    if status_filter:
        query = query.filter(ExcelSyncTask.status == status_filter)
    rows = query.order_by(ExcelSyncTask.id.desc()).limit(200).all()
    return [{"id": t.id, "agency_number": t.agency_number, "tool_id": t.tool_id, "action": t.action, "attempts": t.attempts,
             "last_error": t.last_error, "status": t.status, "created_at": t.created_at, "done_at": t.done_at} for t in rows]


@excel_router.post("/retry")
def excel_retry(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    done, failed = excel_export.retry_pending(db)
    return {"done": done, "failed": failed, "pending": db.query(ExcelSyncTask).filter(ExcelSyncTask.status == "pending").count()}


# ------------------------------------------------------------------ RGPD

def _can_export(db: Session, actor: User, target: User) -> bool:
    return actor.id == target.id or actor.role == UserRole.admin


@gdpr_router.get("/export/{user_id}")
def export_personal_data(user_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        _fail("Utilisateur introuvable", status.HTTP_404_NOT_FOUND)
    if not _can_export(db, current_user, target):
        _fail("Vous ne pouvez exporter que vos propres données", status.HTTP_403_FORBIDDEN)
    tools = db.query(PersonalTool).filter(PersonalTool.owner_id == target.id).all()
    data = {
        "generated_at": utils.now().isoformat(),
        "profile": {"id": target.id, "username": target.username, "full_name": target.full_name, "role": target.role.value,
                    "agency_number": target.agency_number, "email": target.email, "phone": target.phone, "is_active": target.is_active},
        "personal_tools": [{"name": t.name, "code": t.unique_code, "type": t.type, "state": t.state} for t in tools],
        "loans": [{"id": l.id, "tool_id": l.tool_id, "site": l.site, "status": l.status.value, "start": l.start_datetime,
                   "end_planned": l.end_datetime_planned, "returned": l.actual_return_datetime}
                  for l in db.query(Loan).filter(Loan.borrower_id == target.id)],
        "tickets_opened": [{"id": t.id, "tool_kind": t.tool_kind, "tool_id": t.tool_id, "category": t.category, "opened_at": t.opened_at}
                           for t in db.query(MaintenanceTicket).filter(MaintenanceTicket.opened_by_id == target.id)],
        "inspections": [{"id": i.id, "tool_kind": i.tool_kind, "tool_id": i.tool_id, "date": i.inspected_at, "result": i.result}
                        for i in db.query(Inspection).filter(Inspection.inspector_id == target.id).limit(1000)],
        "qualifications": [{"code": q.code, "obtained_at": q.obtained_at, "expires_at": q.expires_at}
                           for q in db.query(UserQualification).filter(UserQualification.user_id == target.id)],
        "notifications": [{"type": n.type, "title": n.title, "created_at": n.created_at} for n in db.query(Notification).filter(Notification.user_id == target.id).limit(500)],
        "push_subscriptions": db.query(PushSubscription).filter(PushSubscription.user_id == target.id).count(),
    }
    audit.record(db, "personal_data_exported", current_user.id, "user", target.id, request)
    db.commit()
    return json.loads(json.dumps(data, default=str))


@gdpr_router.post("/anonymize/{user_id}")
def anonymize_user(user_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    target = db.query(User).filter(User.id == user_id).first()
    if target is None:
        _fail("Utilisateur introuvable", status.HTTP_404_NOT_FOUND)
    if target.id == current_user.id:
        _fail("Vous ne pouvez pas anonymiser votre propre compte")
    if target.username.startswith("anonyme-"):
        _fail("Ce compte est déjà anonymisé")
    blocking = {label: n for label, n in _holdings(db, target.id).items() if n}
    if blocking:
        listing = ", ".join(f"{n} {label}" for label, n in blocking.items())
        _fail(f"Anonymisation impossible : ce compte a encore {listing}. Réaffectez son matériel d'abord.")

    target.username = f"anonyme-{target.id}"
    target.full_name = f"Utilisateur anonymisé #{target.id}"
    target.email = None
    target.phone = None
    target.is_active = False
    target.calendar_token = None
    target.hashed_password = hash_password(secrets.token_urlsafe(32))
    target.must_change_password = True
    invalidate_sessions(db, target)
    db.query(RefreshToken).filter(RefreshToken.user_id == target.id).delete(synchronize_session=False)
    db.query(PushSubscription).filter(PushSubscription.user_id == target.id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == target.id).delete(synchronize_session=False)
    db.query(AssistantAction).filter(AssistantAction.user_id == target.id).delete(synchronize_session=False)
    db.query(AssistantMessage).filter(AssistantMessage.user_id == target.id).delete(synchronize_session=False)
    audit.record(db, "user_anonymized", current_user.id, "user", target.id, request)
    db.commit()
    return {"id": target.id, "username": target.username, "full_name": target.full_name}
