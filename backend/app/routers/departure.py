from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import audit, notify
from ..agencies import require_agency
from ..auth import get_current_admin, get_current_user, invalidate_sessions
from ..database import get_db
from ..hierarchy import PARENT_ROLE, visible_user_ids
from ..models import (
    AgencyTool,
    AgencyToolStatus,
    Epi,
    Loan,
    LoanStatus,
    PeerTransfer,
    PeerTransferStatus,
    PersonalTool,
    Transfer,
    TransferStatus,
    User,
    UserRole,
)

router = APIRouter(prefix="/users", tags=["departure"])


class DepartIn(BaseModel):
    to_user_id: int
    transfer_ownership: bool = True
    transfer_loans: bool = False
    transfer_external: bool = False
    reassign_subordinates_to: Optional[int] = None
    deactivate: bool = True


class ChangeAgencyIn(BaseModel):
    agency_number: str
    manager_id: Optional[int] = None
    include_subordinates: bool = False


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


def _target_for(db: Session, actor: User, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        _fail("Utilisateur introuvable", status.HTTP_404_NOT_FOUND)
    if actor.role == UserRole.gars_chantier:
        _fail("Réservé aux gestionnaires", status.HTTP_403_FORBIDDEN)
    ids = visible_user_ids(db, actor)
    if ids is not None and user.id not in ids:
        _fail("Cet utilisateur n'est pas dans votre équipe", status.HTTP_403_FORBIDDEN)
    if user.id == actor.id:
        _fail("Vous ne pouvez pas traiter votre propre départ")
    return user


def _items(db: Session, user_id: int) -> dict:
    active_loans = db.query(Loan).filter(Loan.borrower_id == user_id,
                                         Loan.status.in_((LoanStatus.reserve, LoanStatus.en_cours, LoanStatus.attente_validation))).all()
    external = db.query(Transfer).filter(Transfer.from_user_id == user_id, Transfer.status == TransferStatus.en_cours).all()
    peer = db.query(PeerTransfer).filter(
        (PeerTransfer.from_user_id == user_id) | (PeerTransfer.to_user_id == user_id),
        PeerTransfer.status.in_((PeerTransferStatus.en_attente, PeerTransferStatus.confirme))).all()
    return {
        "owned_tools": db.query(PersonalTool).filter(PersonalTool.owner_id == user_id).all(),
        "held_tools": db.query(PersonalTool).filter(PersonalTool.current_holder_id == user_id, PersonalTool.owner_id != user_id).all(),
        "epi": db.query(Epi).filter(Epi.assigned_to_id == user_id).all(),
        "dotations": db.query(AgencyTool).filter(AgencyTool.assigned_to_id == user_id, AgencyTool.status == AgencyToolStatus.dotation).all(),
        "loans": active_loans, "external": external, "peer": peer,
        "subordinates": db.query(User).filter(User.manager_id == user_id, User.is_active.is_(True)).all(),
    }


@router.get("/{user_id}/departure-summary")
def departure_summary(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user = _target_for(db, current_user, user_id)
    items = _items(db, user.id)
    return {
        "user": {"id": user.id, "full_name": user.full_name, "role": user.role.value, "agency_number": user.agency_number},
        "reassignable": {
            "personal_tools": db.query(PersonalTool).filter(PersonalTool.current_holder_id == user.id).count(),
            "epi": len(items["epi"]), "dotations": len(items["dotations"]),
        },
        "owned_tools": [{"id": t.id, "name": t.name, "code": t.unique_code} for t in items["owned_tools"]],
        "held_tools": [{"id": t.id, "name": t.name, "code": t.unique_code} for t in items["held_tools"]],
        "epi": [{"id": e.id, "name": e.name, "code": e.unique_code} for e in items["epi"]],
        "dotations": [{"id": t.id, "name": t.name, "code": t.unique_code} for t in items["dotations"]],
        "loans": [{"id": l.id, "status": l.status.value, "end": l.end_datetime_planned} for l in items["loans"]],
        "external_transfers": [{"id": t.id, "recipient": t.to_external_name} for t in items["external"]],
        "peer_transfers": [{"id": p.id, "status": p.status.value} for p in items["peer"]],
        "subordinates": [{"id": u.id, "full_name": u.full_name} for u in items["subordinates"]],
    }


@router.post("/{user_id}/depart")
def depart(user_id: int, payload: DepartIn, request: Request, db: Session = Depends(get_db),
           current_user: User = Depends(get_current_user)):
    user = _target_for(db, current_user, user_id)
    target = db.query(User).filter(User.id == payload.to_user_id, User.is_active.is_(True)).first()
    if target is None or target.id == user.id:
        _fail("Destinataire invalide")
    ids = visible_user_ids(db, current_user)
    if ids is not None and target.id not in ids:
        _fail("Le destinataire n'est pas dans votre équipe", status.HTTP_403_FORBIDDEN)
    if current_user.role != UserRole.admin and target.agency_number != user.agency_number:
        _fail("Le destinataire doit être de la même agence")

    items = _items(db, user.id)
    blockers = []
    if items["peer"]:
        blockers.append(f"{len(items['peer'])} transfert(s) entre collègues à régler")
    if items["loans"] and not payload.transfer_loans:
        blockers.append(f"{len(items['loans'])} réservation(s) active(s) (rendez-les ou cochez « transférer les réservations »)")
    if items["external"] and not payload.transfer_external:
        blockers.append(f"{len(items['external'])} prêt(s) externe(s) en cours (récupérez-les ou cochez « transférer les prêts »)")
    subordinate_target = None
    if items["subordinates"]:
        if payload.reassign_subordinates_to is None:
            blockers.append(f"{len(items['subordinates'])} collaborateur(s) rattaché(s) : indiquez un nouveau responsable")
        else:
            subordinate_target = db.query(User).filter(User.id == payload.reassign_subordinates_to, User.is_active.is_(True)).first()
            if subordinate_target is None or subordinate_target.role != user.role or subordinate_target.id == user.id \
                    or (current_user.role != UserRole.admin and subordinate_target.agency_number != user.agency_number):
                blockers.append("Le nouveau responsable doit être un autre utilisateur de même rôle")
    if blockers:
        _fail("Départ impossible : " + " ; ".join(blockers))

    counts = {}
    counts["personal_tools"] = db.query(PersonalTool).filter(PersonalTool.current_holder_id == user.id).update(
        {"current_holder_id": target.id}, synchronize_session=False)
    counts["epi"] = db.query(Epi).filter(Epi.assigned_to_id == user.id).update({"assigned_to_id": target.id}, synchronize_session=False)
    counts["dotations"] = db.query(AgencyTool).filter(
        AgencyTool.assigned_to_id == user.id, AgencyTool.status == AgencyToolStatus.dotation
    ).update({"assigned_to_id": target.id}, synchronize_session=False)
    if payload.transfer_ownership:
        counts["ownership"] = db.query(PersonalTool).filter(PersonalTool.owner_id == user.id).update(
            {"owner_id": target.id}, synchronize_session=False)
    if payload.transfer_loans:
        counts["loans"] = db.query(Loan).filter(
            Loan.borrower_id == user.id,
            Loan.status.in_((LoanStatus.reserve, LoanStatus.en_cours, LoanStatus.attente_validation)),
        ).update({"borrower_id": target.id}, synchronize_session=False)
    if payload.transfer_external:
        counts["external"] = db.query(Transfer).filter(Transfer.from_user_id == user.id, Transfer.status == TransferStatus.en_cours).update(
            {"from_user_id": target.id}, synchronize_session=False)
    if subordinate_target is not None:
        counts["subordinates"] = db.query(User).filter(User.manager_id == user.id).update(
            {"manager_id": subordinate_target.id}, synchronize_session=False)
    if payload.deactivate:
        user.is_active = False
        invalidate_sessions(db, user)

    notify.create(db, target.id, "generic", f"Matériel repris de {user.full_name}",
                  f"{counts.get('personal_tools', 0)} outil(s), {counts.get('epi', 0)} EPI et {counts.get('dotations', 0)} dotation(s) vous ont été confiés.",
                  link="#/mes-outils")
    audit.record(db, "user_departure", current_user.id, "user", user.id, request,
                 {"to_user_id": target.id, "deactivated": payload.deactivate, **counts})
    db.commit()
    return {"done": True, "counts": counts, "deactivated": payload.deactivate}


def _move(db: Session, user: User, agency: str):
    user.agency_number = agency
    db.query(AgencyTool).filter(AgencyTool.assigned_to_id == user.id, AgencyTool.status == AgencyToolStatus.dotation).update(
        {"agency_number": agency}, synchronize_session=False)
    db.query(Epi).filter(Epi.assigned_to_id == user.id).update({"agency_number": agency}, synchronize_session=False)


@router.post("/{user_id}/change-agency")
def change_agency(user_id: int, payload: ChangeAgencyIn, request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        _fail("Utilisateur introuvable", status.HTTP_404_NOT_FOUND)
    agency = require_agency(db, payload.agency_number)
    if agency == user.agency_number:
        _fail("L'utilisateur est déjà dans cette agence")

    items = _items(db, user.id)
    if items["loans"] or items["external"] or items["peer"]:
        _fail("Changement d'agence impossible : réservations, prêts ou transferts encore actifs")

    if payload.manager_id is not None:
        manager = db.query(User).filter(User.id == payload.manager_id).first()
        expected = PARENT_ROLE.get(user.role)
        if manager is None or expected is None or manager.role != expected or manager.agency_number != agency:
            _fail("Le nouveau responsable doit avoir le bon rôle et appartenir à la nouvelle agence")
        user.manager_id = manager.id
    elif user.manager_id is not None and user.role != UserRole.directeur_agence:
        user.manager_id = None

    moved = [user]
    if payload.include_subordinates:
        frontier = [user.id]
        while frontier:
            children = db.query(User).filter(User.manager_id.in_(frontier)).all()
            moved.extend(children)
            frontier = [c.id for c in children]
    for u in moved:
        _move(db, u, agency)
    invalidate_sessions(db, user)
    audit.record(db, "user_agency_changed", current_user.id, "user", user.id, request,
                 {"to": agency, "moved": [u.id for u in moved]})
    db.commit()
    return {"moved": len(moved), "agency_number": agency}
