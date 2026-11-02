"""Phase 11 : purge des fichiers orphelins sous uploads/ (jamais référencés en base, ou dont la référence a été supprimée)."""
import time
from pathlib import Path
from typing import Set

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from . import config, storage
from .database import Base, engine

# Sécurité : un fichier tout juste déposé peut ne pas encore être commité en base (upload en cours).
MIN_AGE_SECONDS = 3600


def referenced_paths(db: Session) -> Set[str]:
    """Toutes les valeurs de colonnes '*path*' sur les tables du schéma, sous forme de chemins relatifs à uploads/."""
    referenced: Set[str] = set()
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        if table.name not in existing_tables:
            continue
        path_columns = [c for c in table.columns if c.name.endswith("path") and str(c.type).upper().startswith(("VARCHAR", "STRING", "TEXT"))]
        if not path_columns:
            continue
        rows = db.execute(table.select().with_only_columns(*path_columns)).fetchall()
        for row in rows:
            for value in row:
                if isinstance(value, str) and value.startswith("/uploads/"):
                    referenced.add(value[len("/uploads/"):])
    return referenced


def _cleanup_remote(db: Session) -> str:
    referenced = referenced_paths(db)
    now = time.time()
    removed, checked = 0, 0
    for rel, modified in storage.list_files():
        checked += 1
        if rel not in referenced and now - modified >= MIN_AGE_SECONDS:
            storage.delete(rel)
            removed += 1
    return f"{removed} fichier(s) orphelin(s) supprimé(s) sur {checked} vérifié(s)"


def cleanup_orphan_uploads(db: Session) -> str:
    if storage.enabled():
        return _cleanup_remote(db)
    if not config.UPLOAD_DIR.exists():
        return "Dossier uploads absent"
    referenced = referenced_paths(db)
    now = time.time()
    removed, checked = 0, 0
    for path in config.UPLOAD_DIR.rglob("*"):
        if not path.is_file():
            continue
        checked += 1
        rel = path.relative_to(config.UPLOAD_DIR).as_posix()
        if rel in referenced:
            continue
        try:
            if now - path.stat().st_mtime < MIN_AGE_SECONDS:
                continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    for folder in sorted(config.UPLOAD_DIR.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if folder.is_dir():
            try:
                folder.rmdir()  # ne supprime que les dossiers devenus vides
            except OSError:
                pass
    return f"{removed} fichier(s) orphelin(s) supprimé(s) sur {checked} vérifié(s)"
