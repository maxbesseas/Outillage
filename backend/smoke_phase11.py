# Tests de la Phase 11 (santé/readiness, versioning, purge des fichiers orphelins). Exécuté par smoke_test.py.
r = client.get("/health")
check("/health reports ok and a version", r.status_code == 200 and r.json()["status"] == "ok" and r.json()["version"])
r = client.get("/health/ready")
check("/health/ready reports ready with database and migrations checks", r.status_code == 200 and r.json()["status"] == "ready" and r.json()["checks"]["database"] == "ok" and r.json()["checks"]["migrations"] == "ok")
check("/health/ready needs no authentication", "www-authenticate" not in r.headers)
check("cleanup_orphan_uploads is registered as a job", "cleanup_orphan_uploads" in {j["name"] for j in client.get("/admin/jobs", headers=auth(admin_token)).json()})

# ---------- Purge des fichiers orphelins ----------
import time as _time11

from app import config as _cfg11
from app import uploads_cleanup as _uc11

orphan = _cfg11.UPLOAD_DIR / "tool_photos" / "agency" / "orphelin-test.jpg"
orphan.parent.mkdir(parents=True, exist_ok=True)
orphan.write_bytes(b"\x89PNG\r\n\x1a\n0000")
old_time = _time11.time() - 7200
import os as _os11
_os11.utime(orphan, (old_time, old_time))

fresh = _cfg11.UPLOAD_DIR / "tool_photos" / "agency" / "recent-test.jpg"
fresh.write_bytes(b"\x89PNG\r\n\x1a\n0000")

referenced_tool = mk3 = client.post("/agency-tools", json={"name": "Outil P11", "unique_code": "P11-1", "purchase_price": 1}, headers=auth(charge101_token)).json()["id"]
png11 = b"\x89PNG\r\n\x1a\n" + b"0" * 40
r = client.post(f"/tool-photos/agency/{referenced_tool}", files={"file": ("a.png", __import__("io").BytesIO(png11), "image/png")}, headers=auth(charge101_token))
kept_path = r.json()["path"]
kept_file = _cfg11.UPLOAD_DIR / kept_path[len("/uploads/"):]

with database.SessionLocal() as _s11:
    referenced = _uc11.referenced_paths(_s11)
check("referenced_paths finds the photo just uploaded", kept_path[len("/uploads/"):] in referenced)
check("referenced_paths does not include an orphan file", "tool_photos/agency/orphelin-test.jpg" not in referenced)

with database.SessionLocal() as _s11:
    message = _uc11.cleanup_orphan_uploads(_s11)
check("cleanup removes only old orphan files", not orphan.exists() and fresh.exists() and kept_file.exists())
check("cleanup reports what it did", "supprimé" in message)

r = client.post("/admin/jobs/cleanup_orphan_uploads/run", headers=auth(admin_token))
check("the cleanup job runs through the admin API", r.status_code == 200 and r.json()["status"] == "ok")
check("the cleanup job is admin-only", client.post("/admin/jobs/cleanup_orphan_uploads/run", headers=auth(charge101_token)).status_code == 403)
fresh.unlink(missing_ok=True)
