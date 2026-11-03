# Tests de la Phase 6 (chantiers, coûts, statistiques d'utilisation). Exécuté par smoke_test.py.
_n6 = datetime.utcnow()


def d6(days=0, hours=0):
    return (_n6 + timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")


def mk6(code, **extra):
    payload = {"name": f"Outil {code}", "unique_code": code, "type": "Type P6", "purchase_price": 100}
    payload.update(extra)
    r = client.post("/agency-tools", json=payload, headers=auth(charge101_token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------- Chantiers : création, droits, périmètre ----------
r = client.post("/sites", json={"name": "Chantier Nord P6", "client": "Mairie", "code": "600006"}, headers=auth(charge101_token))
S1 = r.json().get("id")
check("a manager creates a site in their agency", r.status_code == 201 and r.json()["agency_number"] == "101" and r.json()["status"] == "actif")
check("personnel cannot create a site", client.post("/sites", json={"name": "Interdit"}, headers=auth(gars101a_token)).status_code == 403)
check("duplicate site name (any case) is refused", client.post("/sites", json={"name": "chantier nord p6"}, headers=auth(charge101_token)).status_code == 400)
check("the same name is allowed in another agency", client.post("/sites", json={"name": "Chantier Nord P6"}, headers=auth(charge202_token)).status_code == 201)
check("end before start is refused", client.post("/sites", json={"name": "Dates KO", "start_date": "2026-05-02T00:00:00", "end_date": "2026-05-01T00:00:00"}, headers=auth(charge101_token)).status_code == 400)
check("personnel can list their agency's sites", any(s["id"] == S1 for s in client.get("/sites", headers=auth(gars101a_token)).json()))
check("another agency does not see the site", not any(s["id"] == S1 for s in client.get("/sites", headers=auth(charge202_token)).json()))
check("another agency cannot read the site", client.get(f"/sites/{S1}", headers=auth(charge202_token)).status_code == 403)
check("another agency cannot modify the site", client.patch(f"/sites/{S1}", json={"notes": "x"}, headers=auth(charge202_token)).status_code == 403)
check("a site manager must belong to the agency", client.patch(f"/sites/{S1}", json={"manager_id": dir202_id}, headers=auth(charge101_token)).status_code == 400 if "dir202_id" in globals() else True)
r = client.patch(f"/sites/{S1}", json={"client": "Mairie de Test"}, headers=auth(charge101_token))
check("a site is updated (PATCH exclude_unset)", r.status_code == 200 and r.json()["client"] == "Mairie de Test" and r.json()["code"] == "600006")

# ---------- Réservation liée à un chantier ----------
T6 = mk6("P6-T1", daily_rate=10)
T6b = mk6("P6-T2")
r = reserve(gars101a_token, T6, d6(hours=-1), d6(hours=3), site_id=S1)
L6 = r.json().get("id")
check("a reservation can target a site", r.status_code == 201 and r.json()["site_id"] == S1 and r.json()["site"] == "Chantier Nord P6")
S2_other = client.post("/sites", json={"name": "Autre agence P6"}, headers=auth(charge202_token)).json()["id"]
check("a site of another agency is refused", reserve(gars101a_token, T6b, d6(hours=-1), d6(hours=2), site_id=S2_other).status_code == 400)
check("an unknown site is refused", reserve(gars101a_token, T6b, d6(hours=-1), d6(hours=2), site_id=99999).status_code == 404)
check("free-text sites still work", reserve(gars101a_token, T6b, d6(days=5), d6(days=5, hours=2), site="Texte libre").json().get("site") == "Texte libre")

# ---------- Clôture ----------
r = client.post(f"/sites/{S1}/close", headers=auth(charge101_token))
check("a site with a borrowed tool cannot be closed", r.status_code == 400 and "Outil" in r.json()["detail"])
check("personnel cannot close a site", client.post(f"/sites/{S1}/close", headers=auth(gars101a_token)).status_code == 403)
check("another agency cannot close the site", client.post(f"/sites/{S1}/close", headers=auth(charge202_token)).status_code == 403)
sheet = client.get(f"/sites/{S1}/sheet", headers=auth(charge101_token)).json()
check("the site sheet lists the tools currently on site", any(t["tool_id"] == T6 for t in sheet["current_tools"]))
check("personnel cannot read the costed sheet", client.get(f"/sites/{S1}/sheet", headers=auth(gars101a_token)).status_code == 403)
check("another agency cannot read the sheet", client.get(f"/sites/{S1}/sheet", headers=auth(charge202_token)).status_code == 403)

r = client.post(f"/loans/{L6}/return", json={"state_after": 5}, headers=auth(gars101a_token))
sheet = client.get(f"/sites/{S1}/sheet", headers=auth(charge101_token)).json()
check("the cost counts each started day at the tool's daily rate", sheet["cost"]["total"] == 10.0 and sheet["cost"]["days"] == 1)
check("no tool remains on site after the return", sheet["current_tools"] == [])
check("a site with no open reservation can be closed", client.post(f"/sites/{S1}/close", headers=auth(charge101_token)).json()["status"] == "clos")
check("a closed site refuses new reservations", reserve(gars101a_token, T6, d6(days=1), d6(days=1, hours=2), site_id=S1).status_code == 400)
check("a closed site cannot be closed twice", client.post(f"/sites/{S1}/close", headers=auth(charge101_token)).status_code == 400)
check("closing is journaled", any(e["action"] == "site_closed" for e in client.get("/audit-log?limit=50", headers=auth(admin_token)).json()))
check("a site can be reopened", client.post(f"/sites/{S1}/reopen", headers=auth(charge101_token)).json()["status"] == "actif")

# Défaut de tarif : forfait par défaut des paramètres
client.patch("/settings/app", json={"values": {"cost.default_daily_rate": 7}}, headers=auth(admin_token))
lb = reserve(gars101a_token, T6b, d6(hours=-1), d6(hours=1), site_id=S1).json()["id"]
client.post(f"/loans/{lb}/return", json={"state_after": 5}, headers=auth(gars101a_token))
sheet = client.get(f"/sites/{S1}/sheet", headers=auth(charge101_token)).json()
check("a tool without rate uses the default daily rate", sheet["cost"]["total"] == 17.0)
r = client.get("/stats/sites-cost", headers=auth(charge101_token)).json()
client.patch("/settings/app", json={"values": {"cost.default_daily_rate": 0}}, headers=auth(admin_token))
check("cost per site is aggregated by agency", any(s["id"] == S1 and s["cost"] == 17.0 for s in r["sites"]) and r["total"] >= 17.0)
check("cost per site is manager-only", client.get("/stats/sites-cost", headers=auth(gars101a_token)).status_code == 403)
check("another agency's costs never include this site", not any(s["id"] == S1 for s in client.get("/stats/sites-cost", headers=auth(charge202_token)).json()["sites"]))

# ---------- Stock rattaché au chantier ----------
mag_tok = login("mag101")
it = client.post("/stock/items", json={"name": "Chevilles P6", "quantity": 50, "threshold": 5}, headers=auth(mag_tok)).json()["id"]
r = client.post(f"/stock/items/{it}/movements", json={"kind": "sortie", "quantity": 12, "site_id": S1}, headers=auth(mag_tok))
check("a stock issue can be attached to a site", r.status_code == 201)
check("a stock issue to another agency's site is refused", client.post(f"/stock/items/{it}/movements", json={"kind": "sortie", "quantity": 1, "site_id": S2_other}, headers=auth(mag_tok)).status_code == 400)
sheet = client.get(f"/sites/{S1}/sheet", headers=auth(charge101_token)).json()
check("the site sheet lists issued consumables", any(s["item"] == "Chevilles P6" and s["quantity"] == 12 for s in sheet["stock_issued"]))

# ---------- Statistiques d'utilisation ----------
from app import migrations as _mig
from app.database import engine as _engine
_start = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
_end = (datetime.utcnow() - timedelta(days=9)).strftime("%Y-%m-%d %H:%M:%S")
with _engine.begin() as _c:
    _c.execute(_mig.text("INSERT INTO loans (tool_id, borrower_id, start_datetime, end_datetime_planned, actual_return_datetime, checked_out_at, status, created_at) VALUES (:t, 1, :s, :e, :e, :s, 'termine', :s)"), {"t": T6, "s": _start, "e": _end})
u = client.get("/stats/utilization?days=30", headers=auth(charge101_token)).json()
row = next((t for t in u["tools"] if t["tool_id"] == T6), None)
check("utilization is computed per tool", row is not None and row["utilization_pct"] > 0 and row["loans"] >= 1)
check("utilization is aggregated by type", any(t["type"] == "Type P6" and t["tools"] >= 2 for t in u["by_type"]))
check("recently created tools are not dormant", not any(t["tool_id"] == T6 for t in u["dormant"]))
client.patch("/settings/app", json={"values": {"stats.dormant_days": 0, "stats.saturated_pct": 1}}, headers=auth(admin_token))
u = client.get("/stats/utilization?days=30", headers=auth(charge101_token)).json()
check("dormant threshold is admin-configurable", any(t["tool_id"] == T6 for t in u["dormant"]) or any(t["tool_id"] == T6b for t in u["dormant"]))
check("saturation threshold is admin-configurable", any(t["tool_id"] == T6 for t in u["saturated"]))
client.patch("/settings/app", json={"values": {"stats.dormant_days": 90, "stats.saturated_pct": 80}}, headers=auth(admin_token))
check("utilization is manager-only", client.get("/stats/utilization", headers=auth(gars101a_token)).status_code == 403)
check("utilization never includes another agency", not any(t["tool_id"] == T6 for t in client.get("/stats/utilization", headers=auth(charge202_token)).json()["tools"]))
check("utilization window is bounded", client.get("/stats/utilization?days=99999", headers=auth(charge101_token)).json()["window_days"] == 730)

# ---------- Migration : rattachement des anciennes réservations texte ----------
with _engine.begin() as _c:
    _c.execute(_mig.text("INSERT INTO loans (tool_id, borrower_id, site, start_datetime, end_datetime_planned, status, created_at) VALUES (:t, :b, 'Ancien chantier P6', '2020-01-01 08:00:00', '2020-01-02 08:00:00', 'termine', '2020-01-01 08:00:00')"), {"t": T6b, "b": p1_id if "p1_id" in globals() else 1})
    _mig.m007_sites(_c)
    _mig.m007_sites(_c)
with _engine.begin() as _c:
    n_sites = _c.execute(_mig.text("SELECT COUNT(*) FROM sites WHERE name = 'Ancien chantier P6'")).scalar()
    linked = _c.execute(_mig.text("SELECT COUNT(*) FROM loans WHERE site = 'Ancien chantier P6' AND site_id IS NOT NULL")).scalar()
    st = _c.execute(_mig.text("SELECT status FROM sites WHERE name = 'Ancien chantier P6'")).scalar()
check("migration m007 creates a site from legacy text and links loans (idempotent)", n_sites == 1 and linked == 1 and st == "clos")
