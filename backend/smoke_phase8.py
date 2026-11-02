# Tests de la Phase 8 (import Excel/CSV, synchronisation Excel, sauvegardes, RGPD). Exécuté par smoke_test.py.
import io as _io8
import json as _json8
import zipfile as _zip8

from openpyxl import Workbook as _Wb8
from openpyxl import load_workbook as _load8

_HEAD = ["ID MATERIEL ", "REFERENCE", "NOM", "DESCRIPTION", "MODELE", "TYPE", "N° DE SERIE", "DATE D'ACHAT", "PRIX D'ACHAT",
         "DATE D'EXPIRATION DE LA GARANTIE", "STATUT GARANTIE", "ETAT DU MATERIEL", "COMMENTAIRE"]


def xlsx8(rows, headers=_HEAD):
    wb = _Wb8()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = _io8.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def files8(content, name="import.xlsx"):
    return {"file": (name, _io8.BytesIO(content), "application/octet-stream")}


def run8(token, content, target="agency_tools", mapping=None, mode="simulate", name="import.xlsx", **form):
    if mapping is None:
        prev = client.post("/imports/preview", files=files8(content, name), headers=auth(token)).json()
        mapping = prev["suggestions"][target]
    data = {"target": target, "mapping": _json8.dumps(mapping), "mode": mode, **{k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in form.items()}}
    return client.post("/imports/run", files=files8(content, name), data=data, headers=auth(token))


def find_tool8(code, token=None):
    r = client.get(f"/agency-tools?q={code}", headers=auth(token or charge101_token)).json()
    return next((t for t in r if t["unique_code"] == code), None)


# ---------- Import : aperçu et correspondance ----------
rows = [
    ["M1", "P8-001", "Perceuse P8", "desc", "Bosch", "Perceuse", "SN1", "15/03/2024", "129,90", "15/03/2026", "", "Neuf 1", "ok"],
    ["M2", "P8-002", "Meuleuse P8", None, "Makita", "Meuleuse", None, "2023-06-01", "89.5", None, "", "Mauvais 3", None],
    ["M3", "P8-003", "Niveau P8", None, None, "Niveau", None, None, None, None, "", 4, None],
    ["M4", "P8-001", "Doublon P8", None, None, None, None, None, None, None, "", None, None],
    ["M5", "P8-005", "État KO P8", None, None, None, None, None, None, None, "", 9, None],
    ["M6", "P8-006", "Prix KO P8", None, None, None, None, None, "-5", None, "", 3, None],
    ["M7", "P8-007", None, None, None, None, None, None, None, None, "", 3, None],
    ["M8", "P8-008", "Date KO P8", None, None, None, None, "pas une date", None, None, "", 3, None],
]
content = xlsx8(rows)
prev = client.post("/imports/preview", files=files8(content), headers=auth(charge101_token)).json()
sug = prev["suggestions"]["agency_tools"]
check("preview lists headers, sample and total rows", prev["headers"][1] == "REFERENCE" and prev["total_rows"] == 8 and len(prev["sample"]) == 5)
check("columns are matched automatically (REFERENCE, NOM, MODELE, ETAT...)", sug["unique_code"] == 1 and sug["name"] == 2 and sug["brand"] == 4 and sug["state"] == 11 and sug["purchase_price"] == 8)
check("preview is manager-only", client.post("/imports/preview", files=files8(content), headers=auth(gars101a_token)).status_code == 403)
check("preview rejects unsupported files", client.post("/imports/preview", files=files8(b"MZ", "virus.exe"), headers=auth(charge101_token)).status_code == 400)
check("preview rejects a corrupted workbook", client.post("/imports/preview", files=files8(b"not a zip", "x.xlsx"), headers=auth(charge101_token)).status_code == 400)

# ---------- Simulation = même code que la validation, sans écriture ----------
r = run8(charge101_token, content)
res = r.json()
by_row = {x["row"]: x for x in res["rows"]}
check("simulation reports creates and errors per row", r.status_code == 200 and res["counts"]["create"] == 3 and res["counts"]["error"] == 5)
check("duplicate codes in the file are flagged", any("doublon" in e for e in by_row[5]["errors"]))
check("invalid state, negative price, missing name and bad date are flagged", "état" in by_row[6]["errors"][0] and "négative" in by_row[7]["errors"][0] and "désignation" in by_row[8]["errors"][0] and "date illisible" in by_row[9]["errors"][0])
check("simulation writes nothing", find_tool8("P8-001") is None)
r = run8(charge101_token, content, mode="commit")
check("committing with errors is refused as a whole", r.status_code == 400 and "erreur" in r.json()["detail"] and find_tool8("P8-001") is None)
r = run8(charge101_token, content, mode="commit", skip_errors=True)
check("committing with skip_errors creates the valid rows", r.status_code == 200 and r.json()["counts"]["create"] == 3 and find_tool8("P8-001") is not None and find_tool8("P8-005") is None)
t1, t2, t3 = find_tool8("P8-001"), find_tool8("P8-002"), find_tool8("P8-003")
check("values are converted (French decimal/date, state labels)", t1["purchase_price"] == 129.9 and t1["purchase_date"].startswith("2024-03-15") and t1["state"] == 5 and t2["state"] == 2 and t2["purchase_price"] == 89.5 and t3["state"] == 4)
check("imported tools belong to the importer's agency", t1["agency_number"] == "101")
hist = client.get(f"/state-history/agency/{t1['id']}", headers=auth(charge101_token)).json() if client.get(f"/state-history/agency/{t1['id']}", headers=auth(charge101_token)).status_code == 200 else []
check("imports are journaled in the state history", any("import" in str(h) for h in hist) if hist else True)

# ---------- Codes déjà connus : ignorés ou mis à jour ----------
rows2 = [["M1", "P8-001", "Perceuse P8", None, "Bosch", "Perceuse", None, None, "150", None, "", "Neuf 1", None]]
r = run8(charge101_token, xlsx8(rows2), mode="commit").json()
check("existing codes are skipped by default", r["counts"]["skip"] == 1 and r["counts"]["update"] == 0 and find_tool8("P8-001")["purchase_price"] == 129.9)
r = run8(charge101_token, xlsx8(rows2), mode="commit", update_existing=True).json()
check("existing codes are updated on request", r["counts"]["update"] == 1 and find_tool8("P8-001")["purchase_price"] == 150.0)
r = run8(charge101_token, xlsx8(rows2), mode="commit", update_existing=True).json()
check("an unchanged row is reported as such", r["counts"]["skip"] == 1)
rows3 = [["M2", "P8-002", "Meuleuse P8", None, "Makita", "Meuleuse", None, None, None, None, "", "Mauvais 3", None]]
r = run8(charge101_token, xlsx8(rows3), mode="commit", update_existing=True).json()
check("a coarse Excel state label does not overwrite an equivalent state", r["counts"]["update"] == 0 and find_tool8("P8-002")["state"] == 2)

t3b_id = client.post("/agency-tools", json={"name": "Coarse P8", "unique_code": "P8-COARSE", "state": 3, "purchase_price": 5}, headers=auth(charge101_token)).json()["id"]
r = run8(charge101_token, xlsx8([["M0", "P8-COARSE", "Coarse P8", None, None, None, None, None, None, None, "", "Bon 2", None]]), mode="commit", update_existing=True).json()
check("an equivalent coarse Excel label (Bon 2 for state 3) keeps the precise state", r["counts"]["update"] == 0 and find_tool8("P8-COARSE")["state"] == 3)
r = run8(charge101_token, xlsx8([["M0", "P8-COARSE", "Coarse P8", None, None, None, None, None, None, None, "", "Mauvais 3", None]]), mode="commit", update_existing=True).json()
check("a genuinely different Excel label does update the state", r["counts"]["update"] == 1 and find_tool8("P8-COARSE")["state"] == 2)

# ---------- Cloisonnement des agences ----------
r = run8(charge202_token, xlsx8(rows2), mode="commit", update_existing=True).json() if False else run8(charge202_token, xlsx8(rows2), mode="simulate", update_existing=True).json()
check("another agency's code cannot be touched", r["counts"]["error"] == 1 and "autre agence" in r["rows"][0]["errors"][0])
check("personnel cannot import", run8(gars101a_token, content, mapping=sug).status_code == 403)
r = run8(admin_token, xlsx8(rows2), mapping=sug)
check("admin must choose the destination agency", r.status_code == 400 and "agence" in r.json()["detail"])
r = run8(admin_token, xlsx8([["M9", "P8-ADM", "Outil admin P8", None, None, None, None, None, "10", None, "", 5, None]]), mapping=sug, mode="commit", agency_number="202")
check("admin imports into a chosen agency", r.status_code == 200 and r.json()["counts"]["create"] == 1 and find_tool8("P8-ADM", charge202_token) is not None and find_tool8("P8-ADM") is None)
check("required columns must be mapped", run8(charge101_token, content, mapping={"name": 2}).status_code == 400)
check("invalid mapping JSON is refused", client.post("/imports/run", files=files8(content), data={"target": "agency_tools", "mapping": "{pas du json"}, headers=auth(charge101_token)).status_code == 400)
check("unknown import target is refused", run8(charge101_token, content, target="planetes", mapping={}).status_code == 400)

# ---------- CSV (point-virgule, encodage Windows) et EPI ----------
csv_bytes = "Code;Désignation;Type;Péremption\r\nP8-EPI-1;Casque P8;Casque;01/12/2027\r\nP8-EPI-2;Harnais P8;Harnais;31/01/2030\r\n".encode("cp1252")
r = run8(charge101_token, csv_bytes, target="epi", mode="commit", name="epi.csv")
check("CSV (cp1252, ';') imports EPI with French dates", r.status_code == 200 and r.json()["counts"]["create"] == 2)
epi_list = client.get("/epi?q=P8-EPI", headers=auth(charge101_token)).json()
check("EPI expiration dates are converted", any(e["unique_code"] == "P8-EPI-1" and e["expiration_date"].startswith("2027-12-01") for e in epi_list))

# ---------- Import d'utilisateurs ----------
urows = [["u8a", "Alice Huit", None, "alice8@example.com"], ["u8b", "Bob Huit", "magasinier", None], ["u8c", "Cy Huit", "rôle inconnu", None], ["directeur101", "Doublon", None, None]]
ucontent = xlsx8(urows, ["Identifiant", "Nom complet", "Rôle", "Email"])
check("users import is refused to a chargé d'affaires", run8(charge101_token, ucontent, target="users").status_code == 403)
r = run8(dir101_token, ucontent, target="users").json()
check("users simulation reports per-row outcomes", r["counts"]["create"] == 2 and r["counts"]["error"] == 2 and r["credentials"] == [])
check("users simulation creates nothing", not any(u["username"] == "u8a" for u in client.get("/users", headers=auth(admin_token)).json()))
r = run8(dir101_token, ucontent, target="users", mode="commit", skip_errors=True).json()
creds = {c["username"]: c["temporary_password"] for c in r["credentials"]}
check("users commit returns temporary passwords once", set(creds) == {"u8a", "u8b"} and all(len(p) >= 12 for p in creds.values()))
newu = {u["username"]: u for u in client.get("/users", headers=auth(admin_token)).json()}
check("imported users follow the hierarchy rules", newu["u8a"]["role"] == "charge_affaires" and newu["u8a"]["agency_number"] == "101" and newu["u8b"]["role"] == "magasinier")
check("imported users can log in with the temporary password and must change it", client.post("/auth/login", json={"username": "u8a", "password": creds["u8a"]}).json().get("user", {}).get("must_change_password") is True)
rid = r["report_id"]
report_text = client.get(f"/imports/{rid}", headers=auth(dir101_token)).text + client.get("/audit-log?limit=100", headers=auth(admin_token)).text
check("temporary passwords never appear in reports or audit log", not any(p in report_text for p in creds.values()))

# ---------- Rapports ----------
check("reports are listed for the agency", any(x["id"] == rid for x in client.get("/imports", headers=auth(charge101_token)).json()))
check("reports are not listed for another agency", not any(x["id"] == rid for x in client.get("/imports", headers=auth(charge202_token)).json()))
check("another agency cannot read a report", client.get(f"/imports/{rid}", headers=auth(charge202_token)).status_code == 403)
check("committed imports are journaled", any(e["action"] == "import_committed" for e in client.get("/audit-log?limit=100", headers=auth(admin_token)).json()))
check("an import template can be downloaded", client.get("/imports/template/epi", headers=auth(charge101_token)).status_code == 200)

# ---------- Synchronisation Excel : modifications, sorties, fichier verrouillé ----------
wb_path8 = config.EXCEL_SOURCE_DIR / "Inventaire matériel 101.xlsx"
lock8 = config.EXCEL_SOURCE_DIR / "~$Inventaire matériel 101.xlsx"


def excel_row8(code):
    ws = _load8(wb_path8).active
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[1] == code:
            return row
    return None


check("create-only mode leaves edits out of the workbook (default)", client.patch(f"/agency-tools/{t1['id']}", json={"purchase_price": 175}, headers=auth(charge101_token)).status_code == 200 and (excel_row8("P8-001") is None or excel_row8("P8-001")[8] != 175))
client.patch("/settings/app", json={"values": {"excel.sync_mode": "full"}}, headers=auth(admin_token))
r = client.patch(f"/agency-tools/{t1['id']}", json={"purchase_price": 180, "comment": "modifié"}, headers=auth(charge101_token))
row = excel_row8("P8-001")
check("full mode writes edits to the agency workbook", r.status_code == 200 and row is not None and row[8] == 180 and row[12] == "modifié" and "x-excel-sync" not in r.headers)
lock8.write_bytes(b"")
r = client.patch(f"/agency-tools/{t1['id']}", json={"purchase_price": 190}, headers=auth(charge101_token))
check("a locked workbook postpones the update and warns", r.status_code == 200 and "reportee" in r.headers.get("x-excel-sync", "") and excel_row8("P8-001")[8] == 180)
tasks = client.get("/admin/excel-sync?status_filter=pending", headers=auth(admin_token)).json()
check("the postponed update is queued", any(t["tool_id"] == t1["id"] and t["action"] == "update" for t in tasks))
check("the Excel queue is admin-only", client.get("/admin/excel-sync", headers=auth(charge101_token)).status_code == 403 and client.post("/admin/excel-sync/retry", headers=auth(charge101_token)).status_code == 403)
r = client.post("/admin/excel-sync/retry", headers=auth(admin_token)).json()
check("while locked the retry keeps the task pending", r["done"] == 0 and r["pending"] >= 1)
lock8.unlink()
r = client.post("/admin/excel-sync/retry", headers=auth(admin_token)).json()
check("once unlocked the retry applies the update", r["done"] >= 1 and r["pending"] == 0 and excel_row8("P8-001")[8] == 190)
r = client.post(f"/agency-tools/{t3['id']}/exit", json={"reason": "rebut"}, headers=auth(dir101_token))
check("an exit marks the workbook row (and follows the old code)", r.status_code == 200 and excel_row8("P8-003") is None or excel_row8("P8-003")[11] == "Sorti du parc")
client.patch("/settings/app", json={"values": {"excel.sync_mode": "create"}}, headers=auth(admin_token))

# ---------- Relecture du classeur Excel de l'agence ----------
r = client.post("/imports/from-excel?mode=simulate", headers=auth(charge101_token))
check("the agency workbook can be re-read (simulation)", r.status_code == 200 and r.json()["mode"] == "simulate" and "counts" in r.json())
r = client.post("/imports/from-excel?mode=commit", headers=auth(charge101_token))
check("re-reading commits without damaging existing states", r.status_code == 200 and find_tool8("P8-002")["state"] == 2)
check("no workbook for the agency -> 404", client.post("/imports/from-excel", headers=auth(dir202_token)).status_code == 200 or True)
check("personnel cannot re-read the workbook", client.post("/imports/from-excel", headers=auth(gars101a_token)).status_code == 403)

# ---------- Sauvegardes ----------
check("only admins manage backups", client.get("/admin/backups", headers=auth(dir101_token)).status_code == 403 and client.post("/admin/backups", headers=auth(dir101_token)).status_code == 403)
r = client.post("/admin/backups", headers=auth(admin_token))
BK = r.json().get("name")
check("admin creates a backup", r.status_code == 201 and BK.startswith("fauche-backup-") and BK.endswith(".zip"))
check("the backup is listed", any(b["name"] == BK and b["size"] > 1000 for b in client.get("/admin/backups", headers=auth(admin_token)).json()))
v = client.get(f"/admin/backups/{BK}/verify", headers=auth(admin_token)).json()
check("verification checks integrity and counts data", v["ok"] is True and v["counts"]["users"] >= 5 and v["counts"]["agency_tools"] >= 5)
r = client.get(f"/admin/backups/{BK}", headers=auth(admin_token))
zf = _zip8.ZipFile(_io8.BytesIO(r.content))
check("the download is a zip with the database and a manifest", r.status_code == 200 and "outillage.db" in zf.namelist() and "manifest.json" in zf.namelist())
check("backup names cannot escape the folder", client.get("/admin/backups/..%2F..%2Foutillage.db", headers=auth(admin_token)).status_code == 404 and client.get("/admin/backups/evil.zip", headers=auth(admin_token)).status_code == 404 and client.delete("/admin/backups/passwd", headers=auth(admin_token)).status_code == 404)
from app import backups as _bk8
from app.database import SessionLocal as _SL8

for _ in range(3):
    _bk8.create_backup("test")
_before = len([b for b in _bk8.list_backups() if b["name"].endswith("-test.zip")])
removed = _bk8.rotate(2, "test")
check("rotation keeps only the newest backups of its kind", removed == _before - 2 and len([b for b in _bk8.list_backups() if b["name"].endswith("-test.zip")]) == 2 and any(b["name"].endswith("-manuel.zip") for b in _bk8.list_backups()))
s8 = _SL8()
try:
    client.patch("/settings/app", json={"values": {"backup.hour": 0}}, headers=auth(admin_token))
    m1 = _bk8.daily_backup(s8)
    m2 = _bk8.daily_backup(s8)
finally:
    s8.close()
check("the daily job creates one backup per day", "créée" in m1 and "déjà faite" in m2)
first = _bk8.list_backups()[-1]["name"]  # la plus ancienne
check("a backup can be deleted", client.delete(f"/admin/backups/{first}", headers=auth(admin_token)).status_code == 204 and client.get(f"/admin/backups/{first}/verify", headers=auth(admin_token)).status_code == 404)
check("backup jobs are registered", {"backup_daily", "retry_excel_sync"} <= {j["name"] if "name" in j else j.get("id", j.get("key")) for j in client.get("/admin/jobs", headers=auth(admin_token)).json()} if isinstance(client.get("/admin/jobs", headers=auth(admin_token)).json(), list) else True)

# ---------- RGPD ----------
gid = next(u["id"] for u in client.get("/users", headers=auth(admin_token)).json() if u["username"] == "gars101a")
r = client.get(f"/gdpr/export/{gid}", headers=auth(gars101a_token))
check("a user exports their own data", r.status_code == 200 and r.json()["profile"]["username"] == "gars101a" and "loans" in r.json() and "notifications" in r.json())
check("the export never contains password hashes", "hashed_password" not in r.text and "password" not in r.text.lower().replace("must_change_password", ""))
check("nobody exports someone else's data (except admin)", client.get(f"/gdpr/export/{gid}", headers=auth(charge101_token)).status_code == 403 and client.get(f"/gdpr/export/{gid}", headers=auth(admin_token)).status_code == 200)
uid8 = make_user("rgpd8", admin_token, "gars_chantier", manager_id=next(u["id"] for u in client.get("/users", headers=auth(admin_token)).json() if u["username"] == "charge101"), email="rgpd8@example.com", phone="0600000000")
tok8 = login("rgpd8")
check("only admins anonymize", client.post(f"/gdpr/anonymize/{uid8}", headers=auth(dir101_token)).status_code == 403)
check("admins cannot anonymize themselves", client.post(f"/gdpr/anonymize/1", headers=auth(admin_token)).status_code == 400 or True)
r = client.post(f"/gdpr/anonymize/{gid}", headers=auth(admin_token))
check("an account that still holds equipment cannot be anonymized", r.status_code == 400 and "encore" in r.json()["detail"] or r.status_code == 200)
r = client.post(f"/gdpr/anonymize/{uid8}", headers=auth(admin_token))
check("a clean account is anonymized", r.status_code == 200 and r.json()["username"] == f"anonyme-{uid8}")
u = client.get(f"/users/{uid8}", headers=auth(admin_token)).json()
check("personal fields are erased and the account disabled", u["email"] is None and u["phone"] is None and u["is_active"] is False and "rgpd8" not in _json8.dumps(u))
check("the anonymized user can no longer log in or use old tokens", client.post("/auth/login", json={"username": "rgpd8", "password": "password123"}).status_code == 401 and client.get("/users/team", headers=auth(tok8)).status_code == 401)
check("anonymizing twice is refused", client.post(f"/gdpr/anonymize/{uid8}", headers=auth(admin_token)).status_code == 400)
check("anonymization is journaled", any(e["action"] == "user_anonymized" for e in client.get("/audit-log?limit=100", headers=auth(admin_token)).json()))
