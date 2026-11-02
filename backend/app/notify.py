from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from . import utils
from .models import User, UserRole
from .models_ext import Notification, NotificationPreference

MANAGER_ROLES = (UserRole.directeur_agence, UserRole.charge_affaires, UserRole.magasinier)

# type -> (libellé, gravité par défaut)
TYPES = {
    "loan_overdue": ("Réservation en retard", "warning"),
    "loan_ending_soon": ("Réservation qui se termine bientôt", "info"),
    "transfer_overdue": ("Prêt externe en retard", "warning"),
    "peer_pending": ("Transfert entre collègues à confirmer", "info"),
    "epi_expiring": ("EPI bientôt périmé", "warning"),
    "epi_expired": ("EPI périmé", "critical"),
    "warranty_expiring": ("Garantie bientôt expirée", "info"),
    "control_due": ("Contrôle à faire", "warning"),
    "calibration_due": ("Étalonnage à faire", "warning"),
    "qualification_expiring": ("Habilitation bientôt expirée", "warning"),
    "repair_long": ("Outil longtemps en réparation", "warning"),
    "tool_problem": ("Outil signalé hors service ou perdu", "critical"),
    "weekly_summary": ("Résumé hebdomadaire", "info"),
    "waitlist_available": ("Outil disponible (liste d'attente)", "info"),
    "loan_approval": ("Réservation à valider", "info"),
    "no_show": ("Réservation non retirée", "warning"),
    "maintenance_update": ("Ticket de maintenance", "info"),
    "stock_low": ("Stock bas", "warning"),
    "agency_transfer": ("Transfert entre agences", "info"),
    "generic": ("Information", "info"),
}


def type_label(type_: str) -> str:
    return TYPES.get(type_, (type_, "info"))[0]


def default_preference(user: User, type_: str) -> dict:
    severity = TYPES.get(type_, ("", "info"))[1]
    is_manager = user.role != UserRole.gars_chantier
    return {
        "in_app": True,
        "email": bool(is_manager and severity in ("warning", "critical")) or type_ == "weekly_summary",
        "push": True,
    }


def resolve_preference(db: Session, user: User, type_: str) -> dict:
    row = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user.id, NotificationPreference.type == type_)
        .first()
    )
    if row is not None:
        return {"in_app": row.in_app, "email": row.email, "push": row.push}
    return default_preference(user, type_)


def chain_managers(db: Session, user: User, levels: int = 3) -> List[User]:
    result = []
    current = user
    for _ in range(levels):
        if current.manager_id is None:
            break
        manager = db.query(User).filter(User.id == current.manager_id).first()
        if manager is None or not manager.is_active:
            break
        result.append(manager)
        current = manager
    return result


def agency_managers(db: Session, agency_number: Optional[str]) -> List[User]:
    if not agency_number:
        return []
    return (
        db.query(User)
        .filter(User.agency_number == agency_number, User.is_active.is_(True), User.role.in_(MANAGER_ROLES))
        .all()
    )


def create(
    db: Session,
    user_id: Optional[int],
    type_: str,
    title: str,
    body: Optional[str] = None,
    severity: Optional[str] = None,
    entity_kind: Optional[str] = None,
    entity_id=None,
    link: Optional[str] = None,
    dedup_key: Optional[str] = None,
) -> Optional[Notification]:
    if user_id is None:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        return None

    if dedup_key:
        existing = (
            db.query(Notification.id)
            .filter(Notification.user_id == user_id, Notification.dedup_key == dedup_key)
            .first()
        )
        if existing:
            return None

    pref = resolve_preference(db, user, type_)
    notification = Notification(
        user_id=user_id,
        type=type_,
        severity=severity or TYPES.get(type_, ("", "info"))[1],
        title=title,
        body=body,
        entity_kind=entity_kind,
        entity_id=str(entity_id) if entity_id is not None else None,
        link=link,
        dedup_key=dedup_key,
        in_app=pref["in_app"],
        email_wanted=pref["email"],
        created_at=utils.now(),
    )
    db.add(notification)
    db.flush()

    if pref["push"]:
        try:
            from . import webpush

            sent, _ = webpush.send_to_user(
                db, user_id, {"title": title, "body": body or "", "url": link or "#/notifications", "tag": type_}
            )
            if sent:
                notification.pushed_at = utils.now()
        except Exception:
            pass
    return notification


def create_many(db: Session, users: Iterable[User], *args, dedup_prefix: Optional[str] = None, **kwargs) -> int:
    count = 0
    seen = set()
    for user in users:
        if user is None or user.id in seen:
            continue
        seen.add(user.id)
        key = f"{dedup_prefix}:{user.id}" if dedup_prefix else None
        if create(db, user.id, *args, dedup_key=key, **kwargs):
            count += 1
    return count


def on_tool_problem(db: Session, kind: str, tool, actor_id: Optional[int], reason: str):
    """Doublon interne du mail au magasinier : alerte les managers et magasiniers de l'agence."""
    agency = getattr(tool, "agency_number", None)
    recipients = agency_managers(db, agency)
    if kind == "personal":
        owner = db.query(User).filter(User.id == tool.owner_id).first()
        if owner:
            recipients = recipients + chain_managers(db, owner) + [owner]
    link = "#/agence" if kind == "agency" else "#/mes-outils"
    create_many(
        db,
        [u for u in recipients if u.id != actor_id],
        "tool_problem",
        f"Outil signalé : {tool.name}",
        f"{tool.name} ({tool.unique_code}) : {reason}",
        entity_kind=kind,
        entity_id=tool.id,
        link=link,
        dedup_prefix=f"tool_problem:{kind}:{tool.id}:{reason}:{utils.now().date()}",
    )
    try:
        from . import maintenance

        actor = db.query(User).filter(User.id == actor_id).first() if actor_id else None
        maintenance.open_ticket_if_needed(db, kind, tool, actor, reason)
    except ImportError:
        pass
