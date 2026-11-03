from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, schemas
from ..agencies import require_agency
from ..auth import (
    generate_temporary_password,
    get_current_admin,
    get_current_user,
    hash_password,
    invalidate_sessions,
    validate_password_strength,
)
from ..database import Base, get_db
from ..hierarchy import CHILD_ROLE, PARENT_ROLE, ROLE_LABELS, visible_user_ids
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

router = APIRouter(prefix="/users", tags=["users"])


# Données propres au compte, supprimées avec lui ; le reste de l'historique métier reste rattaché et bloque la suppression.
ACCOUNT_TABLES = {
    "refresh_tokens", "password_reset_tokens", "notifications", "notification_preferences", "push_subscriptions",
    "assistant_actions", "assistant_messages", "assistant_usage", "user_qualifications", "charter_acceptances",
}


def _user_references():
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name == "users":
                yield table, fk.parent


def _history_tables(db: Session, user_id: int) -> list:
    return sorted({
        table.name for table, column in _user_references()
        if not column.nullable and table.name not in ACCOUNT_TABLES
        and db.execute(select(func.count()).select_from(table).where(column == user_id)).scalar()
    })


def _release_references(db: Session, user_id: int):
    for table, column in _user_references():
        if table.name in ACCOUNT_TABLES and not column.nullable:
            db.execute(table.delete().where(column == user_id))
        elif column.nullable:
            db.execute(table.update().where(column == user_id).values({column.name: None}))


def _holdings(db: Session, user_id: int) -> dict:
    return {
        "outil(s) personnel(s) dont il est propriétaire": db.query(PersonalTool)
        .filter(PersonalTool.owner_id == user_id)
        .count(),
        "outil(s) personnel(s) qu'il détient": db.query(PersonalTool)
        .filter(PersonalTool.current_holder_id == user_id, PersonalTool.owner_id != user_id)
        .count(),
        "EPI assigné(s)": db.query(Epi).filter(Epi.assigned_to_id == user_id).count(),
        "outil(s) d'agence en dotation": db.query(AgencyTool)
        .filter(AgencyTool.assigned_to_id == user_id, AgencyTool.status == AgencyToolStatus.dotation)
        .count(),
        "réservation(s) active(s)": db.query(Loan)
        .filter(Loan.borrower_id == user_id, Loan.status.in_((LoanStatus.reserve, LoanStatus.en_cours)))
        .count(),
        "prêt(s) externe(s) en cours": db.query(Transfer)
        .filter(Transfer.from_user_id == user_id, Transfer.status == TransferStatus.en_cours)
        .count(),
        "transfert(s) entre collègues en cours": db.query(PeerTransfer)
        .filter(
            (PeerTransfer.from_user_id == user_id) | (PeerTransfer.to_user_id == user_id),
            PeerTransfer.status.in_((PeerTransferStatus.en_attente, PeerTransferStatus.confirme)),
        )
        .count(),
        "collaborateur(s) rattaché(s)": db.query(User).filter(User.manager_id == user_id).count(),
    }


@router.get("", response_model=None)
def list_users(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    schema = schemas.UserOut if current_user.role == UserRole.admin else schemas.UserDirectoryOut
    return [schema.model_validate(u) for u in db.query(User).order_by(User.full_name).all()]


@router.get("/team", response_model=list[schemas.UserOut])
def list_team(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ids = visible_user_ids(db, current_user)
    query = db.query(User)
    if ids is not None:
        query = query.filter(User.id.in_(ids))
    return query.order_by(User.full_name).all()


def build_user(db: Session, current_user: User, payload: schemas.UserCreate, request: Optional[Request] = None,
               must_change_password: bool = False) -> User:
    """Crée un compte selon les règles de hiérarchie (sans valider la transaction)."""
    manager_id = None
    agency_number = payload.agency_number

    if payload.role == UserRole.magasinier and current_user.role in (UserRole.admin, UserRole.directeur_agence):
        agency = current_user.agency_number if current_user.role == UserRole.directeur_agence else require_agency(db, payload.agency_number)
        if not agency:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le numéro d'agence est obligatoire pour un magasinier")
        manager_id = current_user.id if current_user.role == UserRole.directeur_agence else None
        agency_number = agency
    elif current_user.role != UserRole.admin:
        expected_child = CHILD_ROLE.get(current_user.role)
        if expected_child is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{ROLE_LABELS[current_user.role]} ne peut créer aucun compte",
            )
        if payload.role != expected_child:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{ROLE_LABELS[current_user.role]} ne peut créer qu'un compte {ROLE_LABELS[expected_child]}",
            )
        manager_id = current_user.id
        agency_number = current_user.agency_number
    else:
        if payload.role == UserRole.directeur_agence:
            if not payload.agency_number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Le numéro d'agence est obligatoire pour un directeur d'agence",
                )
            manager_id = None
            agency_number = require_agency(db, payload.agency_number)
        elif payload.manager_id is not None:
            manager = db.query(User).filter(User.id == payload.manager_id).first()
            if not manager:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Responsable introuvable")
            expected_parent = PARENT_ROLE.get(payload.role)
            if expected_parent is None or manager.role != expected_parent:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Le responsable choisi doit être {ROLE_LABELS.get(expected_parent, '')}",
                )
            manager_id = manager.id
            agency_number = manager.agency_number
        else:
            manager_id = None
            agency_number = require_agency(db, payload.agency_number)

    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cet identifiant existe déjà")

    validate_password_strength(payload.password, payload.username)

    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        manager_id=manager_id,
        agency_number=agency_number,
        email=payload.email,
        phone=payload.phone,
        must_change_password=must_change_password,
    )
    db.add(user)
    db.flush()
    audit.record(
        db, "user_created", current_user.id, "user", user.id, request,
        {"username": user.username, "role": user.role.value, "agency": agency_number},
    )
    return user


@router.post("", response_model=schemas.UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: schemas.UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = build_user(db, current_user, payload, request)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=schemas.UserOut)
def get_user(user_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
    ids = visible_user_ids(db, current_user)
    if ids is not None and user.id not in ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cet utilisateur n'est pas dans votre équipe")
    return user


@router.patch("/{user_id}", response_model=schemas.UserOut)
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")

    data = payload.model_dump(exclude_unset=True)
    changed = sorted(k for k in data.keys() if k != "password")
    revoke = False

    if "password" in data:
        if data["password"]:
            validate_password_strength(data["password"], user.username)
            user.hashed_password = hash_password(data["password"])
            user.must_change_password = user.id != current_user.id
            revoke = True
            changed.append("password")
        del data["password"]

    if "agency_number" in data:
        data["agency_number"] = require_agency(db, data["agency_number"])

    if "role" in data and data["role"] != user.role:
        revoke = True
        if data["role"] == UserRole.admin:
            user.microsoft_tid = user.microsoft_oid = None
    if "email" in data and (data["email"] or "").lower() != (user.email or "").lower():
        user.microsoft_tid = user.microsoft_oid = None
    if data.get("is_active") is False and user.is_active:
        revoke = True

    for field, value in data.items():
        setattr(user, field, value)

    if revoke:
        invalidate_sessions(db, user)

    audit.record(db, "user_updated", current_user.id, "user", user.id, request, {"fields": changed})
    db.commit()
    db.refresh(user)
    return user


@router.post("/{user_id}/reset-password", response_model=schemas.TemporaryPasswordOut)
def reset_user_password(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.gars_chantier:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé aux gestionnaires")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
    if target.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Utilisez « Mon profil » pour changer votre propre mot de passe",
        )

    ids = visible_user_ids(db, current_user)
    if ids is not None and target.id not in ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cet utilisateur n'est pas dans votre équipe")

    temporary = generate_temporary_password()
    target.hashed_password = hash_password(temporary)
    target.must_change_password = True
    invalidate_sessions(db, target)
    audit.record(db, "password_reset_by_manager", current_user.id, "user", target.id, request)
    db.commit()
    return {"temporary_password": temporary}


@router.post("/{user_id}/mfa-reset", response_model=schemas.UserOut)
def reset_user_mfa(user_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    """Dépannage d'un salarié qui a perdu son téléphone."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
    target.totp_enabled, target.totp_secret, target.totp_last_step = False, None, None
    invalidate_sessions(db, target)
    audit.record(db, "mfa_reset_by_admin", current_user.id, "user", target.id, request)
    db.commit()
    db.refresh(target)
    return target


@router.post("/{user_id}/reassign-tools")
def reassign_user_tools(
    user_id: int,
    payload: schemas.ReassignRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.gars_chantier:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé aux gestionnaires")

    source = db.query(User).filter(User.id == user_id).first()
    target = db.query(User).filter(User.id == payload.to_user_id).first()
    if not source or not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
    if source.id == target.id or not target.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Destinataire invalide")

    ids = visible_user_ids(db, current_user)
    if ids is not None:
        if source.id not in ids or target.id not in ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Ces utilisateurs ne sont pas dans votre équipe"
            )
        if source.agency_number != target.agency_number:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Le destinataire doit être de la même agence"
            )

    tools = (
        db.query(PersonalTool)
        .filter(PersonalTool.current_holder_id == source.id)
        .update({"current_holder_id": target.id}, synchronize_session=False)
    )
    epis = (
        db.query(Epi)
        .filter(Epi.assigned_to_id == source.id)
        .update({"assigned_to_id": target.id}, synchronize_session=False)
    )
    dotations = (
        db.query(AgencyTool)
        .filter(AgencyTool.assigned_to_id == source.id, AgencyTool.status == AgencyToolStatus.dotation)
        .update({"assigned_to_id": target.id}, synchronize_session=False)
    )
    audit.record(
        db, "user_tools_reassigned", current_user.id, "user", source.id, request,
        {"to_user_id": target.id, "personal_tools": tools, "epi": epis, "dotations": dotations},
    )
    db.commit()
    return {"personal_tools": tools, "epi": epis, "dotations": dotations}


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Vous ne pouvez pas supprimer votre propre compte"
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")

    blocking = {label: count for label, count in _holdings(db, user.id).items() if count}
    if blocking:
        listing = ", ".join(f"{count} {label}" for label, count in blocking.items())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Suppression impossible : ce compte a encore {listing}. "
            "Réaffectez son matériel puis désactivez le compte.",
        )

    history = _history_tables(db, user.id)
    if history:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Suppression impossible : ce compte a un historique à conserver (" + ", ".join(history) + "). "
            "Désactivez-le ou anonymisez-le.",
        )

    audit.record(db, "user_deleted", current_user.id, "user", user.id, request, {"username": user.username})
    _release_references(db, user.id)
    db.delete(user)
    db.commit()
    return None
