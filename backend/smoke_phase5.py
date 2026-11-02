# Tests de la Phase 5 (maintenance, magasinier, sortie de parc, accessoires, stock). Exécuté par smoke_test.py.
_n5 = datetime.utcnow()


def d5(days=0, hours=0):
    return (_n5 + timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")


def mk5(code, type_="TypeP5", token=None, **extra):
    payload = {"name": f"Outil {code}", "unique_code": code, "type": type_, "purchase_price": 100}
    payload.update(extra)
    r = client.post("/agency-tools", json=payload, headers=auth(token or charge101_token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def tickets_of(token, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get("/maintenance-tickets?" + query, headers=auth(token)).json()


def get_tool5(tool_id):
    return client.get(f"/agency-tools/{tool_id}?include_exited=true", headers=auth(admin_token)).json()


# ---------- Rôle magasinier ----------
r = client.post("/users", json={"username": "mag101", "full_name": "Magasinier 101", "role": "magasinier", "password": "password123", "agency_number": "101"}, headers=admin_headers)
mag_id = r.json()["id"]
check("admin creates a storekeeper in an agency", r.status_code == 201 and r.json()["agency_number"] == "101")
check("a storekeeper needs an agency", client.post("/users", json={"username": "mag_noagency", "full_name": "X", "role": "magasinier", "password": "password123"}, headers=admin_headers).status_code == 400)
r = client.post("/users", json={"username": "mag101b", "full_name": "Magasinier B", "role": "magasinier", "password": "password123"}, headers=auth(dir101_token))
check("a director creates a storekeeper in their own agency", r.status_code == 201 and r.json()["agency_number"] == "101" and r.json()["manager_id"] == dir101_id)
check("a chargé d'affaires cannot create a storekeeper", client.post("/users", json={"username": "mag_bad", "full_name": "X", "role": "magasinier", "password": "password123"}, headers=auth(charge101_token)).status_code == 400)
mag = login("mag101")
check("the storekeeper reads the agency's tools", client.get("/agency-tools", headers=auth(mag)).status_code == 200)
check("the storekeeper manages tools like a manager", client.post("/agency-tools", json={"name": "Outil mag", "unique_code": "P5-MAG-1", "purchase_price": 10}, headers=auth(mag)).status_code == 201)
check("the storekeeper cannot administer accounts", client.post("/users", json={"username": "x_by_mag", "full_name": "X", "role": "gars_chantier", "password": "password123"}, headers=auth(mag)).status_code == 400)
check("the storekeeper has no admin rights", client.get("/settings", headers=auth(mag)).status_code == 403 and client.delete("/agency-tools/1", headers=auth(mag)).status_code == 403)
check("the storekeeper stays inside their agency", client.get("/agency-tools?q=Niveau", headers=auth(mag)).json() == [])

# ---------- Tickets automatiques ----------
T1 = mk5("P5-T1")
client.patch(f"/agency-tools/{T1}", json={"status": "reparation"}, headers=auth(charge101_token))
found = tickets_of(charge101_token, tool_id=T1, tool_kind="agency")
check("a tool sent to repair opens a ticket automatically", len(found) == 1 and found[0]["auto_opened"] and found[0]["status"] == "ouvert")
client.patch(f"/agency-tools/{T1}", json={"comment": "en attente"}, headers=auth(charge101_token))
client.patch(f"/agency-tools/{T1}", json={"state": 2}, headers=auth(charge101_token))
check("no duplicate ticket while one is open", len(tickets_of(charge101_token, tool_id=T1, tool_kind="agency")) == 1)
check("the storekeeper is notified of the new ticket", any(n["type"] == "maintenance_update" for n in notes(mag)))

# ---------- Signalement rapide ----------
T2 = mk5("P5-T2")
r = client.post("/maintenance-tickets", json={"tool_kind": "agency", "tool_id": T2, "category": "panne", "severity": "moyenne", "description": "ne démarre plus"}, headers=auth(gars101a_token))
tk2 = r.json()["id"]
check("personnel report a problem in one step", r.status_code == 201 and r.json()["status"] == "ouvert")
check("the report puts an available tool under repair", get_tool5(T2)["status"] == "reparation")
check("a report is journaled in the tool history", any(h["source"] == "signalement" for h in client.get(f"/state-history?kind=agency&tool_id={T2}", headers=auth(charge101_token)).json()))
T3 = mk5("P5-T3")
r = client.post("/maintenance-tickets", json={"tool_kind": "agency", "tool_id": T3, "category": "perte", "severity": "haute", "description": "oublié sur chantier"}, headers=auth(gars101a_token))
check("a loss report sets the tool out of service with the reason", get_tool5(T3)["status"] == "hors_service" and get_tool5(T3)["loss_reason"] == "perte")
T3b = mk5("P5-T3B")
client.post("/maintenance-tickets", json={"tool_kind": "agency", "tool_id": T3b, "category": "vol", "severity": "haute", "description": "volé"}, headers=auth(gars101a_token))
check("a theft report records the theft reason", get_tool5(T3b)["loss_reason"] == "vol")
check("a serious break needs a description", client.post("/maintenance-tickets", json={"tool_kind": "agency", "tool_id": mk5("P5-T3C"), "category": "casse", "severity": "critique"}, headers=auth(gars101a_token)).status_code == 400)
check("an invalid category is refused", client.post("/maintenance-tickets", json={"tool_kind": "agency", "tool_id": T2, "category": "nimportequoi"}, headers=auth(gars101a_token)).status_code == 400)
check("reports never cross agencies", client.post("/maintenance-tickets", json={"tool_kind": "agency", "tool_id": T2, "category": "panne"}, headers=auth(charge202_token)).status_code == 403)
perso5 = client.post("/personal-tools", json={"name": "Perceuse P5", "unique_code": "P5-PERSO", "state": 5}, headers=auth(gars101a_token)).json()["id"]
client.post("/maintenance-tickets", json={"tool_kind": "personal", "tool_id": perso5, "category": "casse", "severity": "faible"}, headers=auth(gars101a_token))
check("a report on a personal tool flags it as damaged", client.get(f"/personal-tools/{perso5}", headers=auth(gars101a_token)).json()["state_reason"] == "endommage")
check("personnel only see the tickets they opened", all(t["opened_by_id"] is not None and t["opened_by_name"] for t in tickets_of(gars101a_token)) and not any(t["tool_id"] == T1 and t["tool_kind"] == "agency" for t in tickets_of(gars101a_token)))
check("managers see every ticket of the agency", any(t["id"] == tk2 for t in tickets_of(charge101_token)))
check("tickets never cross agencies", tickets_of(charge202_token, tool_id=T2, tool_kind="agency") == [])

# ---------- Cycle de vie ----------
check("personnel cannot move a ticket", client.post(f"/maintenance-tickets/{tk2}/transition", json={"status": "diagnostic"}, headers=auth(gars101a_token)).status_code == 403)
check("an impossible transition is refused", client.post(f"/maintenance-tickets/{tk2}/transition", json={"status": "clos"}, headers=auth(mag)).status_code == 400)
check("the storekeeper moves a ticket to diagnosis", client.post(f"/maintenance-tickets/{tk2}/transition", json={"status": "diagnostic"}, headers=auth(mag)).json()["status"] == "diagnostic")
r = client.patch(f"/maintenance-tickets/{tk2}", json={"provider": "fournisseur", "estimated_cost": 120, "parts": "Charbons", "expected_return_date": d5(5)}, headers=auth(mag))
check("a ticket records provider, cost, parts and return date", r.status_code == 200 and r.json()["provider"] == "fournisseur" and r.json()["estimated_cost"] == 120)
check("an invalid provider is refused", client.patch(f"/maintenance-tickets/{tk2}", json={"provider": "cousin"}, headers=auth(mag)).status_code == 400)
client.post(f"/maintenance-tickets/{tk2}/transition", json={"status": "en_reparation"}, headers=auth(mag))
check("the expected return date blocks the tool automatically", any(b["tool_id"] == T2 and b["source"] == "auto" for b in client.get("/blackouts", headers=auth(charge101_token)).json()))
check("a blocked tool cannot be reserved in the meantime", reserve(gars101a_token, T2, d5(2), d5(2, 2)).status_code == 400)
client.post(f"/maintenance-tickets/{tk2}/comments", json={"body": "pièce commandée"}, headers=auth(gars101a_token))
r = client.post(f"/maintenance-tickets/{tk2}/attachments?kind=photo", files={"file": ("p.jpg", b"\xff\xd8\xff\xe0jpg", "image/jpeg")}, headers=auth(gars101a_token))
check("anyone concerned can attach a photo", r.status_code == 201)
check("personnel cannot attach a quote", client.post(f"/maintenance-tickets/{tk2}/attachments?kind=devis", files={"file": ("d.pdf", b"%PDF-1.4 d", "application/pdf")}, headers=auth(gars101a_token)).status_code == 403)
check("a manager attaches a quote as PDF", client.post(f"/maintenance-tickets/{tk2}/attachments?kind=devis", files={"file": ("devis.pdf", b"%PDF-1.4 devis", "application/pdf")}, headers=auth(mag)).status_code == 201)
check("an executable attachment is refused", client.post(f"/maintenance-tickets/{tk2}/attachments?kind=facture", files={"file": ("x.exe", b"MZ", "application/octet-stream")}, headers=auth(mag)).status_code == 400)
check("an invalid attachment kind is refused", client.post(f"/maintenance-tickets/{tk2}/attachments?kind=virus", files={"file": ("p.jpg", b"x", "image/jpeg")}, headers=auth(mag)).status_code == 400)
detail = client.get(f"/maintenance-tickets/{tk2}", headers=auth(charge101_token)).json()
check("the ticket detail shows comments and attachments", len(detail["comments"]) >= 4 and len(detail["attachments"]) == 2 and detail["tool"]["name"])
check("another agency cannot read the ticket", client.get(f"/maintenance-tickets/{tk2}", headers=auth(charge202_token)).status_code == 403)
client.patch(f"/maintenance-tickets/{tk2}", json={"actual_cost": 95.5}, headers=auth(mag))
r = client.post(f"/maintenance-tickets/{tk2}/transition", json={"status": "repare", "state_after": 5, "resolution": "Charbons remplacés"}, headers=auth(mag))
tool_after = get_tool5(T2)
check("a repaired ticket makes the tool available again with its new state", r.status_code == 200 and tool_after["status"] == "disponible" and tool_after["state"] == 5)
check("the repair triggers a new control", tool_after["last_control_date"] is not None and len(client.get(f"/inspections?tool_kind=agency&tool_id={T2}", headers=auth(charge101_token)).json()) >= 1)
check("the automatic blackout is removed after repair", not any(b["tool_id"] == T2 for b in client.get("/blackouts", headers=auth(charge101_token)).json()))
check("the reporter is informed of the outcome", any(n["type"] == "maintenance_update" and "repare" in n["title"] for n in notes(gars101a_token)))
check("a repaired ticket can be closed", client.post(f"/maintenance-tickets/{tk2}/transition", json={"status": "clos"}, headers=auth(mag)).json()["closed_at"])
check("a closed ticket cannot be reopened", client.post(f"/maintenance-tickets/{tk2}/transition", json={"status": "ouvert"}, headers=auth(mag)).status_code == 400)

T4 = mk5("P5-T4")
tk4 = client.post("/maintenance-tickets", json={"tool_kind": "agency", "tool_id": T4, "category": "casse", "severity": "haute", "description": "carter fendu"}, headers=auth(gars101a_token)).json()["id"]
client.post(f"/maintenance-tickets/{tk4}/transition", json={"status": "irreparable", "resolution": "pièce introuvable"}, headers=auth(mag))
check("an unrepairable ticket takes the tool out of service", get_tool5(T4)["status"] == "hors_service")
check("managers are told to consider a decommission", any(n["type"] == "maintenance_update" and "Irréparable" in n["title"] for n in notes(charge101_token)))

# ---------- Garantie et statistiques ----------
T5 = mk5("P5-T5", warranty_expiration_date=d5(100))
client.patch(f"/agency-tools/{T5}", json={"status": "reparation"}, headers=auth(charge101_token))
tk5 = tickets_of(charge101_token, tool_id=T5, tool_kind="agency")[0]
check("a tool under warranty flags the ticket as a warranty claim", tk5["warranty_claim"] is True and tk5["tool"]["warranty"]["active"] is True)
r = client.patch(f"/maintenance-tickets/{tk5['id']}", json={"warranty_case_number": "SAV-2026-01", "sent_at": d5(0)}, headers=auth(mag))
check("the warranty case number is tracked", r.json()["warranty_case_number"] == "SAV-2026-01")
stats = client.get("/maintenance-tickets/stats", headers=auth(charge101_token)).json()
check("maintenance statistics are available to managers", stats["open"] >= 2 and stats["avg_repair_days"] is not None and stats["total_cost"] >= 95.5 and "TypeP5" in stats["tickets_by_type"])
check("statistics are closed to personnel", client.get("/maintenance-tickets/stats", headers=auth(gars101a_token)).status_code == 403)

# ---------- Sortie de parc ----------
T6 = mk5("P5-T6", purchase_price=250)
future_loan = reserve(gars101a_token, T6, d5(3), d5(3, 2)).json()["id"]
before_total = client.get("/agency-tools/financial-summary", headers=auth(charge101_token)).json()["total_count"]
r = client.post(f"/agency-tools/{T6}/exit", json={"reason": "rebut", "note": "fin de vie", "residual_value": 5}, headers=auth(mag))
exit_req = r.json()["id"]
check("a storekeeper proposes a decommission that waits for approval", r.status_code == 200 and r.json()["status"] == "pending" and get_tool5(T6)["status"] != "sorti_du_parc")
check("only one pending decommission per tool", client.post(f"/agency-tools/{T6}/exit", json={"reason": "rebut"}, headers=auth(mag)).status_code == 400)
check("an invalid reason is refused", client.post(f"/agency-tools/{mk5('P5-T6X')}/exit", json={"reason": "envie"}, headers=auth(mag)).status_code == 400)
check("pending requests are listed for the agency", any(x["id"] == exit_req for x in client.get("/exit-requests", headers=auth(charge101_token)).json()))
check("a chargé d'affaires cannot approve", client.post(f"/exit-requests/{exit_req}/approve", headers=auth(charge101_token)).status_code == 403)
check("another agency's director cannot approve", client.post(f"/exit-requests/{exit_req}/approve", headers=auth(dir202_token)).status_code == 403)
r = client.post(f"/exit-requests/{exit_req}/approve", headers=auth(dir101_token))
exited = get_tool5(T6)
check("the director approves the decommission", r.status_code == 200 and exited["status"] == "sorti_du_parc" and exited["exit_reason"] == "rebut" and exited["residual_value"] == 5)
check("the code is released for reuse", "~SORTI" in exited["unique_code"] and "P5-T6" in exited["exit_note"])
check("future reservations of the tool are cancelled", client.get(f"/loans/{future_loan}", headers=auth(gars101a_token)).json()["status"] == "annule")
check("the exit is journaled", any(h["source"] == "sortie de parc" for h in client.get(f"/state-history?kind=agency&tool_id={T6}", headers=auth(charge101_token)).json()))
check("exited tools disappear from the normal list", not any(t["id"] == T6 for t in client.get("/agency-tools", headers=auth(charge101_token)).json()))
check("exited tools can be shown on demand", any(t["id"] == T6 for t in client.get("/agency-tools?include_exited=true", headers=auth(charge101_token)).json()))
check("an exited tool cannot be reserved", reserve(gars101a_token, T6, d5(6), d5(6, 2)).status_code == 400)
check("exited tools stay in the financial statistics", client.get("/agency-tools/financial-summary", headers=auth(charge101_token)).json()["total_count"] == before_total + 1)  # +1 : l'outil créé par le test du motif invalide
check("exited tools are no longer due for control", not any(i["id"] == T6 for i in client.get("/inspections/due?kind=agency", headers=auth(charge101_token)).json()["items"]))
check("the freed code can be reused", client.post("/agency-tools", json={"name": "Remplaçant", "unique_code": "P5-T6", "purchase_price": 1}, headers=auth(charge101_token)).status_code == 201)
T7 = mk5("P5-T7")
r = client.post(f"/agency-tools/{T7}/exit", json={"reason": "vendu"}, headers=auth(dir101_token))
check("a director decommissions directly", r.json()["status"] == "approved" and get_tool5(T7)["status"] == "sorti_du_parc")
T8 = mk5("P5-T8")
rq = client.post(f"/agency-tools/{T8}/exit", json={"reason": "donne"}, headers=auth(mag)).json()["id"]
check("a request can be rejected", client.post(f"/exit-requests/{rq}/reject", headers=auth(dir101_token)).json()["status"] == "rejected" and get_tool5(T8)["status"] == "disponible")
T9 = mk5("P5-T9")
reserve(gars101a_token, T9, d5(hours=-1), d5(hours=2))
check("a borrowed tool cannot be decommissioned", client.post(f"/agency-tools/{T9}/exit", json={"reason": "rebut"}, headers=auth(dir101_token)).status_code == 400)
check("decommissioning respects the agency", client.post(f"/agency-tools/{T8}/exit", json={"reason": "rebut"}, headers=auth(charge202_token)).status_code == 403)
client.patch("/settings/app", json={"values": {"exit.requires_approval": False, "exit.release_code": False}}, headers=admin_headers)
T10 = mk5("P5-T10")
r = client.post(f"/agency-tools/{T10}/exit", json={"reason": "rebut"}, headers=auth(mag))
check("approval can be switched off by setting", r.json()["status"] == "approved" and get_tool5(T10)["unique_code"] == "P5-T10")
client.patch("/settings/app", json={"values": {"exit.requires_approval": True, "exit.release_code": True}}, headers=admin_headers)

# ---------- Accessoires ----------
T11 = mk5("P5-T11")
check("personnel cannot edit accessories", client.post(f"/agency-tools/{T11}/accessories", json={"name": "Batterie"}, headers=auth(gars101a_token)).status_code == 403)
check("a manager lists accessories", client.post(f"/agency-tools/{T11}/accessories", json={"name": "Batterie 18V", "quantity": 2}, headers=auth(charge101_token)).status_code == 201)
client.post(f"/agency-tools/{T11}/accessories", json={"name": "Chargeur"}, headers=auth(charge101_token))
check("everyone in the agency can read the accessories", len(client.get(f"/agency-tools/{T11}/accessories", headers=auth(gars101a_token)).json()) == 2)
check("accessories never leak to another agency", client.get(f"/agency-tools/{T11}/accessories", headers=auth(charge202_token)).status_code == 403)
loan11 = reserve(gars101a_token, T11, d5(hours=-1), d5(hours=2)).json()["id"]
client.post(f"/loans/{loan11}/return", json={"state_after": 5, "accessories_ok": False}, headers=auth(gars101a_token))
check("an incomplete return opens an accessory ticket", any(t["category"] == "accessoire_manquant" and t["tool_id"] == T11 for t in tickets_of(charge101_token)))
check("the ticket lists the expected accessories", "Batterie 18V" in next(t for t in tickets_of(charge101_token) if t["category"] == "accessoire_manquant" and t["tool_id"] == T11)["description"])

# ---------- Coffrets : outil parent et éléments ----------
PARENT, KID1, KID2 = mk5("P5-COFFRET", "Coffret"), mk5("P5-KID1"), mk5("P5-KID2")
client.patch(f"/agency-tools/{KID1}", json={"parent_tool_id": PARENT}, headers=auth(charge101_token))
client.patch(f"/agency-tools/{KID2}", json={"parent_tool_id": PARENT}, headers=auth(charge101_token))
lp = reserve(gars101a_token, PARENT, d5(hours=-1), d5(hours=3)).json()["id"]
check("borrowing a case marks its contents as borrowed", get_tool5(KID1)["status"] == "emprunte" and get_tool5(KID2)["status"] == "emprunte")
check("an element of a borrowed case cannot be reserved now", reserve(p1_token, KID1, d5(hours=-1), d5(hours=1)).status_code == 400)
client.post(f"/loans/{lp}/return", json={"state_after": 5}, headers=auth(gars101a_token))
check("returning the case frees its contents", get_tool5(KID1)["status"] == "disponible" and get_tool5(KID2)["status"] == "disponible")
future_parent = reserve(gars101a_token, PARENT, d5(4), d5(4, 2)).json()["id"]
check("an element cannot be reserved while its case is booked", reserve(p1_token, KID1, d5(4, 1), d5(4, 3)).status_code == 400)
client.patch(f"/agency-tools/{KID2}", json={"status": "reparation"}, headers=auth(charge101_token))
check("a case cannot be borrowed now if one element is unavailable", reserve(p1_token, PARENT, d5(hours=-1), d5(hours=1)).status_code == 400)

# ---------- Stock ----------
check("personnel cannot create stock items", client.post("/stock/items", json={"name": "Disques", "quantity": 10}, headers=auth(gars101a_token)).status_code == 403)
r = client.post("/stock/items", json={"name": "Disques 125", "reference": "D125", "unit": "pièce", "quantity": 10, "threshold": 3, "location": "Étagère A"}, headers=auth(mag))
item = r.json()["id"]
check("a storekeeper creates a stock item", r.status_code == 201 and r.json()["quantity"] == 10 and not r.json()["low"])
r = client.post(f"/stock/items/{item}/movements", json={"kind": "sortie", "quantity": 8, "site": "Chantier Nord", "to_user_id": p4a_id}, headers=auth(mag))
check("an issue lowers the balance and flags a low stock", r.status_code == 201 and r.json()["quantity"] == 2 and r.json()["low"])
check("crossing the threshold alerts the managers", any(n["type"] == "stock_low" for n in notes(charge101_token)))
check("issuing more than the balance is refused", client.post(f"/stock/items/{item}/movements", json={"kind": "sortie", "quantity": 5}, headers=auth(mag)).status_code == 400)
check("a delivery raises the balance", client.post(f"/stock/items/{item}/movements", json={"kind": "entree", "quantity": 20}, headers=auth(mag)).json()["quantity"] == 22)
check("a stock count sets the balance", client.post(f"/stock/items/{item}/movements", json={"kind": "inventaire", "quantity": 1}, headers=auth(mag)).json()["quantity"] == 1)
check("an invalid movement is refused", client.post(f"/stock/items/{item}/movements", json={"kind": "vol", "quantity": 1}, headers=auth(mag)).status_code == 400)
moves = client.get(f"/stock/items/{item}/movements", headers=auth(gars101a_token)).json()
check("every movement is journaled with its balance", len(moves) >= 4 and moves[0]["balance_after"] == 1 and any(m["site"] == "Chantier Nord" for m in moves))
check("low stock items can be filtered", any(i["id"] == item for i in client.get("/stock/items?low_only=true", headers=auth(charge101_token)).json()))
check("stock never crosses agencies", client.get("/stock/items", headers=auth(charge202_token)).json() == [] and client.post(f"/stock/items/{item}/movements", json={"kind": "entree", "quantity": 1}, headers=auth(charge202_token)).status_code == 403)
check("an item can be archived", client.patch(f"/stock/items/{item}", json={"is_active": False}, headers=auth(mag)).json()["is_active"] is False and not any(i["id"] == item for i in client.get("/stock/items", headers=auth(mag)).json()))
client.patch(f"/stock/items/{item}", json={"is_active": True}, headers=auth(mag))
res = run_alerts(datetime.utcnow() + timedelta(days=30))
check("the weekly stock alert is generated", res.get("stock_low", 0) >= 1)
