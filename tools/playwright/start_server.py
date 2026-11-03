"""Serveur jetable pour les tests Playwright : mode production, SQLite temporaire, données de démonstration. Jamais la base en ligne."""
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
RUN = Path(__file__).resolve().parent / ".run"
PORT = os.environ.get("QA_PORT", "8126")

tmp = Path(tempfile.mkdtemp(prefix="fauche_pw_"))
(tmp / "Source").mkdir()
admin_password = "Pw-admin-" + secrets.token_urlsafe(10) + "1"
env = {k: v for k, v in os.environ.items() if not k.startswith("OUTILLAGE_")}
env.update(
    PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", OUTILLAGE_ENV="prod", OUTILLAGE_SECRET_KEY=secrets.token_urlsafe(48), OUTILLAGE_ADMIN_PASSWORD=admin_password,
    OUTILLAGE_SCHEDULER="off", OUTILLAGE_DB_PATH=str(tmp / "pw.db"), OUTILLAGE_UPLOAD_DIR=str(tmp / "uploads"), OUTILLAGE_BACKUP_DIR=str(tmp / "backups"), OUTILLAGE_EXCEL_DIR=str(tmp / "Source"),
)
subprocess.run([sys.executable, "-W", "ignore", "-m", "app.db_setup"], cwd=BACKEND, env=env, check=True, stdout=subprocess.DEVNULL)
seed = subprocess.run([sys.executable, "-W", "ignore", "seed_demo.py", "--yes"], cwd=BACKEND, env=env, check=True, capture_output=True, text=True, encoding="utf-8").stdout
demo_password = re.search(r"(Demo-\S+)", seed).group(1)

PREPARE = """
import app.main
from app import charter, database, models
db = database.SessionLocal()
admin = db.query(models.User).filter_by(username='admin').first()
admin.must_change_password = False
admin.charter_version = charter.VERSION
for i in range(2005):
    db.add(models.AgencyTool(name=f'Outil volume {i}', type='Volume', unique_code=f'DEMO-VOL-{i:05d}', agency_number='Nantes', purchase_price=100.0))
db.commit()
"""
subprocess.run([sys.executable, "-W", "ignore", "-c", PREPARE], cwd=BACKEND, env=env, check=True)

RUN.mkdir(exist_ok=True)
(RUN / "comptes.json").write_text(json.dumps({"admin": admin_password, "demo": demo_password}), encoding="utf-8")
sys.exit(subprocess.call([sys.executable, "-W", "ignore", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", PORT], cwd=BACKEND, env=env))
