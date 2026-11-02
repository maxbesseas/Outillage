import os
import shutil
import tempfile
from pathlib import Path

os.environ["OUTILLAGE_ENV"] = "dev"
os.environ["OUTILLAGE_SCHEDULER"] = "off"
os.environ["OUTILLAGE_CRON_TOKEN"] = "cron-test-token"

TMP_DIR = Path(tempfile.mkdtemp(prefix="outillage_smoke_"))
os.environ["OUTILLAGE_BACKUP_DIR"] = str(TMP_DIR / "backups")
os.environ["OUTILLAGE_EXCEL_DIR"] = str(TMP_DIR / "Source")
os.environ["OUTILLAGE_UPLOAD_DIR"] = str(TMP_DIR / "uploads")

DB_PATH = TMP_DIR / "outillage.db"

import app.config as config  # noqa: E402

config.DATABASE_URL = f"sqlite:///{DB_PATH}"
config.EXCEL_SOURCE_DIR = Path(os.environ["OUTILLAGE_EXCEL_DIR"])
config.EXCEL_SOURCE_DIR.mkdir(parents=True, exist_ok=True)

import app.database as database  # noqa: E402
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

database.engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})
database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)

import app.excel_export as excel_export  # noqa: E402
excel_export.EXCEL_SOURCE_DIR = config.EXCEL_SOURCE_DIR

from openpyxl import Workbook  # noqa: E402

def make_agency_workbook(agency_number):
    wb = Workbook()
    ws = wb.active
    ws.append(excel_export.COLUMNS)
    path = config.EXCEL_SOURCE_DIR / f"Inventaire matériel {agency_number}.xlsx"
    wb.save(path)
    return path


make_agency_workbook("101")
make_agency_workbook("202")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

results = []


def check(label, cond):
    results.append((label, cond))
    print(("OK   " if cond else "FAIL "), label)


def login(username, password="password123"):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, (username, r.text)
    return r.json()["access_token"]


def pdt(value):
    """Date renvoyée par l'API (UTC, suffixe Z) -> datetime naïf UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


admin_token = login("admin", "admin123")

for agency_name in ("101", "202"):
    r = client.post("/agencies", json={"name": agency_name}, headers=auth(admin_token))
    assert r.status_code == 201, r.text

# --- Hierarchy creation ---
r = client.post("/users", json={
    "username": "directeur101", "full_name": "Directeur 101", "role": "directeur_agence",
    "password": "password123", "agency_number": "101",
}, headers=auth(admin_token))
check("admin creates directeur with agency", r.status_code == 201)

r = client.post("/users", json={
    "username": "directeur_noagency", "full_name": "Directeur X", "role": "directeur_agence",
    "password": "password123",
}, headers=auth(admin_token))
check("admin creating directeur without agency fails", r.status_code == 400)

dir101_token = login("directeur101")

r = client.post("/users", json={
    "username": "charge101", "full_name": "Charge 101", "role": "charge_affaires", "password": "password123",
}, headers=auth(dir101_token))
check("directeur creates charge_affaires (inherits agency)", r.status_code == 201 and r.json()["agency_number"] == "101")

r = client.post("/users", json={
    "username": "bad_role", "full_name": "Bad", "role": "gars_chantier", "password": "password123",
}, headers=auth(dir101_token))
check("directeur cannot create gars_chantier directly", r.status_code == 400)

charge101_token = login("charge101")

r = client.post("/users", json={
    "username": "gars101a", "full_name": "Gars 101 A", "role": "gars_chantier", "password": "password123",
}, headers=auth(charge101_token))
check("charge_affaires creates gars_chantier", r.status_code == 201)

r = client.post("/users", json={
    "username": "gars101b", "full_name": "Gars 101 B", "role": "gars_chantier", "password": "password123",
}, headers=auth(charge101_token))
check("charge_affaires creates second gars_chantier", r.status_code == 201)

gars101a_token = login("gars101a")

r = client.post("/users", json={
    "username": "nope", "full_name": "Nope", "role": "gars_chantier", "password": "password123",
}, headers=auth(gars101a_token))
check("gars_chantier cannot create anyone", r.status_code == 400)

# Second agency branch (parallel), to test visibility isolation
r = client.post("/users", json={
    "username": "directeur202", "full_name": "Directeur 202", "role": "directeur_agence",
    "password": "password123", "agency_number": "202",
}, headers=auth(admin_token))
check("admin creates second directeur", r.status_code == 201)
dir202_token = login("directeur202")

r = client.post("/users", json={
    "username": "charge202", "full_name": "Charge 202", "role": "charge_affaires", "password": "password123",
}, headers=auth(dir202_token))
check("second branch charge_affaires created", r.status_code == 201)
charge202_token = login("charge202")

# --- Personal tools + cascade visibility ---
r = client.post("/personal-tools", json={
    "name": "Perceuse Gars A", "unique_code": "PERSO-001", "state": 5,
}, headers=auth(gars101a_token))
check("gars101a creates personal tool", r.status_code == 201)
tool_a_id = r.json()["id"]

r = client.get(f"/personal-tools?owner_id={r.json()['owner_id']}", headers=auth(charge101_token))
check("direct manager sees subordinate's tool", r.status_code == 200 and len(r.json()) == 1)

r = client.get("/personal-tools", headers=auth(charge202_token))
tool_codes = [t["unique_code"] for t in r.json()]
check("parallel branch does not see other agency's personal tool", "PERSO-001" not in tool_codes)

r = client.get("/personal-tools", headers=auth(dir101_token))
tool_codes = [t["unique_code"] for t in r.json()]
check("agency director sees whole agency's personal tools", "PERSO-001" in tool_codes)

r = client.get("/personal-tools", headers=auth(admin_token))
tool_codes = [t["unique_code"] for t in r.json()]
check("admin sees everything", "PERSO-001" in tool_codes)

# Edit rights: manager in cascade can edit; outsider cannot
r = client.patch(f"/personal-tools/{tool_a_id}", json={"state": 4}, headers=auth(charge101_token))
check("manager in cascade can edit subordinate's tool", r.status_code == 200 and r.json()["state"] == 4)

r = client.patch(f"/personal-tools/{tool_a_id}", json={"state": 3}, headers=auth(charge202_token))
check("manager outside cascade cannot edit tool", r.status_code == 403)

r = client.delete(f"/personal-tools/{tool_a_id}", headers=auth(charge101_token))
check("manager (not owner) cannot delete tool", r.status_code == 403)

# --- Excel mirror check ---
wb_path = config.EXCEL_SOURCE_DIR / "Inventaire matériel 101.xlsx"
from openpyxl import load_workbook
wb = load_workbook(wb_path)
ws = wb.active
check("excel mirror row written for personal tool", ws.cell(row=2, column=1).value == "MAT001")
check("excel mirror has correct reference", ws.cell(row=2, column=2).value == "PERSO-001")

# --- Notification best-effort (no SMTP configured) ---
r = client.patch(f"/personal-tools/{tool_a_id}/state", json={
    "state": 1, "state_reason": "endommage", "state_comment": "Cassé sur chantier",
}, headers=auth(gars101a_token))
check("state update succeeds even without SMTP configured", r.status_code == 200)
check("X-Notification header present and non-blocking", r.headers.get("X-Notification") not in (None, ""))

# Reset tool state to normal for further transfer tests
client.patch(f"/personal-tools/{tool_a_id}/state", json={"state": 5, "state_reason": "normal"}, headers=auth(gars101a_token))

# --- Agency tools isolation ---
r = client.post("/agency-tools", json={
    "name": "Echelle", "unique_code": "AGY-101-1", "purchase_price": 200,
}, headers=auth(charge101_token))
check("charge_affaires creates agency tool", r.status_code == 201)
agy101_tool_id = r.json()["id"]

r = client.post("/agency-tools", json={
    "name": "Echelle 202", "unique_code": "AGY-202-1", "purchase_price": 150,
}, headers=auth(charge202_token))
check("second agency creates its own tool", r.status_code == 201)

r = client.get(f"/agency-tools/{agy101_tool_id}", headers=auth(charge202_token))
check("cross-agency read blocked", r.status_code == 403)

r = client.get("/agency-tools", headers=auth(charge202_token))
codes = [t["unique_code"] for t in r.json()]
check("agency tool list scoped to own agency", "AGY-101-1" not in codes)

r = client.post(f"/agency-tools/{agy101_tool_id}/control", json={"state": 5, "status": "disponible"}, headers=auth(charge202_token))
check("cross-agency control blocked", r.status_code == 403)

# --- Loans scoping + overlap ---
r = client.post("/loans", json={
    "tool_id": agy101_tool_id, "start_datetime": "2026-01-01T08:00:00", "end_datetime_planned": "2026-01-01T10:00:00",
}, headers=auth(gars101a_token))
check("create loan", r.status_code == 201)
loan_id = r.json()["id"]

r = client.post("/loans", json={
    "tool_id": agy101_tool_id, "start_datetime": "2026-01-01T09:00:00", "end_datetime_planned": "2026-01-01T11:00:00",
}, headers=auth(login("gars101b")))
check("overlapping loan rejected", r.status_code == 400)

r = client.get("/loans?scope=agency", headers=auth(charge101_token))
check("scope=agency shows loan", any(l["id"] == loan_id for l in r.json()))

r = client.get("/loans?scope=mine", headers=auth(login("gars101b")))
check("scope=mine excludes other's loan", not any(l["id"] == loan_id for l in r.json()))

r = client.post(f"/loans/{loan_id}/return", json={"state_after": 5}, headers=auth(gars101a_token))
check("loan return works", r.status_code == 200 and r.json()["status"] == "termine")

r = client.get(f"/agency-tools/{agy101_tool_id}", headers=auth(charge101_token))
check("tool back to disponible after return", r.json()["status"] == "disponible")

# --- Dotation rules ---
r = client.patch(f"/agency-tools/{agy101_tool_id}", json={"status": "dotation"}, headers=auth(charge101_token))
check("dotation without assigned_to_id rejected", r.status_code == 400)

r = client.patch(f"/agency-tools/{agy101_tool_id}", json={"status": "dotation", "assigned_to_id": tool_a_id and 1}, headers=auth(charge101_token))
# use admin id=1 as assignee just to test acceptance path
check("dotation with assigned_to_id accepted", r.status_code == 200 and r.json()["status"] == "dotation")

r = client.patch(f"/agency-tools/{agy101_tool_id}", json={"status": "disponible"}, headers=auth(charge101_token))
check("assigned_to_id cleared when leaving dotation", r.status_code == 200 and r.json()["assigned_to_id"] is None)

# --- Transfers (external) cycle ---
r = client.post("/transfers", json={
    "tool_id": tool_a_id, "to_external_name": "Sous-traitant X", "to_external_type": "sous_traitant",
}, headers=auth(gars101a_token))
check("create external transfer", r.status_code == 201)
transfer_id = r.json()["id"]

r = client.get(f"/personal-tools/{tool_a_id}", headers=auth(gars101a_token))
check("holder is None while tool lent externally", r.json()["current_holder_id"] is None)

r = client.post("/transfers", json={
    "tool_id": tool_a_id, "to_external_name": "Autre X", "to_external_type": "autre",
}, headers=auth(gars101a_token))
check("second transfer on same tool rejected while active", r.status_code == 400)

r = client.post(f"/transfers/{transfer_id}/return", json={"state_after": 5}, headers=auth(gars101a_token))
check("transfer return works", r.status_code == 200)

r = client.get(f"/personal-tools/{tool_a_id}", headers=auth(gars101a_token))
check("holder restored after external return", r.json()["current_holder_id"] is not None)

# --- Peer transfers cycle ---
r_users = client.get("/users", headers=auth(admin_token)).json()
gars_b = next(u for u in r_users if u["username"] == "gars101b")
gars_a = next(u for u in r_users if u["username"] == "gars101a")

r = client.post("/peer-transfers", json={
    "direction": "je_donne", "tool_code": "PERSO-001", "counterpart_id": gars_b["id"],
}, headers=auth(gars101a_token))
check("peer transfer declared", r.status_code == 201)
pt_id = r.json()["id"]

r = client.post(f"/peer-transfers/{pt_id}/confirm", headers=auth(gars101a_token))
check("declarant cannot self-confirm", r.status_code == 403)

gars101b_token = login("gars101b")

r = client.post("/peer-transfers", json={
    "direction": "je_donne", "tool_code": "PERSO-001", "counterpart_id": gars_a["id"],
}, headers=auth(gars101b_token))
check("non-holder cannot declare 'je_donne' on this tool", r.status_code == 403)

charge101_users = [u for u in r_users if u["username"] == "charge101"]
r = client.post("/peer-transfers", json={
    "direction": "je_donne", "tool_code": "PERSO-001", "counterpart_id": charge101_users[0]["id"],
}, headers=auth(gars101a_token))
check("concurrent peer transfer on same tool rejected", r.status_code == 400)

r = client.post(f"/peer-transfers/{pt_id}/confirm", headers=auth(gars101b_token))
check("counterpart confirms peer transfer", r.status_code == 200)

r = client.get(f"/personal-tools/{tool_a_id}", headers=auth(gars101a_token))
check("holder updated to receiver after confirm", r.json()["current_holder_id"] == gars_b["id"])

r = client.post(f"/peer-transfers/{pt_id}/return", json={"state_after": 5}, headers=auth(gars101b_token))
check("peer transfer return works", r.status_code == 200)

r = client.get(f"/personal-tools/{tool_a_id}", headers=auth(gars101a_token))
check("holder restored to original giver after return", r.json()["current_holder_id"] == gars_a["id"])

# --- Financial summary scoping ---
r = client.get("/agency-tools/financial-summary", headers=auth(gars101a_token))
check("financial summary blocked for gars_chantier", r.status_code == 403)

r = client.get("/agency-tools/financial-summary", headers=auth(charge101_token))
check("financial summary scoped for manager", r.status_code == 200 and r.json().get("by_agency") is None)

r = client.get("/agency-tools/financial-summary", headers=auth(admin_token))
check("financial summary includes by_agency for admin", r.status_code == 200 and r.json().get("by_agency") is not None)

# --- Settings ---
r = client.get("/settings", headers=auth(charge101_token))
check("settings blocked for non-admin", r.status_code == 403)

r = client.patch("/settings", json={"magasinier_email": "mag@example.com", "smtp_password": "secret123"}, headers=auth(admin_token))
check("settings update by admin works", r.status_code == 200)
check("smtp password never returned in clear", "smtp_password" not in r.json() and r.json()["smtp_password_set"] is True)

r = client.patch("/settings", json={"smtp_password": ""}, headers=auth(admin_token))
check("empty password in update does not erase existing", r.status_code == 200 and r.json()["smtp_password_set"] is True)

# --- EPI ---
r = client.post("/epi", json={"name": "Casque", "unique_code": "EPI-1"}, headers=auth(gars101a_token))
check("gars_chantier can create own EPI", r.status_code == 201 and r.json()["assigned_to_id"] == gars_a["id"])
epi_id = r.json()["id"]

r = client.post("/epi", json={"name": "Casque202", "unique_code": "EPI-202"}, headers=auth(charge202_token))
epi202_id = r.json()["id"]

r = client.get(f"/epi/{epi202_id}", headers=auth(charge101_token))
check("epi cross-agency read blocked", r.status_code == 403)

r = client.post(f"/epi/{epi_id}/control", json={"state": 2}, headers=auth(gars101a_token))
check("epi self-control by assigned wearer allowed", r.status_code == 200)

r = client.delete(f"/epi/{epi_id}", headers=auth(charge101_token))
check("epi delete blocked for non-admin", r.status_code == 403)
r = client.delete(f"/epi/{epi_id}", headers=auth(admin_token))
check("epi delete allowed for admin", r.status_code == 204)

# --- Export ---
r = client.get("/agency-tools/export", headers=auth(charge202_token))
check("export returns correct mime type", r.headers["content-type"].startswith("application/vnd.openxmlformats"))
check("export has content-disposition attachment", "attachment" in r.headers.get("content-disposition", ""))

exec(compile(Path(__file__).with_name("smoke_phase0.py").read_text(encoding="utf-8"), "smoke_phase0.py", "exec"), globals())

exec(compile(Path(__file__).with_name("smoke_phase1.py").read_text(encoding="utf-8"), "smoke_phase1.py", "exec"), globals())

exec(compile(Path(__file__).with_name("smoke_phase2.py").read_text(encoding="utf-8"), "smoke_phase2.py", "exec"), globals())

exec(compile(Path(__file__).with_name("smoke_phase4.py").read_text(encoding="utf-8"), "smoke_phase4.py", "exec"), globals())

exec(compile(Path(__file__).with_name("smoke_phase5.py").read_text(encoding="utf-8"), "smoke_phase5.py", "exec"), globals())

exec(compile(Path(__file__).with_name("smoke_phase3.py").read_text(encoding="utf-8"), "smoke_phase3.py", "exec"), globals())

exec(compile(Path(__file__).with_name("smoke_phase6.py").read_text(encoding="utf-8"), "smoke_phase6.py", "exec"), globals())

exec(compile(Path(__file__).with_name("smoke_phase7.py").read_text(encoding="utf-8"), "smoke_phase7.py", "exec"), globals())

exec(compile(Path(__file__).with_name("smoke_phase8.py").read_text(encoding="utf-8"), "smoke_phase8.py", "exec"), globals())

exec(compile(Path(__file__).with_name("smoke_phase9.py").read_text(encoding="utf-8"), "smoke_phase9.py", "exec"), globals())

exec(compile(Path(__file__).with_name("smoke_phase11.py").read_text(encoding="utf-8"), "smoke_phase11.py", "exec"), globals())
exec(compile(Path(__file__).with_name("smoke_phase12.py").read_text(encoding="utf-8"), "smoke_phase12.py", "exec"), globals())





failures = [label for label, cond in results if not cond]
print()
print(f"TOTAL: {len(results)}  FAILED: {len(failures)}")
if failures:
    print("FAILURES:")
    for f in failures:
        print(" -", f)

shutil.rmtree(TMP_DIR, ignore_errors=True)

if failures:
    raise SystemExit(1)
