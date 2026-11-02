# Tests de la Phase 4 (réservations et mouvements). Exécuté par smoke_test.py.
import re as _re

import app.reservations as reservations_mod
import app.routers.loans as loans_module
from app.models import Loan, User as UserRow
from app.models_p4 import WaitlistEntry

_n4 = datetime.utcnow()


def d4(days=0, hours=0):
    return (_n4 + timedelta(days=days, hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")


def mk_tool(code, type_="TypeP4", token=None, **extra):
    payload = {"name": f"Outil {code}", "unique_code": code, "type": type_, "purchase_price": 40}
    payload.update(extra)
    r = client.post("/agency-tools", json=payload, headers=auth(token or charge101_token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def reserve(token, tool, start, end, **extra):
    return client.post("/loans", json={"tool_id": tool, "start_datetime": start, "end_datetime_planned": end, **extra}, headers=auth(token))


def tool_status(tool_id):
    return client.get(f"/agency-tools/{tool_id}", headers=auth(charge101_token)).json()["status"]


def user_id_of(username):
    return next(u["id"] for u in client.get("/users", headers=auth(admin_token)).json() if u["username"] == username)


p4a_id = make_user("p4a", charge101_token)
p4b_id = make_user("p4b", charge101_token)
p4a, p4b = login("p4a"), login("p4b")

# ---------- Réservation future ou immédiate ----------
T1 = mk_tool("P4-T1")
r = reserve(p4a, T1, d4(3), d4(3, 2))
loan_future = r.json()["id"]
check("a reservation in the future stays reserved (not out yet)", r.status_code == 201 and r.json()["status"] == "reserve")
check("the tool remains available for other slots", tool_status(T1) == "disponible")
r = reserve(p4b, T1, d4(hours=-1), d4(hours=2))
loan_now = r.json()["id"]
check("another person can take the tool now, before the future slot", r.status_code == 201 and r.json()["status"] == "en_cours")
check("an immediate loan marks the tool as borrowed", tool_status(T1) == "emprunte")
check("a slot overlapping the future reservation is refused", reserve(p4b, T1, d4(3, 1), d4(3, 3)).status_code == 400)
check("the future reservation cannot be picked up while the tool is out", client.post(f"/loans/{loan_future}/checkout", json={}, headers=auth(p4a)).status_code == 400)
client.post(f"/loans/{loan_now}/return", json={"state_after": 5}, headers=auth(p4b))
check("checkout is refused to a colleague without management rights", client.post(f"/loans/{loan_future}/checkout", json={}, headers=auth(p4b)).status_code == 403)
r = client.post(f"/loans/{loan_future}/checkout", json={"state_before": 4}, headers=auth(p4a))
check("checkout turns the reservation into a loan in progress", r.status_code == 200 and r.json()["status"] == "en_cours" and r.json()["checked_out_at"])
check("checkout marks the tool as borrowed and pulls the start to now", tool_status(T1) == "emprunte" and pdt(r.json()["start_datetime"]) <= datetime.utcnow() + timedelta(seconds=5))
check("checkout of a loan already in progress is refused", client.post(f"/loans/{loan_future}/checkout", json={}, headers=auth(p4a)).status_code == 400)
client.post(f"/loans/{loan_future}/return", json={"state_after": 5}, headers=auth(p4a))

T2 = mk_tool("P4-T2")
loan_a = reserve(p4b, T2, d4(hours=-1), d4(hours=5)).json()["id"]
loan_b = reserve(p4a, T2, d4(1), d4(1, 2)).json()["id"]
check("a future reservation is accepted while the tool is out", loan_b is not None)
check("returning a reservation never picked up is refused", client.post(f"/loans/{loan_b}/return", json={"state_after": 5}, headers=auth(p4a)).status_code == 400)
client.delete(f"/loans/{loan_b}", headers=auth(p4a))
check("cancelling a future reservation never frees a tool used by someone else", tool_status(T2) == "emprunte")
client.delete(f"/loans/{loan_a}", headers=auth(p4b))
check("cancelling the loan in progress frees the tool", tool_status(T2) == "disponible")

# ---------- Non-retrait ----------
T3 = mk_tool("P4-T3")
loan_ns = reserve(p4a, T3, d4(hours=2), d4(hours=4)).json()["id"]
with database.SessionLocal() as s:
    cancelled = reservations_mod.expire_no_shows(s, datetime.utcnow() + timedelta(hours=7))
    s.commit()
check("a reservation not picked up in time is cancelled automatically", cancelled >= 1)
check("the automatic cancellation is explained", client.get(f"/loans/{loan_ns}", headers=auth(p4a)).json()["status"] == "annule"
      and any(n["type"] == "no_show" for n in notes(p4a)))
loan_ns2 = reserve(p4a, T3, d4(hours=2), d4(hours=4)).json()["id"]
with database.SessionLocal() as s:
    still = reservations_mod.expire_no_shows(s, datetime.utcnow() + timedelta(hours=3))
    s.commit()
check("the no-show delay is respected", still == 0 and client.get(f"/loans/{loan_ns2}", headers=auth(p4a)).json()["status"] == "reserve")
client.delete(f"/loans/{loan_ns2}", headers=auth(p4a))

# ---------- Indisponibilités ----------
T4 = mk_tool("P4-T4")
r = client.post("/blackouts", json={"tool_id": T4, "start_datetime": d4(10), "end_datetime": d4(12), "reason": "maintenance"}, headers=auth(charge101_token))
blackout_id = r.json()["id"]
check("a manager creates an unavailability period", r.status_code == 201)
r = reserve(p4a, T4, d4(11), d4(11, 2))
check("a reservation inside the unavailability is refused with the reason", r.status_code == 400 and "maintenance" in r.json()["detail"])
check("personnel cannot create unavailability", client.post("/blackouts", json={"tool_id": T4, "start_datetime": d4(30), "end_datetime": d4(31)}, headers=auth(p4a)).status_code == 403)
check("another agency cannot create unavailability", client.post("/blackouts", json={"tool_id": T4, "start_datetime": d4(30), "end_datetime": d4(31)}, headers=auth(charge202_token)).status_code == 403)
check("an invalid reason is refused", client.post("/blackouts", json={"tool_id": T4, "start_datetime": d4(30), "end_datetime": d4(31), "reason": "vacances"}, headers=auth(charge101_token)).status_code == 400)
loan_clash = reserve(p4a, T4, d4(20), d4(20, 2)).json()["id"]
check("unavailability cannot overlap an existing reservation", client.post("/blackouts", json={"tool_id": T4, "start_datetime": d4(20, 1), "end_datetime": d4(21)}, headers=auth(charge101_token)).status_code == 400)
check("unavailability periods are listed for the agency", any(b["id"] == blackout_id for b in client.get(f"/blackouts?tool_id={T4}", headers=auth(p4a)).json()))
check("unavailability never leaks to another agency", client.get(f"/blackouts?tool_id={T4}", headers=auth(charge202_token)).json() == [])
client.delete(f"/loans/{loan_clash}", headers=auth(p4a))
check("an unavailability can be removed", client.delete(f"/blackouts/{blackout_id}", headers=auth(charge101_token)).status_code == 204
      and reserve(p4a, T4, d4(11), d4(11, 2)).status_code == 201)

# ---------- Prolongation, modification, alternatives ----------
T5 = mk_tool("P4-T5")
T5b = mk_tool("P4-T5B")
loan_ext = reserve(p4a, T5, d4(hours=-1), d4(hours=2)).json()["id"]
r = client.post(f"/loans/{loan_ext}/extend", json={"new_end": d4(hours=4)}, headers=auth(p4a))
check("a loan can be extended when the slot is free", r.status_code == 200 and r.json()["end_datetime_planned"] == d4(hours=4) + "Z")
check("a shorter end date is refused", client.post(f"/loans/{loan_ext}/extend", json={"new_end": d4(hours=1)}, headers=auth(p4a)).status_code == 400)
reserve(p4b, T5, d4(hours=6), d4(hours=8))
r = client.post(f"/loans/{loan_ext}/extend", json={"new_end": d4(hours=7)}, headers=auth(p4a))
check("an extension colliding with the next booking is refused", r.status_code == 400 and "réservé" in r.json()["detail"])
alts = client.get(f"/loans/{loan_ext}/alternatives?end={d4(hours=7)}", headers=auth(p4a)).json()
check("equivalent free tools are proposed as alternatives", any(a["code"] == "P4-T5B" for a in alts) and all(a["id"] != T5 for a in alts))
T5c = mk_tool("P4-T5C")
client.patch(f"/agency-tools/{T5c}", json={"status": "reparation"}, headers=auth(charge101_token))
alts2 = client.get(f"/loans/{loan_ext}/alternatives?end={d4(hours=7)}", headers=auth(p4a)).json()
check("alternatives never include unavailable tools", all(a["code"] != "P4-T5C" for a in alts2) and any(a["code"] == "P4-T5B" for a in alts2))
check("site and comment can change on a loan in progress", client.patch(f"/loans/{loan_ext}", json={"site": "Chantier Nord"}, headers=auth(p4a)).json()["site"] == "Chantier Nord")
check("times of a loan in progress are protected", client.patch(f"/loans/{loan_ext}", json={"end_datetime_planned": d4(hours=9)}, headers=auth(p4a)).status_code == 400)
fut = reserve(p4a, T5b, d4(2), d4(2, 2)).json()["id"]
check("a future reservation can be moved", client.patch(f"/loans/{fut}", json={"start_datetime": d4(3), "end_datetime_planned": d4(3, 2)}, headers=auth(p4a)).json()["start_datetime"] == d4(3) + "Z")
other_slot = reserve(p4b, T5b, d4(5), d4(5, 2)).json()["id"]
check("moving onto another booking is refused", client.patch(f"/loans/{fut}", json={"start_datetime": d4(5), "end_datetime_planned": d4(5, 1)}, headers=auth(p4a)).status_code == 400)
events = client.get(f"/loans/{loan_ext}/events", headers=auth(p4a)).json()
check("the loan keeps a modification history", [e["kind"] for e in events][:3] == ["created", "extended", "modified"] and events[0]["user_name"])
check("a colleague from another agency cannot read the history", client.get(f"/loans/{loan_ext}/events", headers=auth(charge202_token)).status_code == 403)

# ---------- Durée maximale et validation ----------
T6 = mk_tool("P4-T6")
check("a tool-level rule can be set by a manager", client.post("/reservation-rules", json={"agency_tool_id": T6, "max_days": 1}, headers=auth(charge101_token)).status_code == 201)
r = reserve(p4a, T6, d4(2), d4(5))
check("a reservation longer than the maximum is refused", r.status_code == 400 and "maximale" in r.json()["detail"])
check("a reservation within the maximum is accepted", reserve(p4a, T6, d4(2), d4(2, 5)).status_code == 201)
check("a type-wide rule is admin-only", client.post("/reservation-rules", json={"tool_type": "TypeAppr", "requires_approval": True}, headers=auth(charge101_token)).status_code == 403)
check("admin sets an approval rule for a type", client.post("/reservation-rules", json={"tool_type": "TypeAppr", "requires_approval": True}, headers=admin_headers).status_code == 201)
check("a rule needs a type or a tool", client.post("/reservation-rules", json={"requires_approval": True}, headers=admin_headers).status_code == 400)

TA = mk_tool("P4-APPR-1", type_="TypeAppr")
r = reserve(p4a, TA, d4(4), d4(4, 2))
appr_loan = r.json()["id"]
check("a governed reservation waits for validation", r.status_code == 201 and r.json()["status"] == "attente_validation")
check("a pending request does not block the tool itself", tool_status(TA) == "disponible")
check("a pending request still holds its slot", reserve(p4b, TA, d4(4, 1), d4(4, 3)).status_code == 400)
check("approvers see the pending request", any(l["id"] == appr_loan and l["tool_name"] for l in client.get("/loans/pending-approval", headers=auth(charge101_token)).json()))
check("personnel see no pending approvals", client.get("/loans/pending-approval", headers=auth(p4b)).json() == [])
check("a colleague cannot approve", client.post(f"/loans/{appr_loan}/approve", json={}, headers=auth(p4b)).status_code == 403)
check("the requester cannot approve", client.post(f"/loans/{appr_loan}/approve", json={}, headers=auth(p4a)).status_code == 403)
check("another agency cannot approve", client.post(f"/loans/{appr_loan}/approve", json={}, headers=auth(charge202_token)).status_code == 403)
check("checkout is refused before validation", client.post(f"/loans/{appr_loan}/checkout", json={}, headers=auth(p4a)).status_code == 400)
r = client.post(f"/loans/{appr_loan}/approve", json={"comment": "OK pour ce chantier"}, headers=auth(charge101_token))
check("a manager approves the request", r.status_code == 200 and r.json()["status"] == "reserve" and r.json()["approved_by_id"])
check("the requester is told of the decision", any(n["type"] == "loan_approval" and "acceptée" in n["title"] for n in notes(p4a)))
check("a decision cannot be taken twice", client.post(f"/loans/{appr_loan}/approve", json={}, headers=auth(charge101_token)).status_code == 400)
rej = reserve(p4a, TA, d4(8), d4(8, 2)).json()["id"]
r = client.post(f"/loans/{rej}/reject", json={"comment": "Matériel réservé à un autre chantier"}, headers=auth(dir101_token))
check("a request can be rejected with a reason", r.status_code == 200 and r.json()["status"] == "refuse")
check("a rejected request frees its slot", reserve(p4b, TA, d4(8), d4(8, 2)).json()["status"] == "attente_validation")
mgr = reserve(charge101_token, TA, d4(15), d4(15, 2))
check("managers are exempt from validation", mgr.status_code == 201 and mgr.json()["status"] == "reserve")

# ---------- Réserver pour un collègue ----------
T7 = mk_tool("P4-T7")
r = reserve(charge101_token, T7, d4(6), d4(6, 2), borrower_id=p4a_id)
check("a manager reserves on behalf of a team member", r.status_code == 201 and r.json()["borrower_id"] == p4a_id and r.json()["created_by_id"] != p4a_id)
check("personnel cannot reserve for a colleague", reserve(p4a, T7, d4(7), d4(7, 2), borrower_id=p4b_id).status_code == 403)
check("a manager cannot reserve for someone outside the team", reserve(charge202_token, T7, d4(7), d4(7, 2), borrower_id=p4a_id).status_code == 403)

# ---------- Séries récurrentes ----------
T8 = mk_tool("P4-T8")
r = client.post("/loans/recurring", json={"tool_id": T8, "start_datetime": d4(20), "end_datetime_planned": d4(20, 2), "frequency": "weekly", "until": d4(41)}, headers=auth(p4a))
series = r.json()["series_id"]
check("a weekly series creates every occurrence", r.status_code == 201 and r.json()["count"] == 4 and all(l["series_id"] == series for l in r.json()["loans"]))
before = len(client.get(f"/loans?scope=agency&tool_id={T8}", headers=auth(charge101_token)).json())
r = client.post("/loans/recurring", json={"tool_id": T8, "start_datetime": d4(6), "end_datetime_planned": d4(6, 2), "frequency": "weekly", "until": d4(34)}, headers=auth(p4b))
check("a series with a conflict is refused entirely and names the date", r.status_code == 400 and "Aucune réservation n'a été créée" in r.json()["detail"])
check("nothing was created by the failed series", len(client.get(f"/loans?scope=agency&tool_id={T8}", headers=auth(charge101_token)).json()) == before)
check("a series is limited to 60 occurrences", client.post("/loans/recurring", json={"tool_id": T8, "start_datetime": d4(100), "end_datetime_planned": d4(100, 1), "frequency": "daily", "until": d4(200)}, headers=auth(p4a)).status_code == 400)
check("a series can be listed", len(client.get(f"/loans/series/{series}", headers=auth(p4a)).json()) == 4)
r = client.patch(f"/loans/series/{series}", json={"delta_minutes": 60}, headers=auth(p4a))
check("a whole series can be shifted", r.status_code == 200 and r.json()["moved"] == 4)
check("a colleague cannot shift someone else's series", client.patch(f"/loans/series/{series}", json={"delta_minutes": 60}, headers=auth(p4b)).status_code == 403)
r = client.delete(f"/loans/series/{series}", headers=auth(p4a))
check("a whole series can be cancelled", r.status_code == 200 and r.json()["cancelled"] == 4)

# ---------- Kits ----------
K1, K2, K3 = mk_tool("P4-K1", "TypeKit"), mk_tool("P4-K2", "TypeKit"), mk_tool("P4-K3", "TypeKit")
check("personnel cannot create kits", client.post("/kits", json={"name": "Kit intérim", "tool_ids": [K1, K2, K3]}, headers=auth(p4a)).status_code == 403)
r = client.post("/kits", json={"name": "Kit intérim", "tool_ids": [K1, K2, K3]}, headers=auth(charge101_token))
kit_id = r.json()["id"]
check("a manager creates a kit", r.status_code == 201 and len(r.json()["tools"]) == 3)
check("a kit cannot mix agencies", client.post("/kits", json={"name": "Mixte", "tool_ids": [K1, mk_tool("P4-OTHER", token=charge202_token)]}, headers=auth(charge101_token)).status_code in (400, 403))
check("kits are private to their agency", client.get("/kits", headers=auth(charge202_token)).json() == [])
check("kits of another agency cannot be reserved", client.post(f"/kits/{kit_id}/reserve", json={"start_datetime": d4(50), "end_datetime_planned": d4(50, 2)}, headers=auth(charge202_token)).status_code == 403)
r = client.post(f"/kits/{kit_id}/reserve", json={"start_datetime": d4(50), "end_datetime_planned": d4(50, 2), "site": "Chantier Kit"}, headers=auth(p4a))
check("reserving a kit reserves all its tools together", r.status_code == 201 and r.json()["count"] == 3 and len({l["series_id"] for l in r.json()["loans"]}) == 1)
r = client.post(f"/kits/{kit_id}/reserve", json={"start_datetime": d4(50, 1), "end_datetime_planned": d4(50, 3)}, headers=auth(p4b))
check("an unavailable kit is refused as a whole and lists every blocked tool", r.status_code == 400 and all(f"P4-K{i}" in r.json()["detail"] for i in (1, 2, 3)))
check("the refused kit created nothing", len(client.get(f"/loans?scope=agency&tool_id={K1}", headers=auth(charge101_token)).json()) == 1)
check("a kit can be edited", client.patch(f"/kits/{kit_id}", json={"tool_ids": [K1, K2]}, headers=auth(charge101_token)).json()["tools"].__len__() == 2)

# ---------- Retour groupé ----------
B1, B2 = mk_tool("P4-B1"), mk_tool("P4-B2")
lb1 = reserve(p4a, B1, d4(hours=-2), d4(hours=3)).json()["id"]
lb2 = reserve(p4a, B2, d4(hours=-2), d4(hours=3)).json()["id"]
r = client.post("/loans/batch-return", json={"returns": [{"loan_id": lb1, "state_after": 5}, {"loan_id": lb2, "state_after": 1, "comment_return": "moteur fatigué"}, {"loan_id": 999999, "state_after": 5}]}, headers=auth(p4a))
check("a batch return reports each item", r.status_code == 200 and r.json()["done"] == 2 and r.json()["failed"] == 1)
check("each returned tool gets its own outcome", tool_status(B1) == "disponible" and tool_status(B2) == "reparation")
check("a colleague cannot return someone else's loans in batch", client.post("/loans/batch-return", json={"returns": [{"loan_id": lb1, "state_after": 5}]}, headers=auth(p4b)).json()["failed"] == 1)

# ---------- Liste d'attente ----------
W1 = mk_tool("P4-W1")
loan_w = reserve(p4a, W1, d4(hours=-1), d4(hours=5)).json()["id"]
r = client.post("/waitlist", json={"tool_id": W1, "start_datetime": d4(hours=1), "end_datetime": d4(hours=3)}, headers=auth(p4b))
entry_b = r.json()["id"]
check("someone can wait for a busy tool", r.status_code == 201 and r.json()["status"] == "waiting")
check("the same person cannot queue twice on the slot", client.post("/waitlist", json={"tool_id": W1, "start_datetime": d4(hours=1), "end_datetime": d4(hours=2)}, headers=auth(p4b)).status_code == 400)
check("a free tool cannot be waited for", client.post("/waitlist", json={"tool_id": mk_tool("P4-W0"), "start_datetime": d4(2), "end_datetime": d4(2, 2)}, headers=auth(p4b)).status_code == 400)
client.post(f"/loans/{loan_w}/return", json={"state_after": 5}, headers=auth(p4a))
entries = {e["id"]: e for e in client.get("/waitlist", headers=auth(p4b)).json()}
check("returning the tool offers the slot to the first in line", entries[entry_b]["status"] == "offered" and entries[entry_b]["offer_expires_at"])
check("the person is notified of the offer", any(n["type"] == "waitlist_available" for n in notes(p4b)))
check("an offered slot cannot be booked by someone else", reserve(gars101a_token, W1, d4(hours=1), d4(hours=3)).status_code == 400)
r = client.post("/waitlist", json={"tool_id": W1, "start_datetime": d4(hours=1), "end_datetime": d4(hours=3)}, headers=auth(gars101a_token))
entry_c = r.json()["id"]
check("a second person queues behind the offer", r.status_code == 201)
check("only the owner of the offer can accept it", client.post(f"/waitlist/{entry_b}/accept", headers=auth(gars101a_token)).status_code == 404)
r = client.post(f"/waitlist/{entry_b}/accept", headers=auth(p4b))
check("accepting the offer creates the reservation", r.status_code == 201 and r.json()["borrower_id"] == p4b_id)
check("an offer can only be used once", client.post(f"/waitlist/{entry_b}/accept", headers=auth(p4b)).status_code == 400)
client.delete(f"/waitlist/{entry_c}", headers=auth(gars101a_token))

W2 = mk_tool("P4-W2")
loan_w2 = reserve(p4a, W2, d4(hours=-1), d4(3)).json()["id"]
e1 = client.post("/waitlist", json={"tool_id": W2, "start_datetime": d4(1), "end_datetime": d4(2)}, headers=auth(p4b)).json()["id"]
e2 = client.post("/waitlist", json={"tool_id": W2, "start_datetime": d4(1), "end_datetime": d4(2)}, headers=auth(gars101a_token)).json()["id"]
client.post(f"/loans/{loan_w2}/return", json={"state_after": 5}, headers=auth(p4a))
with database.SessionLocal() as s:
    reservations_mod.expire_offers(s, datetime.utcnow() + timedelta(hours=25))
    s.commit()
    states = {e.id: e.status for e in s.query(WaitlistEntry).filter(WaitlistEntry.id.in_([e1, e2]))}
check("an unanswered offer expires and passes to the next person", states[e1] == "expired" and states[e2] == "offered")
check("an expired offer cannot be accepted", client.post(f"/waitlist/{e1}/accept", headers=auth(p4b)).status_code == 400)

# ---------- Bon de sortie et signature ----------
T9 = mk_tool("P4-T9", serial_number="SN-9")
loan_doc = reserve(p4a, T9, d4(hours=-1), d4(hours=4), site="Chantier Sud", comment="x" * 300).json()["id"]
pdf_plain = client.get(f"/loans/{loan_doc}/voucher.pdf", headers=auth(p4a))
check("a voucher can be generated as PDF", pdf_plain.status_code == 200 and pdf_plain.content.startswith(b"%PDF"))
check("an empty signature is refused", client.post(f"/loans/{loan_doc}/signature", json={"signature": {"w": 100, "h": 50, "strokes": []}}, headers=auth(p4a)).status_code == 400)
check("a malformed signature is refused", client.post(f"/loans/{loan_doc}/signature", json={"signature": {"w": 100, "h": 50, "strokes": [[["a", 1]]]}}, headers=auth(p4a)).status_code == 400)
check("an oversized signature is refused", client.post(f"/loans/{loan_doc}/signature", json={"signature": {"w": 100, "h": 50, "strokes": [[[1, 1]] * 7000]}}, headers=auth(p4a)).status_code == 400)
r = client.post(f"/loans/{loan_doc}/signature", json={"signature": {"w": 300, "h": 100, "strokes": [[[10, 10], [80, 40], [150, 20]]]}, "signed_name": "P. Quatre"}, headers=auth(p4a))
check("a drawn signature is stored", r.status_code == 200)
pdf_signed = client.get(f"/loans/{loan_doc}/voucher.pdf", headers=auth(p4a))
check("the signature is drawn into the voucher", pdf_signed.content.startswith(b"%PDF") and b"1.20 w" in pdf_signed.content and b"1.20 w" not in pdf_plain.content)
check("the voucher is private to the agency", client.get(f"/loans/{loan_doc}/voucher.pdf", headers=auth(charge202_token)).status_code == 403)
sent = []
original_loans_send = loans_module.send_email
loans_module.send_email = lambda db, to, subject, body, html=None, attachments=None: (sent.append((to, subject, attachments)) or (True, "ok"))
r = client.post(f"/loans/{loan_doc}/voucher/email", json={"to": "chef@example.com"}, headers=auth(p4a))
loans_module.send_email = original_loans_send
check("the voucher can be emailed with the PDF attached", r.status_code == 200 and r.json()["sent"] and sent[0][2][0][0].endswith(".pdf") and sent[0][2][0][1].startswith(b"%PDF"))
check("an invalid email address is refused", client.post(f"/loans/{loan_doc}/voucher/email", json={"to": "pas-un-email"}, headers=auth(p4a)).status_code == 422)

# ---------- Agenda ----------
r = client.get(f"/loans/{loan_doc}/ics", headers=auth(p4a))
body = r.content.decode("utf-8")
check("a reservation exports as an iCalendar event", r.status_code == 200 and "BEGIN:VEVENT" in body and "SUMMARY:Réservation" in body and "\r\n" in body)
check("long lines are folded to 75 bytes", all(len(line.encode("utf-8")) <= 75 for line in body.split("\r\n")))
r = client.post("/calendar/token", headers=auth(p4a))
token_url = r.json()["url"]
feed_token = _re.search(r"/calendar/feed/(.+)\.ics", token_url).group(1)
check("a personal calendar URL can be created", r.status_code == 200 and len(feed_token) >= 30)
feed = client.get(f"/calendar/feed/{feed_token}.ics")
check("the feed is readable without login through its secret URL", feed.status_code == 200 and "text/calendar" in feed.headers["content-type"] and "Réservation" in feed.text)
check("an unknown feed token is refused", client.get("/calendar/feed/abcdef.ics").status_code == 404)
new_url = client.post("/calendar/token", headers=auth(p4a)).json()["url"]
check("regenerating the URL invalidates the old one", client.get(f"/calendar/feed/{feed_token}.ics").status_code == 404 and new_url != token_url)
check("the feed can be revoked", client.delete("/calendar/token", headers=auth(p4a)).status_code == 204 and client.get(new_url.replace("http://127.0.0.1:8000", "")).status_code == 404)

# ---------- Transferts entre agences ----------
AT1, AT2 = mk_tool("P4-AT1"), mk_tool("P4-AT2")
check("personnel cannot propose an inter-agency transfer", client.post("/agency-transfers", json={"tool_id": AT1, "to_agency": "202"}, headers=auth(p4a)).status_code == 403)
check("a transfer to the same agency is refused", client.post("/agency-transfers", json={"tool_id": AT1, "to_agency": "101"}, headers=auth(charge101_token)).status_code == 400)
check("a transfer to an unknown agency is refused", client.post("/agency-transfers", json={"tool_id": AT1, "to_agency": "ZZZ"}, headers=auth(charge101_token)).status_code == 400)
busy = mk_tool("P4-AT-BUSY")
reserve(p4a, busy, d4(hours=-1), d4(hours=2))
check("only an available tool can be transferred", client.post("/agency-transfers", json={"tool_id": busy, "to_agency": "202"}, headers=auth(charge101_token)).status_code == 400)
r = client.post("/agency-transfers", json={"tool_id": AT1, "to_agency": "202", "comment": "Renfort chantier"}, headers=auth(charge101_token))
at_id = r.json()["id"]
check("a manager proposes a transfer", r.status_code == 201 and r.json()["status"] == "pending")
check("a duplicate proposal is refused", client.post("/agency-transfers", json={"tool_id": AT1, "to_agency": "202"}, headers=auth(charge101_token)).status_code == 400)
check("the destination director is notified", any(n["type"] == "agency_transfer" for n in notes(dir202_token)))
check("the origin director cannot accept", client.post(f"/agency-transfers/{at_id}/accept", headers=auth(dir101_token)).status_code == 403)
check("a manager of the destination cannot accept (director only)", client.post(f"/agency-transfers/{at_id}/accept", headers=auth(charge202_token)).status_code == 403)
r = client.post(f"/agency-transfers/{at_id}/accept", headers=auth(dir202_token))
check("the destination director accepts", r.status_code == 200 and r.json()["status"] == "accepted")
check("the tool now belongs to the new agency", client.get(f"/agency-tools/{AT1}", headers=auth(charge202_token)).status_code == 200
      and client.get(f"/agency-tools/{AT1}", headers=auth(charge101_token)).status_code == 403)
check("the move is journaled in the tool history", any(h["source"] == "transfert entre agences" for h in client.get(f"/state-history?kind=agency&tool_id={AT1}", headers=auth(charge202_token)).json()))
r = client.post("/agency-transfers", json={"tool_id": AT2, "to_agency": "202", "temporary": True}, headers=auth(charge101_token))
check("a temporary loan needs a return date", r.status_code == 400)
at2 = client.post("/agency-transfers", json={"tool_id": AT2, "to_agency": "202", "temporary": True, "planned_return_date": d4(10)}, headers=auth(charge101_token)).json()["id"]
client.post(f"/agency-transfers/{at2}/accept", headers=auth(dir202_token))
check("a temporary loan remembers the home agency", client.get(f"/agency-tools/{AT2}", headers=auth(charge202_token)).json()["agency_number"] == "202")
check("a permanent transfer cannot be returned", client.post(f"/agency-transfers/{at_id}/return", headers=auth(charge202_token)).status_code == 400)
r = client.post(f"/agency-transfers/{at2}/return", headers=auth(charge202_token))
check("a temporary loan goes back to its agency", r.status_code == 200 and r.json()["status"] == "returned" and client.get(f"/agency-tools/{AT2}", headers=auth(charge101_token)).json()["agency_number"] == "101")
AT3 = mk_tool("P4-AT3")
at3 = client.post("/agency-transfers", json={"tool_id": AT3, "to_agency": "202"}, headers=auth(charge101_token)).json()["id"]
check("the destination can refuse", client.post(f"/agency-transfers/{at3}/reject", json={"comment": "Pas besoin"}, headers=auth(dir202_token)).json()["status"] == "rejected")
at4 = client.post("/agency-transfers", json={"tool_id": AT3, "to_agency": "202"}, headers=auth(charge101_token)).json()["id"]
check("the requester can cancel a pending proposal", client.post(f"/agency-transfers/{at4}/cancel", headers=auth(charge101_token)).json()["status"] == "cancelled")
check("transfers are listed per agency direction", any(t["id"] == at_id for t in client.get("/agency-transfers?direction=incoming", headers=auth(dir202_token)).json())
      and not any(t["id"] == at_id for t in client.get("/agency-transfers?direction=incoming", headers=auth(dir101_token)).json()))

# ---------- Départ d'un salarié ----------
dep1_id, dep2_id = make_user("dep1", charge101_token), make_user("dep2", charge101_token)
dep1 = login("dep1")
client.post("/personal-tools", json={"name": "Meuleuse dep1", "unique_code": "P4-DEP-TOOL", "state": 5}, headers=auth(dep1))
client.post("/epi", json={"name": "Casque dep1", "type": "Casque", "unique_code": "P4-DEP-EPI", "state": 5, "assigned_to_id": dep1_id}, headers=auth(charge101_token))
TD = mk_tool("P4-DEP-LOAN")
dep_loan = reserve(dep1, TD, d4(hours=-1), d4(hours=3)).json()["id"]
r = client.get(f"/users/{dep1_id}/departure-summary", headers=auth(charge101_token))
check("the departure summary lists everything held", r.status_code == 200 and len(r.json()["owned_tools"]) == 1 and len(r.json()["epi"]) == 1 and len(r.json()["loans"]) == 1)
check("personnel cannot run a departure", client.get(f"/users/{dep1_id}/departure-summary", headers=auth(p4a)).status_code == 403)
check("a manager outside the team cannot", client.get(f"/users/{dep1_id}/departure-summary", headers=auth(charge202_token)).status_code == 403)
check("nobody handles their own departure", client.post(f"/users/{user_id_of('charge101')}/depart", json={"to_user_id": dep2_id}, headers=auth(charge101_token)).status_code == 400)
r = client.post(f"/users/{dep1_id}/depart", json={"to_user_id": dep2_id}, headers=auth(charge101_token))
check("an active loan blocks the departure and says so", r.status_code == 400 and "réservation" in r.json()["detail"])
client.post(f"/loans/{dep_loan}/return", json={"state_after": 5}, headers=auth(dep1))
r = client.post(f"/users/{dep1_id}/depart", json={"to_user_id": dep2_id}, headers=auth(charge101_token))
check("the departure reassigns tools, EPI, dotations and ownership", r.status_code == 200 and r.json()["counts"]["epi"] == 1 and r.json()["counts"]["personal_tools"] >= 1 and r.json()["counts"]["ownership"] >= 1)
check("the leaving account is deactivated and its sessions closed", client.get("/auth/me", headers=auth(dep1)).status_code == 401)
check("the receiver now owns the tool", any(t["unique_code"] == "P4-DEP-TOOL" for t in client.get("/personal-tools", headers=auth(login("dep2"))).json()))
r = client.delete(f"/users/{dep1_id}", headers=admin_headers)
check("an account with a loan history cannot be deleted, to keep the traceability", r.status_code == 400 and "anonymisez" in r.json()["detail"])
r = client.post(f"/gdpr/anonymize/{dep1_id}", headers=admin_headers)
check("the emptied account can be anonymized instead", r.status_code == 200 and r.json()["username"] == f"anonyme-{dep1_id}")

cA_id = make_user("depcharge_a", dir101_token, role="charge_affaires")
cB_id = make_user("depcharge_b", dir101_token, role="charge_affaires")
gsub_id = make_user("depsub", login("depcharge_a"))
r = client.post(f"/users/{cA_id}/depart", json={"to_user_id": cB_id}, headers=auth(dir101_token))
check("subordinates block a manager's departure", r.status_code == 400 and "collaborateur" in r.json()["detail"])
r = client.post(f"/users/{cA_id}/depart", json={"to_user_id": cB_id, "reassign_subordinates_to": gsub_id}, headers=auth(dir101_token))
check("the new manager of subordinates must share the role", r.status_code == 400)
r = client.post(f"/users/{cA_id}/depart", json={"to_user_id": cB_id, "reassign_subordinates_to": cB_id}, headers=auth(dir101_token))
check("subordinates are moved to the new manager", r.status_code == 200 and next(u for u in client.get("/users", headers=admin_headers).json() if u["id"] == gsub_id)["manager_id"] == cB_id)

check("changing agency is admin-only", client.post(f"/users/{dep2_id}/change-agency", json={"agency_number": "202"}, headers=auth(charge101_token)).status_code == 403)
check("an unknown agency is refused", client.post(f"/users/{dep2_id}/change-agency", json={"agency_number": "ZZZ"}, headers=admin_headers).status_code == 400)
r = client.post(f"/users/{dep2_id}/change-agency", json={"agency_number": "202"}, headers=admin_headers)
check("admin moves an employee to another agency with the assigned EPI", r.status_code == 200
      and next(u for u in client.get("/users", headers=admin_headers).json() if u["id"] == dep2_id)["agency_number"] == "202"
      and client.get("/epi", headers=auth(charge202_token)).json().__len__() >= 1)

# ---------- Prêts externes : coordonnées, décharge, lot ----------
X1, X2, X3 = mk_tool("P4-X1"), mk_tool("P4-X2"), mk_tool("P4-X3")
r = client.post("/transfers", json={"agency_tool_id": X1, "to_external_name": "Jean Dupont", "to_external_type": "sous_traitant", "to_external_company": "ACME",
                                    "to_external_email": "jean@acme.fr", "to_external_phone": "0611223344", "planned_return_date": d4(5)}, headers=auth(p4a))
tid = r.json()["id"]
check("external contact details are stored on a loan", r.status_code == 201 and r.json()["to_external_email"] == "jean@acme.fr")
pdf = client.get(f"/transfers/{tid}/discharge.pdf", headers=auth(p4a))
check("a discharge document can be generated", pdf.status_code == 200 and pdf.content.startswith(b"%PDF"))
check("the discharge is private to the lender's scope", client.get(f"/transfers/{tid}/discharge.pdf", headers=auth(charge202_token)).status_code == 403)
check("an invalid discharge signature is refused", client.post(f"/transfers/{tid}/signature", json={"signature": {"w": 10, "h": 10, "strokes": []}}, headers=auth(p4a)).status_code == 400)
check("the recipient's signature is stored", client.post(f"/transfers/{tid}/signature", json={"signature": {"w": 300, "h": 100, "strokes": [[[5, 5], [60, 30]]]}}, headers=auth(p4a)).status_code == 200)
check("the signed discharge contains the drawing", b"1.20 w" in client.get(f"/transfers/{tid}/discharge.pdf", headers=auth(p4a)).content)
import app.routers.transfers_docs as docs_module
docs_sent = []
original_docs_send = docs_module.send_email
docs_module.send_email = lambda db, to, subject, body, html=None, attachments=None: (docs_sent.append((to, attachments)) or (True, "ok"))
r = client.post(f"/transfers/{tid}/discharge/email", json={"to": "jean@acme.fr"}, headers=auth(p4a))
docs_module.send_email = original_docs_send
check("the discharge can be emailed to the recipient", r.status_code == 200 and docs_sent and docs_sent[0][1][0][0].endswith(".pdf"))
r = client.post("/transfers/batch", json={"agency_tool_ids": [X2, X3], "to_external_name": "Sous-traitant Lot"}, headers=auth(p4a))
check("several tools can be lent to the same person at once", r.status_code == 201 and r.json()["count"] == 2 and tool_status(X2) == "emprunte" and tool_status(X3) == "emprunte")
X4 = mk_tool("P4-X4")
r = client.post("/transfers/batch", json={"agency_tool_ids": [X4, X2], "to_external_name": "Autre"}, headers=auth(p4a))
check("a batch loan is all-or-nothing", r.status_code == 400 and "annulé" in r.json()["detail"] and tool_status(X4) == "disponible")
check("an empty batch is refused", client.post("/transfers/batch", json={"to_external_name": "X"}, headers=auth(p4a)).status_code == 400)

# ---------- Tâches ----------
names_jobs = {j["name"] for j in client.get("/admin/jobs", headers=admin_headers).json()}
check("the reservation jobs are registered", {"expire_no_shows", "process_waitlists"} <= names_jobs)
check("the no-show job can be run", client.post("/admin/jobs/expire_no_shows/run", headers=admin_headers).json()["status"] == "ok")
