"""Phase 8 : sauvegardes complètes (base SQLite + fichiers téléversés) avec rotation et vérification."""
import json
import re
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from sqlalchemy.orm import Session

from . import appsettings, config, migrations, utils
from .database import engine

PREFIX = "fauche-backup-"
NAME_RE = re.compile(r"^fauche-backup-\d{8}-\d{6}(?:-[a-z0-9-]{1,30})?\.zip$")


def _dir() -> Path:
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return config.BACKUP_DIR


def create_backup(label: str = "auto") -> Path:
    """Crée une archive zip : outillage.db (copie cohérente via l'API de sauvegarde SQLite), uploads/, manifest.json."""
    safe_label = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")[:30] or "manuel"
    moment = utils.now()
    target = _dir() / f"{PREFIX}{moment:%Y%m%d-%H%M%S}-{safe_label}.zip"
    while target.exists():  # deux sauvegardes dans la même seconde : on décale le nom
        moment += timedelta(seconds=1)
        target = _dir() / f"{PREFIX}{moment:%Y%m%d-%H%M%S}-{safe_label}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "outillage.db"
        src = sqlite3.connect(str(engine.url.database))
        try:
            dst = sqlite3.connect(str(db_copy))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        files = 0
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, "outillage.db")
            if config.UPLOAD_DIR.exists():
                for path in config.UPLOAD_DIR.rglob("*"):
                    if path.is_file():
                        zf.write(path, "uploads/" + path.relative_to(config.UPLOAD_DIR).as_posix())
                        files += 1
            zf.writestr("manifest.json", json.dumps({
                "created_at": utils.now().isoformat(), "schema_version": migrations.current_version(engine),
                "upload_files": files, "label": safe_label,
            }, ensure_ascii=False))
    return target


def list_backups() -> List[dict]:
    out = []
    for path in sorted(_dir().glob(f"{PREFIX}*.zip"), reverse=True):
        if not NAME_RE.match(path.name):
            continue
        stat = path.stat()
        out.append({"name": path.name, "size": stat.st_size, "created_at": datetime.utcfromtimestamp(stat.st_mtime)})
    return out


def resolve(name: str) -> Optional[Path]:
    """Ne renvoie qu'un fichier réellement présent dans la liste (aucun chemin fourni par l'appelant n'est utilisé)."""
    if not NAME_RE.match(name or ""):
        return None
    for path in _dir().glob(f"{PREFIX}*.zip"):
        if path.name == name:
            return path
    return None


def rotate(keep: int, label: str = "auto") -> int:
    """Ne supprime que les sauvegardes du même type (les sauvegardes manuelles sont conservées)."""
    removed = 0
    same = [b for b in list_backups() if b["name"].endswith(f"-{label}.zip")]
    for item in same[max(keep, 1):]:
        path = resolve(item["name"])
        if path:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def verify(path: Path) -> dict:
    """Ouvre l'archive, contrôle l'intégrité de la base et compte les données principales."""
    with zipfile.ZipFile(path) as zf:
        if zf.testzip() is not None:
            return {"ok": False, "message": "Archive corrompue"}
        names = zf.namelist()
        if "outillage.db" not in names:
            return {"ok": False, "message": "Base absente de l'archive"}
        with tempfile.TemporaryDirectory() as tmp:
            zf.extract("outillage.db", tmp)
            conn = sqlite3.connect(str(Path(tmp) / "outillage.db"))
            try:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                counts = {}
                for table in ("users", "agency_tools", "epi", "personal_tools", "loans"):
                    try:
                        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    except sqlite3.Error:
                        counts[table] = None
            finally:
                conn.close()
        manifest = json.loads(zf.read("manifest.json")) if "manifest.json" in names else {}
    return {"ok": integrity == "ok", "message": "Base saine" if integrity == "ok" else integrity, "counts": counts,
            "upload_files": sum(1 for n in names if n.startswith("uploads/")), "schema_version": manifest.get("schema_version")}


def daily_backup(db: Session) -> str:
    """Tâche planifiée : une sauvegarde par jour, à partir de l'heure réglée (UTC), puis rotation."""
    now = utils.now()
    if now.hour < appsettings.get_int(db, "backup.hour"):
        return "Pas encore l'heure de la sauvegarde"
    today = now.strftime("%Y%m%d")
    if any(b["name"].startswith(f"{PREFIX}{today}-") and b["name"].endswith("-auto.zip") for b in list_backups()):
        return "Sauvegarde du jour déjà faite"
    path = create_backup("auto")
    removed = rotate(appsettings.get_int(db, "backup.keep"))
    return f"Sauvegarde {path.name} créée ({removed} ancienne(s) supprimée(s))"
