# Tests de la Phase 3 (terrain : lookup, lots, fiche, photos, idempotence). Exécuté par smoke_test.py.
import io as _io

_t3 = client.post("/agency-tools", json={"name": "Perceuse P3", "unique_code": "P3-SCAN-1", "type": "Perceuse", "purchase_price": 50}, headers=auth(charge101_token)).json()["id"]

r = client.get("/tools/lookup?code=P3-SCAN-1", headers=auth(gars101a_token))
check("scan: lookup by code returns the tool", r.status_code == 200 and r.json()["kind"] == "agency" and r.json()["id"] == _t3)
check("scan: unknown code -> 404", client.get("/tools/lookup?code=NOPE-XYZ", headers=auth(gars101a_token)).status_code == 404)
check("scan: another agency's tool -> 403", client.get("/tools/lookup?code=P3-SCAN-1", headers=auth(charge202_token)).status_code == 403)
check("scan: lookup requires auth", client.get("/tools/lookup?code=P3-SCAN-1").status_code == 401)

r = client.post("/tools/lookup-batch", json={"codes": ["P3-SCAN-1", "P3-SCAN-1", "NOPE-XYZ"]}, headers=auth(charge101_token))
res = {x["code"]: x["result"] for x in r.json()}
check("batch scan: dedups and flags not_found", r.status_code == 200 and res == {"P3-SCAN-1": "ok", "NOPE-XYZ": "not_found"})
r = client.post("/tools/lookup-batch", json={"codes": ["P3-SCAN-1"]}, headers=auth(charge202_token))
check("batch scan: cross-agency is 'forbidden' with no tool data", r.json()[0]["result"] == "forbidden" and r.json()[0]["tool"] is None)
check("batch scan: empty list refused", client.post("/tools/lookup-batch", json={"codes": []}, headers=auth(charge101_token)).status_code == 422)

r = client.get(f"/tools/agency/{_t3}/sheet", headers=auth(gars101a_token))
check("sheet: aggregated data", r.status_code == 200 and {"control", "open_tickets", "photos", "current_loan", "next_reservations", "accessories"} <= set(r.json()))
check("sheet: personnel cannot manage", r.json()["can_manage"] is False)
check("sheet: cross-agency 403", client.get(f"/tools/agency/{_t3}/sheet", headers=auth(charge202_token)).status_code == 403)
check("sheet: unknown kind 400", client.get(f"/tools/robot/{_t3}/sheet", headers=auth(charge101_token)).status_code == 400)

png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
r = client.post(f"/tool-photos/agency/{_t3}?photo_kind=etat&caption=Rayure", files={"file": ("a.png", _io.BytesIO(png), "image/png")}, headers=auth(gars101a_token))
pid = r.json().get("id")
check("photos: upload on the gallery", r.status_code == 201 and r.json()["path"].startswith("/uploads/tool_photos/agency/"))
check("photos: bad extension refused", client.post(f"/tool-photos/agency/{_t3}", files={"file": ("a.exe", _io.BytesIO(b"MZ"), "application/octet-stream")}, headers=auth(gars101a_token)).status_code == 400)
check("photos: bad kind refused", client.post(f"/tool-photos/agency/{_t3}?photo_kind=zzz", files={"file": ("a.png", _io.BytesIO(png), "image/png")}, headers=auth(gars101a_token)).status_code == 400)
check("photos: cross-agency upload refused", client.post(f"/tool-photos/agency/{_t3}", files={"file": ("a.png", _io.BytesIO(png), "image/png")}, headers=auth(charge202_token)).status_code == 403)
check("photos: listed in gallery and sheet", len(client.get(f"/tool-photos/agency/{_t3}", headers=auth(charge101_token)).json()) == 1 and len(client.get(f"/tools/agency/{_t3}/sheet", headers=auth(charge101_token)).json()["photos"]) == 1)
check("photos: author deletes", client.delete(f"/tool-photos/{pid}", headers=auth(gars101a_token)).status_code == 204)

# Idempotence : le même Idempotency-Key ne crée qu'un seul ticket
hdr = {**auth(gars101a_token), "Idempotency-Key": "test-key-0001"}
body = {"tool_kind": "agency", "tool_id": _t3, "category": "panne", "severity": "faible", "description": "idem"}
r1 = client.post("/maintenance-tickets", json=body, headers=hdr)
r2 = client.post("/maintenance-tickets", json=body, headers=hdr)
check("idempotency: first call creates", r1.status_code == 201)
check("idempotency: replay returns the same response", r2.status_code == 201 and r2.json()["id"] == r1.json()["id"] and r2.headers.get("idempotent-replay") == "true")
n_idem = len([t for t in client.get(f"/maintenance-tickets?tool_id={_t3}", headers=auth(charge101_token)).json() if t["description"] == "idem"])
check("idempotency: exactly one ticket exists", n_idem == 1)
r3 = client.post("/maintenance-tickets", json=body, headers={**auth(charge101_token), "Idempotency-Key": "test-key-0001"})
check("idempotency: keys are scoped per user", r3.headers.get("idempotent-replay") != "true")

# Étiquettes
r = client.get("/tools/labels?kind=agency", headers=auth(charge101_token))
check("labels: manager lists tools with printed flag", r.status_code == 200 and any(x["unique_code"] == "P3-SCAN-1" and x["printed_at"] is None for x in r.json()))
check("labels: personnel cannot list", client.get("/tools/labels", headers=auth(gars101a_token)).status_code == 403)
check("labels: other agency sees none of these", not any(x["unique_code"] == "P3-SCAN-1" for x in client.get("/tools/labels?kind=agency", headers=auth(charge202_token)).json()))
check("labels: personal kind refused", client.get("/tools/labels?kind=personal", headers=auth(charge101_token)).status_code == 400)
r = client.post("/tools/labels/printed", json={"kind": "agency", "ids": [_t3]}, headers=auth(charge101_token))
check("labels: mark as printed", r.status_code == 200 and r.json()["marked"] == 1)
check("labels: only_unprinted hides it", not any(x["unique_code"] == "P3-SCAN-1" for x in client.get("/tools/labels?kind=agency&only_unprinted=true", headers=auth(charge101_token)).json()))
check("labels: cross-agency mark is ignored", client.post("/tools/labels/printed", json={"kind": "agency", "ids": [_t3]}, headers=auth(charge202_token)).json()["marked"] == 0)

# Recherche globale
r = client.get("/search?q=P3-SCAN-1", headers=auth(gars101a_token))
check("search: finds a tool by its unique code", r.status_code == 200 and any("P3-SCAN-1" in i["subtitle"] for cat in r.json()["categories"] for i in cat["items"]))
check("search: too-short queries return no categories", client.get("/search?q=P", headers=auth(gars101a_token)).json()["categories"] == [])
check("search: never crosses agencies", not any("P3-SCAN-1" in i["subtitle"] for cat in client.get("/search?q=P3-SCAN-1", headers=auth(charge202_token)).json()["categories"] for i in cat["items"]))
check("search: personnel do not see the team category", not any(cat["label"] == "Équipe" for cat in client.get("/search?q=directeur101", headers=auth(gars101a_token)).json()["categories"]))
check("search: managers can find a teammate", any(cat["label"] == "Équipe" for cat in client.get("/search?q=directeur101", headers=auth(charge101_token)).json()["categories"]))
check("search requires authentication", client.get("/search?q=abc").status_code == 401)
