import os
from pathlib import Path

VERSION = "1.0.0"  # voir CHANGELOG.md

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(os.environ.get("OUTILLAGE_UPLOAD_DIR", str(BASE_DIR / "uploads")))
FRONTEND_DIR = BASE_DIR.parent / "frontend"
EXCEL_SOURCE_DIR = Path(os.environ.get("OUTILLAGE_EXCEL_DIR", str(BASE_DIR.parent / "Source")))
BACKUP_DIR = Path(os.environ.get("OUTILLAGE_BACKUP_DIR", str(BASE_DIR / "backups")))

DB_PATH = Path(os.environ.get("OUTILLAGE_DB_PATH", str(BASE_DIR / "outillage.db")))


def _database_url() -> str:
    url = os.environ.get("OUTILLAGE_DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{DB_PATH}"
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = _database_url()
# off : le schéma est préparé à part (python -m app.db_setup), pas à chaque démarrage à froid du serverless.
AUTO_MIGRATE = os.environ.get("OUTILLAGE_AUTO_MIGRATE", "on").strip().lower() != "off"

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
CRON_TOKEN = os.environ.get("OUTILLAGE_CRON_TOKEN") or os.environ.get("CRON_SECRET") or None
# on : uniquement derrière un proxy qui réécrit X-Forwarded-For (Vercel) ; sinon l'IP serait falsifiable.
TRUST_PROXY_HEADERS = os.environ.get("OUTILLAGE_TRUST_PROXY", "off").strip().lower() == "on"
EXCEL_SYNC_ENABLED = os.environ.get("OUTILLAGE_EXCEL_SYNC", "on").strip().lower() != "off"
MAX_UPLOAD_MB = int(os.environ.get("OUTILLAGE_MAX_UPLOAD_MB", "10"))

S3_BUCKET = os.environ.get("OUTILLAGE_S3_BUCKET", "").strip() or None
S3_ENDPOINT = os.environ.get("OUTILLAGE_S3_ENDPOINT", "").strip().rstrip("/") or None
S3_REGION = os.environ.get("OUTILLAGE_S3_REGION", "fr-par").strip()
S3_ACCESS_KEY = os.environ.get("OUTILLAGE_S3_ACCESS_KEY") or None
S3_SECRET_KEY = os.environ.get("OUTILLAGE_S3_SECRET_KEY") or None

# Connexion Microsoft : désactivée tant que l'application Entra n'est pas renseignée.
MS_CLIENT_ID = os.environ.get("OUTILLAGE_MS_CLIENT_ID", "").strip() or None
MS_CLIENT_SECRET = os.environ.get("OUTILLAGE_MS_CLIENT_SECRET") or None
MS_TENANT = os.environ.get("OUTILLAGE_MS_TENANT", "common").strip()

PASSWORD_MIN_LENGTH = 12 if IS_PROD else 8
CHARTER_ENFORCED = IS_PROD

LOGIN_MAX_FAILURES_USER = 5
LOGIN_MAX_FAILURES_IP = 15
LOGIN_MAX_FAILURES_ACCOUNT = 30

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"  # développement uniquement : en production, voir OUTILLAGE_ADMIN_PASSWORD
ADMIN_PASSWORD = os.environ.get("OUTILLAGE_ADMIN_PASSWORD") or None


def initial_admin_password():
    """Mot de passe du tout premier compte admin ; None en production s'il n'a pas été fourni (aucun compte créé)."""
    return ADMIN_PASSWORD or (None if IS_PROD else DEFAULT_ADMIN_PASSWORD)


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
    if is_prod and ADMIN_PASSWORD == DEFAULT_ADMIN_PASSWORD:
        raise RuntimeError("OUTILLAGE_ADMIN_PASSWORD ne doit pas reprendre le mot de passe de développement.")
    if is_prod and DATABASE_URL.startswith("postgresql") and not any(
        f"sslmode={mode}" in DATABASE_URL for mode in ("require", "verify-ca", "verify-full")
    ):
        raise RuntimeError("La connexion PostgreSQL doit être chiffrée : ajoutez sslmode=require (ou verify-full) à l'URL.")
