# Tests de la Phase 1 (alertes et notifications). Exécuté par smoke_test.py.
import base64
import json
import os as _os

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

import app.alerts as alerts_mod
import app.notifications as notifications_mod
import app.webpush as webpush_mod
from app.models_ext import Notification, PushSubscription

_now = datetime.utcnow()


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def run_alerts(at=None):
    with database.SessionLocal() as s:
        result = alerts_mod.run_all(s, at or datetime.utcnow())
        s.commit()
    return result


def notes(token, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get("/notifications?limit=200" + ("&" + query if query else ""), headers=auth(token))
    return r.json()


p1_user_id = make_user("notifgars", charge101_token, email="notif@example.com")
p1_token = login("notifgars")
dir101_id = next(u["id"] for u in client.get("/users", headers=auth(admin_token)).json() if u["username"] == "directeur101")


def new_tool(code, **extra):
    payload = {"name": f"Outil {code}", "unique_code": code, "type": "TypeP1", "purchase_price": 100}
    payload.update(extra)
    r = client.post("/agency-tools", json=payload, headers=auth(charge101_token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ---------- Retards de réservation ----------
t_late1 = new_tool("P1-LATE-1")
r = client.post("/loans", json={"tool_id": t_late1, "start_datetime": iso(_now - timedelta(days=2)),
                                "end_datetime_planned": iso(_now - timedelta(days=1))}, headers=auth(p1_token))
check("overdue loan can be created (start in the past)", r.status_code == 201)
res = run_alerts()
check("alert generation reports overdue loans", res["loan_overdue"] >= 1)
mine = notes(p1_token)
check("borrower receives the overdue notification", any(n["type"] == "loan_overdue" and "P1-LATE-1" in n["title"] + (n["body"] or "") or "Outil P1-LATE-1" in n["title"] for n in mine))
check("no escalation before the delay threshold", not any(n["title"].startswith("Retard de") for n in notes(charge101_token)))
before = len(notes(p1_token))
run_alerts()
check("same-day rerun is deduplicated", len(notes(p1_token)) == before)
check("unread counter matches", client.get("/notifications/count", headers=auth(p1_token)).json()["unread"] == before)

t_late3 = new_tool("P1-LATE-3")
client.post("/loans", json={"tool_id": t_late3, "start_datetime": iso(_now - timedelta(days=6)),
                            "end_datetime_planned": iso(_now - timedelta(days=3))}, headers=auth(p1_token))
run_alerts()
check("manager and director are alerted after the escalation delay",
      any(n["title"].startswith("Retard de") for n in notes(charge101_token)) and any(n["title"].startswith("Retard de") for n in notes(dir101_token)))
check("escalation never reaches other agencies", not any(n["title"].startswith("Retard de") for n in notes(charge202_token)))
run_alerts(datetime.utcnow() + timedelta(days=1))
check("next day sends a new reminder for the same loan", len(notes(p1_token)) > before)

# ---------- Fin de réservation proche ----------
t_soon = new_tool("P1-SOON-1")
client.post("/loans", json={"tool_id": t_soon, "start_datetime": iso(_now - timedelta(hours=1)),
                            "end_datetime_planned": iso(_now + timedelta(hours=10))}, headers=auth(p1_token))
res = run_alerts()
check("ending-soon reminder is generated", res["loan_ending_soon"] >= 1 and any(n["type"] == "loan_ending_soon" for n in notes(p1_token)))

# ---------- EPI ----------
r = client.post("/epi", json={"name": "Casque P1", "type": "Casque", "unique_code": "P1-EPI-EXP", "state": 5,
                              "expiration_date": iso(_now + timedelta(days=20)), "assigned_to_id": p1_user_id}, headers=auth(charge101_token))
r = client.post("/epi", json={"name": "Harnais P1", "type": "Harnais", "unique_code": "P1-EPI-OLD", "state": 5,
                              "expiration_date": iso(_now - timedelta(days=5)), "assigned_to_id": p1_user_id}, headers=auth(charge101_token))
res = run_alerts()
check("EPI expiring and expired alerts are generated", res["epi_expiring"] >= 3)
mine = notes(p1_token)
check("wearer is told about the expiring EPI", any(n["type"] == "epi_expiring" for n in mine))
check("expired EPI alert is critical", any(n["type"] == "epi_expired" and n["severity"] == "critical" for n in mine))
check("manager of the wearer is alerted too", any(n["type"] == "epi_expired" for n in notes(charge101_token)))
count_before = len(notes(p1_token))
run_alerts()
check("EPI alerts are not repeated", len(notes(p1_token)) == count_before)

# ---------- Garantie ----------
new_tool("P1-WARR-1", warranty_expiration_date=iso(_now + timedelta(days=20)))
res = run_alerts()
check("warranty expiry alert reaches agency managers", res["warranty_expiring"] >= 1 and any(n["type"] == "warranty_expiring" for n in notes(charge101_token)))
check("warranty alert stays inside the agency", not any(n["type"] == "warranty_expiring" and "P1-WARR-1" in n["title"] for n in notes(charge202_token)))

# ---------- Transfert entre collègues en attente ----------
p1b_id = make_user("notifgars2", charge101_token)
client.post("/personal-tools", json={"name": "Perceuse P1", "unique_code": "P1-PERSO-1", "state": 5}, headers=auth(p1_token))
r = client.post("/peer-transfers", json={"direction": "je_donne", "tool_code": "P1-PERSO-1", "counterpart_id": p1b_id}, headers=auth(p1_token))
check("peer transfer declared for the reminder test", r.status_code == 201)
p1b_token = login("notifgars2")
run_alerts(datetime.utcnow() + timedelta(days=3))
check("the other party is reminded of a pending transfer", any(n["type"] == "peer_pending" for n in notes(p1b_token)))
check("the declarant is not reminded", not any(n["type"] == "peer_pending" for n in notes(p1_token)))

# ---------- Lecture ----------
first = notes(p1_token, unread_only="true")[0]
r = client.post(f"/notifications/{first['id']}/read", headers=auth(p1_token))
check("a notification can be marked read", r.status_code == 200)
check("another user cannot read it", client.post(f"/notifications/{first['id']}/read", headers=auth(p1b_token)).status_code == 404)
check("unread filter excludes read items", first["id"] not in [n["id"] for n in notes(p1_token, unread_only="true")])
r = client.post("/notifications/read-all", headers=auth(p1_token))
check("read-all clears the counter", client.get("/notifications/count", headers=auth(p1_token)).json()["unread"] == 0 and r.status_code == 200)
r = client.get("/notifications?limit=2", headers=auth(p1_token))
check("notifications are paginated with a total", len(r.json()) == 2 and int(r.headers["x-total-count"]) > 2)

# ---------- Préférences ----------
r = client.get("/notifications/preferences", headers=auth(p1_token))
prefs = {p["type"]: p for p in r.json()}
check("preferences list every type with sensible defaults", "loan_overdue" in prefs and prefs["loan_overdue"]["in_app"] is True and prefs["loan_overdue"]["email"] is False)
check("managers get email by default for warnings", {p["type"]: p for p in client.get("/notifications/preferences", headers=auth(charge101_token)).json()}["loan_overdue"]["email"] is True)
r = client.put("/notifications/preferences", json=[{"type": "loan_ending_soon", "in_app": False, "email": True, "push": False}], headers=auth(p1_token))
check("preferences can be updated", r.status_code == 200 and {p["type"]: p for p in r.json()}["loan_ending_soon"]["in_app"] is False)
check("unknown notification type is rejected", client.put("/notifications/preferences", json=[{"type": "nimportequoi", "in_app": True, "email": True, "push": True}], headers=auth(p1_token)).status_code == 400)
t_soon2 = new_tool("P1-SOON-2")
client.post("/loans", json={"tool_id": t_soon2, "start_datetime": iso(_now - timedelta(hours=1)),
                            "end_datetime_planned": iso(_now + timedelta(hours=5))}, headers=auth(p1_token))
before_ids = {n["id"] for n in notes(p1_token)}
run_alerts()
check("in-app disabled type stays out of the notification centre", not any(n["type"] == "loan_ending_soon" and n["id"] not in before_ids for n in notes(p1_token)))

# ---------- Digest email ----------
sent_emails = []


def fake_send(db, to, subject, body, html=None, attachments=None):
    sent_emails.append((to, subject, body, html))
    return True, "ok"


original_send = notifications_mod.send_email
notifications_mod.send_email = fake_send
with database.SessionLocal() as s:
    off_hour = alerts_mod.send_digests(s, datetime.utcnow().replace(hour=3), force=False)
check("digest is not sent outside the configured hour", off_hour["emails"] == 0 and not sent_emails)
with database.SessionLocal() as s:
    result = alerts_mod.send_digests(s, force=True)
check("digest sends one grouped email per person", result["emails"] >= 1 and len({e[0] for e in sent_emails}) == len(sent_emails))
check("digest email has a text and an HTML body", all(e[3] and "<table" in e[3] and e[2] for e in sent_emails))
sent_emails.clear()
with database.SessionLocal() as s:
    again = alerts_mod.send_digests(s, force=True)
check("digest marks alerts as sent (no duplicate)", again["emails"] == 0 and not sent_emails)
notifications_mod.send_email = original_send

# ---------- Web Push ----------
ua_private = ec.generate_private_key(ec.SECP256R1())
ua_public = ua_private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
ua_auth = _os.urandom(16)
sub_payload = {"endpoint": "https://push.example.com/send/abc123",
               "keys": {"p256dh": webpush_mod.b64u(ua_public), "auth": webpush_mod.b64u(ua_auth)}}
r = client.get("/push/public-key", headers=auth(p1b_token))
vapid_public = r.json()["public_key"]
check("VAPID public key is a 65-byte uncompressed point", len(webpush_mod.b64u_decode(vapid_public)) == 65 and webpush_mod.b64u_decode(vapid_public)[0] == 4)
check("VAPID key is stable across calls", client.get("/push/public-key", headers=auth(p1b_token)).json()["public_key"] == vapid_public)
check("non-HTTPS push endpoint is rejected", client.post("/push/subscribe", json={**sub_payload, "endpoint": "http://insecure.example.com/x"}, headers=auth(p1b_token)).status_code == 400)
check("push subscription is stored", client.post("/push/subscribe", json=sub_payload, headers=auth(p1b_token)).status_code == 201)

push_calls = []
push_code = {"value": 201}


def fake_transport(endpoint, headers, body):
    push_calls.append((endpoint, headers, body))
    return push_code["value"]


webpush_mod.transport = fake_transport
with database.SessionLocal() as s:
    import app.notify as notify_mod
    n = notify_mod.create(s, next(u["id"] for u in client.get("/users", headers=auth(admin_token)).json() if u["username"] == "notifgars2"),
                          "generic", "Test push", "Contenu du message", link="#/notifications")
    s.commit()
check("a notification triggers a push to the subscribed device", len(push_calls) == 1 and push_calls[0][0] == sub_payload["endpoint"])
endpoint, headers, body = push_calls[0]
plaintext = json.loads(webpush_mod.decrypt_payload(body, ua_private, sub_payload["keys"]["auth"]))
check("push payload decrypts on the device side (RFC 8291 round trip)", plaintext["title"] == "Test push" and plaintext["url"] == "#/notifications")
check("push carries the aes128gcm encoding and a VAPID header", headers["Content-Encoding"] == "aes128gcm" and headers["Authorization"].startswith("vapid t="))
token = headers["Authorization"].split("t=")[1].split(",")[0]
h_b64, c_b64, s_b64 = token.split(".")
claims = json.loads(webpush_mod.b64u_decode(c_b64))
signature = webpush_mod.b64u_decode(s_b64)
vapid_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush_mod.b64u_decode(vapid_public))
try:
    vapid_key.verify(encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")),
                     f"{h_b64}.{c_b64}".encode(), ec.ECDSA(hashes.SHA256()))
    signature_ok = True
except Exception:
    signature_ok = False
check("VAPID JWT is signed with the server key and targets the push service", signature_ok and claims["aud"] == "https://push.example.com")
push_code["value"] = 410
with database.SessionLocal() as s:
    notify_mod.create(s, next(u["id"] for u in client.get("/users", headers=auth(admin_token)).json() if u["username"] == "notifgars2"),
                      "generic", "Second push", "x")
    s.commit()
with database.SessionLocal() as s:
    check("expired push subscription (410) is removed automatically", s.query(PushSubscription).count() == 0)
webpush_mod.transport = webpush_mod._http_transport

# ---------- Réglages d'alertes ----------
check("alert settings are admin-only", client.get("/settings/app", headers=auth(charge101_token)).status_code == 403)
r = client.get("/settings/app", headers=auth(admin_token))
check("alert settings expose defaults and descriptions", any(s["key"] == "alert.epi_expiry_days" and s["default"] == "60,30,7" for s in r.json()))
r = client.patch("/settings/app", json={"values": {"alert.overdue_escalation_days": 5}}, headers=auth(admin_token))
check("alert settings can be changed", any(s["key"] == "alert.overdue_escalation_days" and s["value"] == "5" for s in r.json()))
check("unknown alert setting is rejected", client.patch("/settings/app", json={"values": {"nope": 1}}, headers=auth(admin_token)).status_code == 400)
client.patch("/settings/app", json={"values": {"alert.overdue_escalation_days": 2}}, headers=auth(admin_token))

# ---------- Tableau de bord : retards ----------
r = client.get("/dashboard/overdue", headers=auth(charge101_token))
check("manager dashboard lists the team's overdue loans", r.status_code == 200 and len(r.json()["loans"]) >= 2 and all("days_late" in l for l in r.json()["loans"]))
r = client.get("/dashboard/overdue", headers=auth(p1b_token))
check("personnel only sees their own overdue items", all(l["borrower_id"] != p1_user_id for l in r.json()["loans"]))
check("overdue dashboard never crosses agencies", client.get("/dashboard/overdue", headers=auth(charge202_token)).json()["loans"] == [])

# ---------- Alerte immédiate d'un outil hors service ----------
t_break = new_tool("P1-BREAK-1")
client.patch(f"/agency-tools/{t_break}", json={"status": "reparation"}, headers=auth(charge101_token))
check("a broken tool alerts the other managers immediately", any(n["type"] == "tool_problem" and "P1-BREAK-1" in n["title"] for n in notes(dir101_token)))
check("the author of the change is not notified", not any(n["type"] == "tool_problem" and "P1-BREAK-1" in n["title"] for n in notes(charge101_token)))

# ---------- Résumé hebdomadaire ----------
monday = datetime.utcnow() + timedelta(days=(7 - datetime.utcnow().weekday()) % 7 or 7)
with database.SessionLocal() as s:
    alerts_mod.weekly_summary(s, monday)
    s.commit()
check("weekly summary reaches the managers of the agency", any(n["type"] == "weekly_summary" for n in notes(dir101_token)))
with database.SessionLocal() as s:
    check("weekly summary is only generated on Mondays", alerts_mod.weekly_summary(s, monday + timedelta(days=1)) == 0)

# ---------- Tâches ----------
r = client.post("/admin/jobs/generate_alerts/run", headers=auth(admin_token))
check("alert generation is available as a scheduled job", r.status_code == 200 and r.json()["status"] == "ok")

# ---------- Relance d'un retard ----------
late_loan_id = next(l["id"] for l in client.get("/loans?scope=team", headers=auth(charge101_token)).json()
                    if l["borrower_id"] == p1_user_id and l["tool_id"] == t_late3)
check("manager can remind a late colleague", client.post(f"/loans/{late_loan_id}/remind", headers=auth(charge101_token)).status_code == 200)
check("a second reminder the same day is refused", client.post(f"/loans/{late_loan_id}/remind", headers=auth(charge101_token)).status_code == 400)
check("the colleague receives the reminder", any(n["title"].startswith("Rappel de") for n in notes(p1_token)))
check("personnel cannot remind", client.post(f"/loans/{late_loan_id}/remind", headers=auth(p1b_token)).status_code == 403)
check("manager outside the team cannot remind", client.post(f"/loans/{late_loan_id}/remind", headers=auth(charge202_token)).status_code == 403)
check("nobody reminds themselves", client.post(f"/loans/{late_loan_id}/remind", headers=auth(p1_token)).status_code == 403)
