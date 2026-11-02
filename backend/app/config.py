import os
from pathlib import Path

VERSION = "1.0.0"  # voir CHANGELOG.md

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(os.environ.get("OUTILLAGE_UPLOAD_DIR", str(BASE_DIR / "uploads")))
FRONTEND_DIR = BASE_DIR.parent / "frontend"
EXCEL_SOURCE_DIR = Path(os.environ.get("OUTILLAGE_EXCEL_DIR", str(BASE_DIR.parent / "Source")))
BACKUP_DIR = Path(os.environ.get("OUTILLAGE_BACKUP_DIR", str(BASE_DIR / "backups")))

DB_PATH = Path(os.environ.get("OUTILLAGE_DB_PATH", str(BASE_DIR / "outillage.db")))
DATABASE_URL = f"sqlite:///{DB_PATH}"

ENV = os.environ.get("OUTILLAGE_ENV", "prod").strip().lower()
IS_PROD = ENV != "dev"

DEFAULT_SECRET_KEY = "change-moi-en-production-cle-secrete-longue"
SECRET_KEY = os.environ.get("OUTILLAGE_SECRET_KEY", DEFAULT_SECRET_KEY)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("OUTILLAGE_ACCESS_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("OUTILLAGE_REFRESH_DAYS", "30"))
PASSWORD_RESET_EXPIRE_MINUTES = 30

CORS_ORIGINS = [o.strip() for o in os.environ.get("OUTILLAGE_CORS_ORIGINS", "").split(",") if o.strip()]
PUBLIC_URL = os.environ.get("OUTILLAGE_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")

SCHEDULER_ENABLED = os.environ.get("OUTILLAGE_SCHEDULER", "on").strip().lower() != "off"
CRON_TOKEN = os.environ.get("OUTILLAGE_CRON_TOKEN") or None

LOGIN_MAX_FAILURES_USER = 5
LOGIN_MAX_FAILURES_IP = 15

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXCEL_SOURCE_DIR.mkdir(parents=True, exist_ok=True)


def validate_startup(is_prod=None, secret_key=None):
    is_prod = IS_PROD if is_prod is None else is_prod
    secret_key = SECRET_KEY if secret_key is None else secret_key
    if is_prod and secret_key == DEFAULT_SECRET_KEY:
        raise RuntimeError(
            "OUTILLAGE_SECRET_KEY utilise encore la valeur par défaut. "
            "Définissez une clé secrète longue et aléatoire, ou lancez avec OUTILLAGE_ENV=dev en développement."
        )
