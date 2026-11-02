"""Point d'entrée Vercel : l'application FastAPI sert l'API et le frontend. Le disque n'est inscriptible que sous /tmp."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

os.environ.setdefault("OUTILLAGE_AUTO_MIGRATE", "off")
os.environ.setdefault("OUTILLAGE_SCHEDULER", "off")
os.environ.setdefault("OUTILLAGE_EXCEL_SYNC", "off")
os.environ.setdefault("OUTILLAGE_TRUST_PROXY", "on")
os.environ.setdefault("OUTILLAGE_MAX_UPLOAD_MB", "4")  # Vercel refuse les requêtes de plus de 4,5 Mo
os.environ.setdefault("OUTILLAGE_UPLOAD_DIR", "/tmp/uploads")
os.environ.setdefault("OUTILLAGE_BACKUP_DIR", "/tmp/backups")
os.environ.setdefault("OUTILLAGE_EXCEL_DIR", "/tmp/excel")

from app.main import app  # noqa: E402,F401
