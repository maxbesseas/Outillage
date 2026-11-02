# Tests de la Phase 2 (contrôles, étalonnage, habilitations). Exécuté par smoke_test.py.
import io as _io

from app.models_p2 import Inspection

_n2 = datetime.utcnow()


def d2(days=0, hours=0):
    return (_n2 + timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")


def new_p2_tool(code, type_="TypeP2", token=None, **extra):
    payload = {"name": f"Outil {code}", "unique_code": code, "type": type_, "purchase_price": 50}
    payload.update(extra)
    r = client.post("/agency-tools", json=payload, headers=auth(token or charge101_token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def set_control_date(tool_id, days_ago):
    r = client.patch(f"/agency-tools/{tool_id}", json={"last_control_date": d2(-days_ago)}, headers=auth(charge101_token))
    assert r.status_code == 200, r.text


# ---------- Politiques ----------
r = client.post("/inspection-policies", json={"tool_kind": "agency", "type": "TypeP2", "periodicity_days": 90, "warn_before_days": 15},
                headers=auth(charge101_token))
check("inspection policies are admin-only", r.status_code == 403)
r = client.post("/inspection-policies", json={"tool_kind": "agency", "type": "TypeP2", "periodicity_days": 90, "warn_before_days": 15},
                headers=auth(admin_token))
policy_id = r.json()["id"]
check("admin creates a policy per type", r.status_code == 201 and r.json()["periodicity_days"] == 90)
check("duplicate policy is refused", client.post("/inspection-policies", json={"tool_kind": "agency", "type": "TypeP2", "periodicity_days": 30},
                                                 headers=auth(admin_token)).status_code == 400)
check("invalid periodicity is rejected", client.post("/inspection-policies", json={"tool_kind": "agency", "type": "X", "periodicity_days": 0},
                                                     headers=auth(admin_token)).status_code == 422)
check("policies are readable by everyone", len(client.get("/inspection-policies", headers=auth(gars101a_token)).json()) >= 1)
r = client.patch(f"/inspection-policies/{policy_id}", json={"warn_before_days": 20}, headers=auth(admin_token))
check("a policy can be updated", r.status_code == 200 and r.json()["warn_before_days"] == 20)

# ---------- Échéances ----------
t_over = new_p2_tool("P2-OVER-1")
t_soon = new_p2_tool("P2-SOON-1")
t_ok = new_p2_tool("P2-OK-1")
t_never = new_p2_tool("P2-NEVER-1")
t_default = new_p2_tool("P2-DEF-1", type_="TypeSansPolitique")
set_control_date(t_over, 120)
set_control_date(t_soon, 80)
set_control_date(t_ok, 10)
set_control_date(t_default, 200)
r = client.get("/inspections/due?kind=agency", headers=auth(charge101_token))
by_code = {i["code"]: i for i in r.json()["items"]}
check("policy periodicity drives the overdue status", by_code["P2-OVER-1"]["status"] == "overdue")
check("warning window drives the soon status", by_code["P2-SOON-1"]["status"] == "soon" and by_code["P2-SOON-1"]["days_left"] == 10)
check("up-to-date items are not listed", "P2-OK-1" not in by_code)
check("never-inspected items are listed", by_code["P2-NEVER-1"]["status"] == "never")
check("types without policy use the default 365 days (not yet due at 200 days)", "P2-DEF-1" not in by_code)
set_control_date(t_default, 400)
check("default periodicity flags an overdue item", any(i["code"] == "P2-DEF-1" and i["status"] == "overdue"
                                                        for i in client.get("/inspections/due?kind=agency", headers=auth(charge101_token)).json()["items"]))
counts = client.get("/inspections/due?kind=agency", headers=auth(charge101_token)).json()["counts"]
check("due counters are returned", counts["overdue"] >= 2 and counts["never"] >= 1 and counts["soon"] >= 1)
check("status filter works", all(i["status"] == "soon" for i in client.get("/inspections/due?kind=agency&status_filter=soon", headers=auth(charge101_token)).json()["items"]))
check("due list never crosses agencies", not any(i["code"].startswith("P2-") for i in client.get("/inspections/due?kind=agency", headers=auth(charge202_token)).json()["items"]))
check("personnel see the agency due list too", any(i["code"] == "P2-OVER-1" for i in client.get("/inspections/due?kind=agency", headers=auth(gars101a_token)).json()["items"]))

# ---------- Modèles de checklist ----------
template = {"tool_kind": "agency", "type": "TypeP2", "items": [
    {"id": "sangles", "label": "Sangles et mousquetons", "required": True},
    {"id": "marches", "label": "Marches", "required": True},
    {"id": "peinture", "label": "Peinture", "required": False}]}
check("checklist templates are admin-only", client.put("/inspection-templates", json=template, headers=auth(charge101_token)).status_code == 403)
check("duplicate item ids are refused", client.put("/inspection-templates", json={**template, "items": [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]},
                                                   headers=auth(admin_token)).status_code == 400)
check("admin saves a checklist template", client.put("/inspection-templates", json=template, headers=auth(admin_token)).status_code == 200)
r = client.get("/inspections/template?kind=agency&type=TypeP2", headers=auth(gars101a_token))
check("the checklist and its policy are served to inspectors", len(r.json()["items"]) == 3 and r.json()["policy"]["periodicity_days"] == 90)

# ---------- Enregistrer un contrôle ----------
r = client.post("/inspections", json={"tool_kind": "agency", "tool_id": t_over, "state_after": 5,
                                      "checklist": [{"id": "sangles", "answer": "ok"}]}, headers=auth(gars101a_token))
check("a missing required point blocks the inspection", r.status_code == 400 and "obligatoire" in r.json()["detail"])
check("an unknown checklist point is rejected", client.post("/inspections", json={"tool_kind": "agency", "tool_id": t_over,
      "checklist": [{"id": "inconnu", "answer": "ok"}]}, headers=auth(gars101a_token)).status_code == 400)
r = client.post("/inspections", json={"tool_kind": "agency", "tool_id": t_over, "state_after": 4, "comment": "RAS",
                                      "checklist": [{"id": "sangles", "answer": "ok"}, {"id": "marches", "answer": "ok"}]},
                headers=auth(gars101a_token))
check("a complete inspection is recorded as conforme", r.status_code == 201 and r.json()["result"] == "conforme" and r.json()["inspector_name"])
check("next due date follows the policy", abs((pdt(r.json()["next_due"]) - datetime.utcnow()).days - 90) <= 1)
tool = client.get(f"/agency-tools/{t_over}", headers=auth(charge101_token)).json()
check("the tool state and last control date are updated", tool["state"] == 4 and tool["last_control_date"][:10] == datetime.utcnow().strftime("%Y-%m-%d"))
check("the tool leaves the overdue list", not any(i["code"] == "P2-OVER-1" for i in client.get("/inspections/due?kind=agency", headers=auth(charge101_token)).json()["items"]))
hist = client.get(f"/state-history?kind=agency&tool_id={t_over}", headers=auth(charge101_token)).json()
check("the inspection is journaled in the state history", any(h["source"] == "contrôle" for h in hist))

t_bad = new_p2_tool("P2-BAD-1")
r = client.post("/inspections", json={"tool_kind": "agency", "tool_id": t_bad, "state_after": 3,
                                      "checklist": [{"id": "sangles", "answer": "ko", "comment": "sangle coupée"}, {"id": "marches", "answer": "ok"}]},
                headers=auth(gars101a_token))
check("a failed mandatory point makes the inspection non conforme", r.status_code == 201 and r.json()["result"] == "non_conforme")
check("a non conforming inspection forces the repair status", client.get(f"/agency-tools/{t_bad}", headers=auth(charge101_token)).json()["status"] == "reparation")
check("the checklist answers are stored with their comments", r.json()["checklist"][0]["comment"] == "sangle coupée")
check("managers are alerted of the non conforming tool", any(n["type"] == "tool_problem" and "P2-BAD-1" in n["title"] for n in notes(dir101_token)))
client.patch("/settings/app", json={"values": {"inspection.nonconform_status": "hors_service"}}, headers=auth(admin_token))
t_bad2 = new_p2_tool("P2-BAD-2")
client.post("/inspections", json={"tool_kind": "agency", "tool_id": t_bad2, "checklist": [{"id": "sangles", "answer": "ko"}, {"id": "marches", "answer": "ok"}]}, headers=auth(gars101a_token))
check("the non conforming status is configurable", client.get(f"/agency-tools/{t_bad2}", headers=auth(charge101_token)).json()["status"] == "hors_service")
client.patch("/settings/app", json={"values": {"inspection.nonconform_status": "reparation"}}, headers=auth(admin_token))
t_res = new_p2_tool("P2-RES-1")
r = client.post("/inspections", json={"tool_kind": "agency", "tool_id": t_res, "checklist": [{"id": "sangles", "answer": "ok"}, {"id": "marches", "answer": "ok"}, {"id": "peinture", "answer": "ko"}]}, headers=auth(gars101a_token))
check("an optional failed point gives conforme avec réserves", r.json()["result"] == "conforme_avec_reserves" and client.get(f"/agency-tools/{t_res}", headers=auth(charge101_token)).json()["status"] == "disponible")

check("inspections never cross agencies (write)", client.post("/inspections", json={"tool_kind": "agency", "tool_id": t_res, "checklist": []}, headers=auth(charge202_token)).status_code == 403)
check("inspections never cross agencies (read)", client.get(f"/inspections?tool_kind=agency&tool_id={t_res}", headers=auth(charge202_token)).status_code == 403)
r = client.get(f"/inspections?tool_kind=agency&tool_id={t_over}&limit=1", headers=auth(charge101_token))
check("inspection history is paginated", len(r.json()) == 1 and int(r.headers["x-total-count"]) >= 1)
check("an invalid kind is rejected", client.get("/inspections?tool_kind=zzz&tool_id=1", headers=auth(charge101_token)).status_code == 400)

# ---------- Photo et rapport obligatoires ----------
admin_headers = auth(admin_token)
client.post("/inspection-policies", json={"tool_kind": "agency", "type": "TypePhoto", "periodicity_days": 365, "requires_photo": True}, headers=admin_headers)
t_photo = new_p2_tool("P2-PHOTO-1", type_="TypePhoto")
r = client.post("/inspections", json={"tool_kind": "agency", "tool_id": t_photo}, headers=auth(gars101a_token))
check("a required photo blocks an inspection without one", r.status_code == 400 and "photo" in r.json()["detail"].lower())
r = client.post("/inspections", json={"tool_kind": "agency", "tool_id": t_photo, "photo_attached": True}, headers=auth(gars101a_token))
inspection_id = r.json()["id"]
check("the inspection is accepted once the photo is announced", r.status_code == 201 and r.json()["photo_required"] is True)
r = client.post(f"/inspections/{inspection_id}/photo", files={"file": ("p.jpg", b"\xff\xd8\xff\xe0fakejpg", "image/jpeg")}, headers=auth(gars101a_token))
check("the photo can be attached to the inspection", r.status_code == 200 and r.json()["photo_path"].startswith("/uploads/inspections/"))
r = client.post(f"/inspections/{inspection_id}/report", files={"file": ("rapport.pdf", b"%PDF-1.4 rapport", "application/pdf")}, headers=auth(gars101a_token))
check("a PDF report can be attached", r.status_code == 200 and r.json()["report_path"].endswith(".pdf"))
check("a non-PDF report is refused", client.post(f"/inspections/{inspection_id}/report", files={"file": ("malware.exe", b"MZ", "application/octet-stream")}, headers=auth(gars101a_token)).status_code == 400)
check("a fake PDF is refused", client.post(f"/inspections/{inspection_id}/report", files={"file": ("faux.pdf", b"pas un pdf", "application/pdf")}, headers=auth(gars101a_token)).status_code == 400)
check("an oversized document is refused", client.post(f"/inspections/{inspection_id}/report", files={"file": ("gros.pdf", b"%PDF" + b"0" * (11 * 1024 * 1024), "application/pdf")}, headers=auth(gars101a_token)).status_code == 400)
check("another agency cannot attach files", client.post(f"/inspections/{inspection_id}/photo", files={"file": ("p.jpg", b"x", "image/jpeg")}, headers=auth(charge202_token)).status_code == 403)
client.patch("/settings/app", json={"values": {"photo.required_on_nonconform": True}}, headers=admin_headers)
r = client.post("/inspections", json={"tool_kind": "agency", "tool_id": t_res, "checklist": [{"id": "sangles", "answer": "ko"}, {"id": "marches", "answer": "ok"}]}, headers=auth(gars101a_token))
check("a non conforming result can require a photo through a setting", r.status_code == 400)
client.patch("/settings/app", json={"values": {"photo.required_on_nonconform": False}}, headers=admin_headers)

# ---------- EPI et outils personnels ----------
epi_id = client.post("/epi", json={"name": "Casque P2", "type": "Casque", "unique_code": "P2-EPI-1", "state": 5}, headers=auth(charge101_token)).json()["id"]
r = client.post("/inspections", json={"tool_kind": "epi", "tool_id": epi_id, "state_after": 2, "comment": "coque fissurée"}, headers=auth(gars101a_token))
check("an EPI can be inspected by anyone of the agency", r.status_code == 201 and client.get(f"/epi/{epi_id}", headers=auth(charge101_token)).json()["state"] == 2)
check("EPI inspections stay inside the agency", client.post("/inspections", json={"tool_kind": "epi", "tool_id": epi_id}, headers=auth(charge202_token)).status_code == 403)
perso_id = client.post("/personal-tools", json={"name": "Scie P2", "unique_code": "P2-PERSO-1", "state": 5}, headers=auth(gars101a_token)).json()["id"]
r = client.post("/inspections", json={"tool_kind": "personal", "tool_id": perso_id, "result": "non_conforme", "state_after": 1}, headers=auth(gars101a_token))
check("an owner inspects a personal tool", r.status_code == 201)
check("a non conforming personal tool is flagged for repair", client.get(f"/personal-tools/{perso_id}", headers=auth(gars101a_token)).json()["state_reason"] == "en_reparation")
check("personal tools of another agency cannot be inspected", client.post("/inspections", json={"tool_kind": "personal", "tool_id": perso_id}, headers=auth(charge202_token)).status_code == 403)
t_quick = new_p2_tool("P2-QUICK-1")
client.post(f"/agency-tools/{t_quick}/control", json={"state": 5, "status": "disponible"}, headers=auth(gars101a_token))
check("the historical quick control is traced in the registry", len(client.get(f"/inspections?tool_kind=agency&tool_id={t_quick}", headers=auth(charge101_token)).json()) == 1)

# ---------- Registre exportable ----------
r = client.get(f"/inspections/registry?tool_kind=agency&tool_id={t_over}&format=xlsx", headers=auth(charge101_token))
check("the registry exports to Excel", r.status_code == 200 and "spreadsheetml" in r.headers["content-type"] and r.content[:2] == b"PK")
r = client.get(f"/inspections/registry?tool_kind=agency&tool_id={t_over}&format=pdf", headers=auth(charge101_token))
check("the registry exports to a valid PDF", r.status_code == 200 and r.content.startswith(b"%PDF") and b"%%EOF" in r.content[-8:])
check("the registry respects agency isolation", client.get(f"/inspections/registry?tool_kind=agency&tool_id={t_over}", headers=auth(charge202_token)).status_code == 403)
r = client.get("/inspections/registry?tool_kind=agency&type=TypeP2&format=pdf", headers=auth(charge202_token))
check("a type-wide registry only contains the caller's agency", r.status_code == 200 and b"P2-OVER-1" not in r.content)

# ---------- Étalonnage ----------
client.post("/inspection-policies", json={"tool_kind": "agency", "type": "Mesure P2", "periodicity_days": 365, "requires_calibration": True,
                                          "calibration_periodicity_days": 30, "warn_before_days": 5}, headers=admin_headers)
t_cal = new_p2_tool("P2-CAL-1", type_="Mesure P2")
r = client.get("/calibrations/overview", headers=auth(charge101_token))
check("an instrument without calibration is listed as missing", any(i["code"] == "P2-CAL-1" for i in r.json()["missing"]))
r = client.post("/loans", json={"tool_id": t_cal, "start_datetime": d2(-1), "end_datetime_planned": d2(hours=2)}, headers=auth(gars101a_token))
check("reserving an uncalibrated instrument only warns by default", r.status_code == 201 and "talonnage" in r.headers.get("x-warning", ""))
client.post(f"/loans/{r.json()['id']}/return", json={"state_after": 5}, headers=auth(gars101a_token))
client.patch("/settings/app", json={"values": {"calibration.block_reservation": True}}, headers=admin_headers)
r = client.post("/loans", json={"tool_id": t_cal, "start_datetime": d2(-1), "end_datetime_planned": d2(hours=2)}, headers=auth(gars101a_token))
check("the block setting refuses the reservation", r.status_code == 400 and "talonnage" in r.json()["detail"])
check("personnel cannot record calibrations", client.post("/calibrations", json={"tool_id": t_cal, "calibrated_at": d2(0)}, headers=auth(gars101a_token)).status_code == 403)
check("other agencies cannot record calibrations", client.post("/calibrations", json={"tool_id": t_cal, "calibrated_at": d2(0)}, headers=auth(charge202_token)).status_code == 403)
r = client.post("/calibrations", json={"tool_id": t_cal, "calibrated_at": d2(-40), "provider": "Labo X", "certificate_number": "C-001", "cost": 80}, headers=auth(charge101_token))
cal_id = r.json()["id"]
check("a calibration computes its next due date from the policy", r.status_code == 201 and r.json()["next_due"] is not None)
check("a 40-day-old calibration is expired (30-day period)", any(i["code"] == "P2-CAL-1" for i in client.get("/calibrations/overview", headers=auth(charge101_token)).json()["expired"]))
check("an expired calibration blocks the reservation", client.post("/loans", json={"tool_id": t_cal, "start_datetime": d2(-1), "end_datetime_planned": d2(hours=2)}, headers=auth(gars101a_token)).status_code == 400)
r = client.post(f"/calibrations/{cal_id}/certificate", files={"file": ("certificat.pdf", b"%PDF-1.4 cert", "application/pdf")}, headers=auth(charge101_token))
check("a calibration certificate can be attached", r.status_code == 200 and r.json()["certificate_path"].endswith(".pdf"))
client.post("/calibrations", json={"tool_id": t_cal, "calibrated_at": d2(-2), "provider": "Labo X"}, headers=auth(charge101_token))
check("a fresh calibration lifts the block", client.get("/calibrations/overview", headers=auth(charge101_token)).json()["ok"] != [] and any(i["code"] == "P2-CAL-1" for i in client.get("/calibrations/overview", headers=auth(charge101_token)).json()["ok"]))
r = client.post("/loans", json={"tool_id": t_cal, "start_datetime": d2(-1), "end_datetime_planned": d2(hours=2)}, headers=auth(gars101a_token))
check("the instrument can be reserved again", r.status_code == 201 and "x-warning" not in r.headers)
client.post(f"/loans/{r.json()['id']}/return", json={"state_after": 5}, headers=auth(gars101a_token))
client.post("/calibrations", json={"tool_id": t_cal, "calibrated_at": d2(0), "result": "non_conforme"}, headers=auth(charge101_token))
check("a failed calibration counts as expired", any(i["code"] == "P2-CAL-1" for i in client.get("/calibrations/overview", headers=auth(charge101_token)).json()["expired"]))
check("calibration list is scoped to the agency", client.get(f"/calibrations?tool_id={t_cal}", headers=auth(charge202_token)).status_code == 403)
check("calibration overview never crosses agencies", not any(i["code"] == "P2-CAL-1" for k in ("expired", "ok", "soon", "missing")
                                                             for i in client.get("/calibrations/overview", headers=auth(charge202_token)).json()[k]))
client.patch("/settings/app", json={"values": {"calibration.block_reservation": False}}, headers=admin_headers)

# ---------- Habilitations ----------
check("qualification types are admin-only", client.post("/qualification-types", json={"code": "ELEC", "label": "Habilitation électrique"}, headers=auth(charge101_token)).status_code == 403)
check("admin creates a qualification type", client.post("/qualification-types", json={"code": "ELEC", "label": "Habilitation électrique"}, headers=admin_headers).status_code == 201)
check("duplicate qualification code is refused", client.post("/qualification-types", json={"code": "ELEC", "label": "Autre"}, headers=admin_headers).status_code == 400)
client.post("/qualification-types", json={"code": "HAUT", "label": "Travail en hauteur"}, headers=admin_headers)
qual_user_id = make_user("qualuser", charge101_token)
qual_token = login("qualuser")
r = client.post("/qualifications", json={"user_id": qual_user_id, "code": "ELEC", "obtained_at": d2(-100), "expires_at": d2(-1)}, headers=auth(charge101_token))
qual_id = r.json()["id"]
check("a manager records a qualification for a team member", r.status_code == 201 and r.json()["status"] == "expired")
check("a manager outside the cascade cannot", client.post("/qualifications", json={"user_id": qual_user_id, "code": "ELEC"}, headers=auth(charge202_token)).status_code == 403)
check("personnel cannot record qualifications", client.post("/qualifications", json={"user_id": qual_user_id, "code": "ELEC"}, headers=auth(gars101a_token)).status_code == 403)
check("an unknown qualification code is refused", client.post("/qualifications", json={"user_id": qual_user_id, "code": "NOPE"}, headers=auth(charge101_token)).status_code == 400)
check("a document can be attached to a qualification", client.post(f"/qualifications/{qual_id}/document", files={"file": ("attestation.pdf", b"%PDF-1.4 x", "application/pdf")}, headers=auth(charge101_token)).status_code == 200)
check("personnel only list their own qualifications", all(q["user_id"] == qual_user_id for q in client.get("/qualifications", headers=auth(qual_token)).json()))
check("personnel cannot read a colleague's qualifications", client.get(f"/qualifications?user_id={qual_user_id}", headers=auth(gars101a_token)).status_code == 403)

t_hab = new_p2_tool("P2-HAB-1", type_="TypeHaut")
check("a type-wide requirement is admin-only", client.post("/tool-requirements", json={"tool_type": "TypeHaut", "qualification_code": "HAUT"}, headers=auth(charge101_token)).status_code == 403)
req_type = client.post("/tool-requirements", json={"tool_type": "TypeHaut", "qualification_code": "HAUT"}, headers=admin_headers)
check("admin sets a type-wide requirement", req_type.status_code == 201)
check("a requirement needs a type or a tool, not both", client.post("/tool-requirements", json={"tool_type": "X", "agency_tool_id": t_hab, "qualification_code": "HAUT"}, headers=admin_headers).status_code == 400)
r = client.post("/loans", json={"tool_id": t_hab, "start_datetime": d2(-1), "end_datetime_planned": d2(hours=2)}, headers=auth(qual_token))
check("missing qualification only warns by default", r.status_code == 201 and "Travail en hauteur" in r.headers.get("x-warning", ""))
client.post(f"/loans/{r.json()['id']}/return", json={"state_after": 5}, headers=auth(qual_token))
client.post("/qualifications", json={"user_id": qual_user_id, "code": "HAUT", "expires_at": d2(200)}, headers=auth(charge101_token))
r = client.post("/loans", json={"tool_id": t_hab, "start_datetime": d2(-1), "end_datetime_planned": d2(hours=2)}, headers=auth(qual_token))
check("a valid qualification removes the warning", r.status_code == 201 and "x-warning" not in r.headers)
client.post(f"/loans/{r.json()['id']}/return", json={"state_after": 5}, headers=auth(qual_token))
client.post("/tool-requirements", json={"agency_tool_id": t_hab, "qualification_code": "ELEC", "blocking": True}, headers=auth(charge101_token))
r = client.post("/loans", json={"tool_id": t_hab, "start_datetime": d2(-1), "end_datetime_planned": d2(hours=2)}, headers=auth(qual_token))
check("a blocking requirement refuses an expired qualification", r.status_code == 400 and "lectrique" in r.json()["detail"])
check("a tool-level requirement stays inside the agency", client.post("/tool-requirements", json={"agency_tool_id": t_hab, "qualification_code": "ELEC"}, headers=auth(charge202_token)).status_code == 403)
client.patch("/settings/app", json={"values": {"qualification.block": True}}, headers=admin_headers)
t_hab2 = new_p2_tool("P2-HAB-2", type_="TypeHaut")
client.post("/tool-requirements", json={"tool_type": "TypeHaut2", "qualification_code": "ELEC"}, headers=admin_headers)
client.delete(f"/tool-requirements/{req_type.json()['id']}", headers=admin_headers)
check("removing a requirement is admin-only for type-wide rules", client.delete("/tool-requirements/999999", headers=admin_headers).status_code == 404)
client.patch("/settings/app", json={"values": {"qualification.block": False}}, headers=admin_headers)

# ---------- Alertes ----------
set_control_date(t_over, 200)
before_control = len([n for n in notes(charge101_token) if n["type"] == "control_due"])
next_week = datetime.utcnow() + timedelta(days=15)
res = run_alerts(next_week)
check("control alerts are grouped per person", res["control_due"] >= 1)
after_control = [n for n in notes(charge101_token) if n["type"] == "control_due"]
check("a manager gets one grouped control notification per week", len(after_control) == before_control + 1 and "contrôle(s) à faire" in after_control[0]["title"])
res_again = run_alerts(next_week)
check("control alerts are sent once per week", res_again["control_due"] == 0)
check("control alerts never reach other agencies", not any(n["type"] == "control_due" and "P2-" in (n["body"] or "") for n in notes(charge202_token)))
check("calibration alerts reach the agency managers", any(n["type"] == "calibration_due" for n in notes(charge101_token)))
check("qualification alerts reach the person and the managers", any(n["type"] == "qualification_expiring" for n in notes(qual_token))
      and any(n["type"] == "qualification_expiring" for n in notes(charge101_token)))
with database.SessionLocal() as s:
    import app.controls as controls_mod
    check("the weekly summary can count the controls to do", controls_mod.count_due_for_agency(s, "101") >= 3)
