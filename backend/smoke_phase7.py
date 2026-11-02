# Tests de la Phase 7 (amortissement, TCO, pertes, budgets, exports, clés d'API). Exécuté par smoke_test.py.
import csv as _csv
import io as _io2
import json as _json

from openpyxl import load_workbook as _load_wb


def _ago(years):
    return (datetime.utcnow() - timedelta(days=int(365.25 * years))).strftime("%Y-%m-%dT%H:%M:%S")


def mk7(code, token=None, **extra):
    payload = {"name": f"Outil {code}", "unique_code": code, "type": "Type P7", "purchase_price": 1000, "purchase_date": _ago(2)}
    payload.update(extra)
    r = client.post("/agency-tools", json=payload, headers=auth(token or charge101_token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------- Amortissement ----------
r = client.put("/finance/depreciation-policies", json={"type": "Type P7", "years": 4, "residual_pct": 0}, headers=auth(admin_token))
POL = r.json().get("id")
check("admin sets a depreciation policy per type", r.status_code == 200 and r.json()["years"] == 4)
check("non-admins cannot set policies", client.put("/finance/depreciation-policies", json={"type": "X", "years": 3}, headers=auth(dir101_token)).status_code == 403)
check("policy years must be positive", client.put("/finance/depreciation-policies", json={"type": "X", "years": 0}, headers=auth(admin_token)).status_code == 422)
check("policy residual is bounded", client.put("/finance/depreciation-policies", json={"type": "X", "years": 3, "residual_pct": 150}, headers=auth(admin_token)).status_code == 422)
check("policies are readable by managers", any(p["type"] == "Type P7" for p in client.get("/finance/depreciation-policies", headers=auth(charge101_token)).json()["policies"]))
check("policies are not readable by personnel", client.get("/finance/depreciation-policies", headers=auth(gars101a_token)).status_code == 403)

A1 = mk7("P7-A1")
A_old = mk7("P7-OLD", purchase_date=_ago(10))
A_inc = mk7("P7-INC", purchase_price=0, purchase_date=None)
res = client.get("/finance/assets", headers=auth(charge101_token)).json()
line = next(l for l in res["lines"] if l["tool_id"] == A1)
check("linear depreciation: 2 years of 4 -> half the value", abs(line["book_value"] - 500) < 5 and abs(line["accumulated"] - 500) < 5 and line["years"] == 4)
old = next(l for l in res["lines"] if l["tool_id"] == A_old)
check("a fully depreciated tool has a zero book value", old["book_value"] == 0 and old["fully_depreciated"] is True)
check("tools without price/date are flagged incomplete", next(l for l in res["lines"] if l["tool_id"] == A_inc)["complete"] is False and res["totals"]["incomplete"] >= 1)
check("totals add up", abs(res["totals"]["acquisition"] - res["totals"]["accumulated"] - res["totals"]["book_value"]) < 0.5)
check("assets are scoped to the agency", not any(l["tool_id"] == A1 for l in client.get("/finance/assets", headers=auth(charge202_token)).json()["lines"]))
check("assets are manager-only", client.get("/finance/assets", headers=auth(gars101a_token)).status_code == 403)
client.put("/finance/depreciation-policies", json={"type": "Type P7", "years": 8, "residual_pct": 25}, headers=auth(admin_token))
line = next(l for l in client.get("/finance/assets", headers=auth(charge101_token)).json()["lines"] if l["tool_id"] == A1)
check("residual value is honoured", abs(line["accumulated"] - (1000 * 0.75 * 2 / 8)) < 5)
client.put("/finance/depreciation-policies", json={"type": "Type P7", "years": 4, "residual_pct": 0}, headers=auth(admin_token))

# ---------- TCO ----------
tk = client.post("/maintenance-tickets", json={"tool_kind": "agency", "tool_id": A1, "category": "panne", "severity": "moyenne"}, headers=auth(gars101a_token)).json()["id"]
client.patch(f"/maintenance-tickets/{tk}", json={"actual_cost": 120.5}, headers=auth(charge101_token))
t = next(x for x in client.get("/finance/tco", headers=auth(charge101_token)).json()["tools"] if x["tool_id"] == A1)
check("TCO = purchase + repairs", t["purchase_price"] == 1000 and t["repair_cost"] == 120.5 and t["tco"] == 1120.5)
check("TCO is manager-only and scoped", client.get("/finance/tco", headers=auth(gars101a_token)).status_code == 403 and not any(x["tool_id"] == A1 for x in client.get("/finance/tco", headers=auth(charge202_token)).json()["tools"]))

# ---------- Pertes et litiges ----------
r = client.post("/losses", json={"tool_id": A1, "kind": "vol", "circumstances": "Vol camionnette", "police_report_ref": "PV-2026-1", "insurance_status": "declared", "insurance_ref": "SIN-42"}, headers=auth(charge101_token))
LOSS = r.json().get("id")
check("a manager records a loss (value defaults to the price)", r.status_code == 201 and r.json()["declared_value"] == 1000 and r.json()["net_loss"] == 1000)
check("personnel cannot record a loss", client.post("/losses", json={"tool_id": A1, "kind": "vol"}, headers=auth(gars101a_token)).status_code == 403)
check("an unknown loss kind is refused", client.post("/losses", json={"tool_id": A1, "kind": "zzz"}, headers=auth(charge101_token)).status_code == 400)
check("an invalid insurance status is refused", client.post("/losses", json={"tool_id": A1, "kind": "vol", "insurance_status": "?"}, headers=auth(charge101_token)).status_code == 400)
check("another agency cannot declare a loss on this tool", client.post("/losses", json={"tool_id": A1, "kind": "vol"}, headers=auth(charge202_token)).status_code == 403)
check("another agency cannot edit the loss", client.patch(f"/losses/{LOSS}", json={"litigation_status": "open"}, headers=auth(charge202_token)).status_code == 403)
r = client.patch(f"/losses/{LOSS}", json={"insurance_status": "accepted", "refunded_amount": 400, "litigation_status": "open", "litigation_note": "Expertise en cours"}, headers=auth(charge101_token))
check("insurance and litigation are tracked", r.status_code == 200 and r.json()["net_loss"] == 600 and r.json()["litigation_status"] == "open")
check("negative refunds are refused", client.patch(f"/losses/{LOSS}", json={"refunded_amount": -5}, headers=auth(charge101_token)).status_code == 422)
lst = client.get("/losses", headers=auth(dir101_token)).json()
check("loss totals are aggregated", lst["totals"]["net"] >= 600 and lst["totals"]["open_litigations"] >= 1)
check("losses are scoped to the agency", client.get("/losses", headers=auth(charge202_token)).json()["records"] == [] or not any(x["id"] == LOSS for x in client.get("/losses", headers=auth(charge202_token)).json()["records"]))
A_stolen = mk7("P7-STOLEN")
client.post(f"/agency-tools/{A_stolen}/exit", json={"reason": "vole", "note": "Vol chantier"}, headers=auth(dir101_token))
check("a theft exit opens a loss record automatically", any(x["tool_id"] == A_stolen and x["kind"] == "vol" for x in client.get("/losses", headers=auth(dir101_token)).json()["records"]))

# ---------- Budgets et prévisions ----------
year = datetime.utcnow().year
r = client.put("/finance/budgets", json={"year": year, "category": "achats", "amount": 5000}, headers=auth(dir101_token))
check("a director sets a budget", r.status_code == 200 and next(x for x in r.json()["rows"] if x["category"] == "achats")["planned"] == 5000)
check("a chargé d'affaires cannot set a budget", client.put("/finance/budgets", json={"year": year, "category": "achats", "amount": 1}, headers=auth(charge101_token)).status_code == 403)
check("an invalid budget category is refused", client.put("/finance/budgets", json={"year": year, "category": "cafe", "amount": 1}, headers=auth(dir101_token)).status_code == 400)
check("a negative budget is refused", client.put("/finance/budgets", json={"year": year, "category": "achats", "amount": -1}, headers=auth(dir101_token)).status_code == 422)
client.put("/finance/budgets", json={"year": year, "category": "pertes", "amount": 1000}, headers=auth(dir101_token))
b = client.get(f"/finance/budgets?year={year}", headers=auth(charge101_token)).json()
achats = next(x for x in b["rows"] if x["category"] == "achats")
check("budget actuals reflect purchases of the year", achats["actual"] >= 0 and achats["remaining"] == achats["planned"] - achats["actual"])
pertes = next(x for x in b["rows"] if x["category"] == "pertes")
check("budget actuals reflect net losses", pertes["actual"] >= 600)
b202 = client.get(f"/finance/budgets?year={year}", headers=auth(charge202_token)).json()
check("budgets never leak across agencies", next(x for x in b202["rows"] if x["category"] == "achats")["planned"] == 0)
client.put("/finance/budgets", json={"year": year, "category": "achats", "amount": 7000}, headers=auth(dir101_token))
check("setting a budget again replaces it", next(x for x in client.get(f"/finance/budgets?year={year}", headers=auth(dir101_token)).json()["rows"] if x["category"] == "achats")["planned"] == 7000)

f = client.get("/finance/forecast?months=12", headers=auth(charge101_token)).json()
check("forecast lists tools at end of life", any(r["tool_id"] == A_old and r["overdue"] for r in f["replacements"]) and f["replacements_total"] >= 1000)
check("forecast horizon is bounded", client.get("/finance/forecast?months=9999", headers=auth(charge101_token)).json()["months"] == 60)
check("forecast is manager-only", client.get("/finance/forecast", headers=auth(gars101a_token)).status_code == 403)

# ---------- Exports ----------
A_evil = mk7("P7-EVIL", name="=CMD|' /C calc'!A0")
r = client.get("/exports/tools?format=csv", headers=auth(charge101_token))
text_csv = r.content.decode("utf-8")
check("CSV export is UTF-8 with BOM and ';' separators", r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf") and "Désignation" in text_csv.split("\r\n")[0] and ";" in text_csv.split("\r\n")[0])
rows = list(_csv.reader(_io2.StringIO(text_csv.lstrip("﻿")), delimiter=";"))
check("CSV export neutralises formula injection", any(c.startswith("'=CMD") for row in rows for c in row) and not any(c.startswith("=") for row in rows for c in row))
check("CSV export is scoped to the agency", "P7-A1" in text_csv and "P7-A1" not in client.get("/exports/tools?format=csv", headers=auth(charge202_token)).content.decode("utf-8"))
check("CSV decimals follow the French convention", any("1000,00" in c for row in rows for c in row))
r = client.get("/exports/assets?format=xlsx", headers=auth(charge101_token))
wb = _load_wb(_io2.BytesIO(r.content))
check("Excel export of a dataset", r.status_code == 200 and "attachment" in r.headers["content-disposition"] and wb.sheetnames == ["Actifs"] and wb.active.max_row > 1)
r = client.get("/exports/workbook", headers=auth(dir101_token))
wb = _load_wb(_io2.BytesIO(r.content))
check("multi-sheet workbook", r.status_code == 200 and {"Outils", "Actifs", "Pertes", "Chantiers", "Budgets"} <= set(wb.sheetnames))
evil_cells = [c.value for ws in wb.worksheets for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")]
check("Excel export never contains live formulas", evil_cells == [])
check("unknown dataset -> 404, bad format -> 400", client.get("/exports/nope", headers=auth(charge101_token)).status_code == 404 and client.get("/exports/tools?format=pdf", headers=auth(charge101_token)).status_code == 400)
check("exports are manager-only", client.get("/exports/tools", headers=auth(gars101a_token)).status_code == 403 and client.get("/exports/workbook", headers=auth(gars101a_token)).status_code == 403)
check("exports require authentication", client.get("/exports/tools").status_code == 401)
check("exports are journaled", any(e["action"] == "export" for e in client.get("/audit-log?limit=100", headers=auth(admin_token)).json()))

# ---------- Clés d'API ----------
check("only admins manage API keys", client.post("/api-keys", json={"name": "x"}, headers=auth(dir101_token)).status_code == 403 and client.get("/api-keys", headers=auth(dir101_token)).status_code == 403)
r = client.post("/api-keys", json={"name": "BI agence 101", "agency_number": "101"}, headers=auth(admin_token))
KEY, KEY_ID = r.json().get("key"), r.json().get("id")
check("admin creates a key shown once", r.status_code == 201 and KEY.startswith("fk_") and len(KEY) > 30)
check("the key list never shows the secret", KEY not in client.get("/api-keys", headers=auth(admin_token)).text)
check("the secret never reaches the audit log", KEY not in client.get("/audit-log?limit=200", headers=auth(admin_token)).text)
r = client.get("/reports/tools", headers={"X-API-Key": KEY})
check("a key reads its reports", r.status_code == 200 and any(x["unique_code"] == "P7-A1" for x in r.json()) and r.headers["x-total-count"])
check("a key is limited to its agency", all(x["agency_number"] == "101" for x in r.json()))
check("reports need a valid key", client.get("/reports/tools").status_code == 401 and client.get("/reports/tools", headers={"X-API-Key": "fk_nope"}).status_code == 401)
check("a JWT is not accepted as an API key", client.get("/reports/tools", headers={"X-API-Key": admin_token}).status_code == 401)
check("reports are read-only", client.post("/reports/tools", headers={"X-API-Key": KEY}).status_code == 405)
check("unknown report -> 404", client.get("/reports/nope", headers={"X-API-Key": KEY}).status_code == 404)
check("reports paginate", len(client.get("/reports/tools?limit=1", headers={"X-API-Key": KEY}).json()) == 1)
check("the dataset catalogue is listed", any(d["name"] == "assets" for d in client.get("/reports", headers={"X-API-Key": KEY}).json()["datasets"]))
check("last use is recorded", next(k for k in client.get("/api-keys", headers=auth(admin_token)).json() if k["id"] == KEY_ID)["last_used_at"] is not None)
check("revoking a key", client.delete(f"/api-keys/{KEY_ID}", headers=auth(admin_token)).status_code == 204 and client.get("/reports/tools", headers={"X-API-Key": KEY}).status_code == 401)
K2 = client.post("/api-keys", json={"name": "limit test"}, headers=auth(admin_token)).json()["key"]
codes = [client.get("/reports", headers={"X-API-Key": K2}).status_code for _ in range(63)]
check("API keys are rate-limited", codes[0] == 200 and codes[-1] == 429)
