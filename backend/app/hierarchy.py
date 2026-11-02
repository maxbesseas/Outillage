from collections import deque

from sqlalchemy.orm import Session

from .models import User, UserRole

CHILD_ROLE = {
    UserRole.admin: UserRole.directeur_agence,
    UserRole.directeur_agence: UserRole.charge_affaires,
    UserRole.charge_affaires: UserRole.gars_chantier,
}

PARENT_ROLE = {
    UserRole.charge_affaires: UserRole.directeur_agence,
    UserRole.gars_chantier: UserRole.charge_affaires,
}

ROLE_LABELS = {
    UserRole.gars_chantier: "Personnel de chantier",
    UserRole.charge_affaires: "Chargé d'affaires",
    UserRole.directeur_agence: "Directeur d'agence",
    UserRole.magasinier: "Magasinier",
    UserRole.admin: "Administrateur",
}


def get_subordinate_ids(db: Session, user: User):
    if user.role == UserRole.admin:
        return None

    visited = set()
    queue = deque([user.id])
    while queue:
        current_id = queue.popleft()
        children = db.query(User.id).filter(User.manager_id == current_id).all()
        for (child_id,) in children:
            if child_id not in visited:
                visited.add(child_id)
                queue.append(child_id)
    return visited


def visible_user_ids(db: Session, user: User):
    subordinates = get_subordinate_ids(db, user)
    if subordinates is None:
        return None
    return subordinates | {user.id}
