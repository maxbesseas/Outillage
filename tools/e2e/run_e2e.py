"""Lance un serveur neuf (base et uploads temporaires) puis le parcours navigateur tools/e2e/e2e.mjs.

Usage : backend/venv/Scripts/python.exe tools/e2e/run_e2e.py   (Windows)   ou   backend/venv/bin/python tools/e2e/run_e2e.py
Nécessite Node 22+ et un navigateur Chromium (Edge/Chrome ; variable E2E_BROWSER sinon).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("E2E_PORT", "8124"))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="fauche_e2e_"))
    env = dict(os.environ)
    env.update({
        "OUTILLAGE_ENV": "dev", "OUTILLAGE_SCHEDULER": "off", "OUTILLAGE_DB_PATH": str(tmp / "e2e.db"),
        "OUTILLAGE_UPLOAD_DIR": str(tmp / "uploads"), "OUTILLAGE_BACKUP_DIR": str(tmp / "backups"),
        "OUTILLAGE_EXCEL_DIR": str(tmp / "Source"), "E2E_BASE": f"http://127.0.0.1:{PORT}",
    })
    (tmp / "Source").mkdir()
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT / "backend", env=env, stdout=open(tmp / "server.log", "w"), stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print("Le serveur ne démarre pas :\n", (tmp / "server.log").read_text(errors="replace")[-2000:])
            return 2
        code = subprocess.call(["node", str(ROOT / "tools" / "e2e" / "e2e.mjs")], env=env)
        if code:
            log = (tmp / "server.log").read_text(errors="replace")
            lines = log.splitlines()
            hits = [i for i, line in enumerate(lines) if "Traceback" in line or " 500 " in line]
            if hits:
                print("--- Extrait du journal serveur (erreurs 500) ---")
                interesting = [l for l in lines if "backend\\app" in l or "Error" in l or "Exception:" in l]
                print("\n".join(interesting[-25:]))
        return code
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
