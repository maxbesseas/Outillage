"""Dépannage : redonne l'accès au compte admin quand son mot de passe ou son téléphone est perdu.

Usage, depuis backend/, avec OUTILLAGE_ENV, OUTILLAGE_SECRET_KEY et OUTILLAGE_DATABASE_URL définies :
    python reset_admin.py
Le nouveau mot de passe se saisit sans s'afficher. La double authentification du compte est désactivée et ses sessions sont fermées.
"""
import getpass
import os
import sys

os.environ["OUTILLAGE_AUTO_MIGRATE"] = "off"
os.environ["OUTILLAGE_SCHEDULER"] = "off"

from fastapi import HTTPException  # noqa: E402

from app import audit, database, main  # noqa: E402,F401
from app.auth import hash_password, invalidate_sessions, validate_password_strength  # noqa: E402
from app.config import DEFAULT_ADMIN_USERNAME  # noqa: E402
from app.models import User  # noqa: E402


def reset(db, password: str) -> bool:
    user = db.query(User).filter(User.username == DEFAULT_ADMIN_USERNAME).first()
    if user is None:
        return False
    user.hashed_password = hash_password(password)
    user.must_change_password = False
    user.totp_enabled, user.totp_secret, user.totp_last_step = False, None, None
    invalidate_sessions(db, user)
    audit.record(db, "admin_reset_from_server", user.id, "user", user.id)
    db.commit()
    return True


def main_cli() -> int:
    print(f"Base visée : {database.engine.url.get_backend_name()} {database.engine.url.host or database.engine.url.database}")
    password = getpass.getpass("Nouveau mot de passe admin (rien ne s'affiche) : ")
    if password != getpass.getpass("Confirmez : "):
        print("Les deux saisies sont différentes : rien n'a changé.")
        return 1
    try:
        validate_password_strength(password, DEFAULT_ADMIN_USERNAME)
    except HTTPException as exc:
        print(exc.detail)
        return 1
    db = database.SessionLocal()
    try:
        if not reset(db, password):
            print("Aucun compte admin dans cette base.")
            return 1
    finally:
        db.close()
    print("Mot de passe changé, double authentification désactivée. Connectez-vous avec le compte admin.")
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
