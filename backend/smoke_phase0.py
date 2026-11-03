# Tests de la Phase 0. Exécuté par smoke_test.py (partage client, check, auth, tokens).
import sqlite3
from datetime import datetime, timedelta

from sqlalchemy import text

import app.config as cfg
import app.migrations as migrations_mod
import app.utils as utils_mod
from app.auth import hash_password, hash_token
from app.models import AuditLog, JobRun, LoginAttempt, PasswordResetToken, PersonalTool


def advance_clock(seconds):
    base = datetime.utcnow()
    utils_mod.set_clock(lambda: base + timedelta(seconds=seconds))


def reset_clock():
    utils_mod.set_clock(None)


def raw_login(username, password):
    return client.post("/auth/login", json={"username": username, "password": password})


def make_user(username, creator_token, role="gars_chantier", **extra):
    payload = {"username": username, "full_name": username.title(), "role": role, "password": "password123"}
    payload.update(extra)
    r = client.post("/users", json=payload, headers=auth(creator_token))
    assert r.status_code == 201, (username, r.text)
    return r.json()["id"]


# ---------- Migrations sur une base à l'ancien schéma ----------
old_db = TMP_DIR / "old_schema.db"
con = sqlite3.connect(old_db)
con.execute(
    "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR NOT NULL, hashed_password VARCHAR NOT NULL, "
    "full_name VARCHAR NOT NULL, role VARCHAR NOT NULL, manager_id INTEGER, agency_number VARCHAR, "
    "is_active BOOLEAN NOT NULL, created_at DATETIME)"
)
con.execute(
    "INSERT INTO users (username, hashed_password, full_name, role, agency_number, is_active) VALUES (?,?,?,?,?,1)",
    ("admin", hash_password("admin123"), "Administrateur", "admin", None),
)
con.execute(
    "INSERT INTO users (username, hashed_password, full_name, role, agency_number, is_active) VALUES (?,?,?,?,?,1)",
    ("ancien", hash_password("motdepasse1"), "Ancien", "directeur_agence", "ZONE-A"),
)
con.commit()
con.close()

old_engine = create_engine(f"sqlite:///{old_db}", connect_args={"check_same_thread": False})
database.Base.metadata.create_all(bind=old_engine)
backup_dir = TMP_DIR / "mig_backups"
applied = migrations_mod.run_migrations(old_engine, backup_dir)
with old_engine.begin() as conn:
    cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
    users_after = conn.execute(text("SELECT username, must_change_password FROM users ORDER BY id")).fetchall()
    agencies_after = {row[0] for row in conn.execute(text("SELECT name FROM agencies"))}
check("migration adds new user columns", {"email", "phone", "must_change_password", "token_version"} <= cols)
check("migration keeps existing users", [u[0] for u in users_after] == ["admin", "ancien"])
check("migration flags admin still on default password", users_after[0][1] == 1 and users_after[1][1] == 0)
check("migration seeds agencies from existing values", agencies_after == {"ZONE-A"})
check("migration creates a backup before changing data", len(list(backup_dir.glob("*.db"))) == 1)
check("all migrations recorded", applied == [m[0] for m in migrations_mod.MIGRATIONS])
check(
    "second migration run is a no-op",
    migrations_mod.run_migrations(old_engine, backup_dir) == [] and len(list(backup_dir.glob("*.db"))) == 1,
)
old_engine.dispose()

# ---------- Démarrage sécurisé ----------
try:
    cfg.validate_startup(True, cfg.DEFAULT_SECRET_KEY)
    refused = False
except RuntimeError:
    refused = True
check("prod refuses default secret key", refused)
cfg.validate_startup(False, cfg.DEFAULT_SECRET_KEY)
cfg.validate_startup(True, "une-cle-longue-et-aleatoire-123456789")
check("dev or custom key starts fine", True)

r = client.get("/health")
check(
    "security headers present",
    r.headers.get("x-content-type-options") == "nosniff"
    and "default-src 'self'" in r.headers.get("content-security-policy", ""),
)

# ---------- Agences ----------
r = client.post("/agencies", json={"name": "999X"}, headers=auth(charge101_token))
check("non-admin cannot create agency", r.status_code == 403)
r = client.post("/agencies", json={"name": "101"}, headers=auth(admin_token))
check("duplicate agency rejected", r.status_code == 400)
r = client.post("/users", json={
    "username": "dir_bad_agency", "full_name": "X", "role": "directeur_agence",
    "password": "password123", "agency_number": "UNKNOWN",
}, headers=auth(admin_token))
check("unknown agency rejected on user creation", r.status_code == 400)
tmp1_id = client.post("/agencies", json={"name": "TMP1"}, headers=auth(admin_token)).json()["id"]
r = client.post("/users", json={
    "username": "dir_tmp1", "full_name": "Dir TMP", "role": "directeur_agence",
    "password": "password123", "agency_number": "TMP1",
}, headers=auth(admin_token))
check("user created in new agency", r.status_code == 201)
r = client.patch(f"/agencies/{tmp1_id}", json={"name": "TMP2"}, headers=auth(admin_token))
tmp_users = client.get("/users", headers=auth(admin_token)).json()
check(
    "agency rename cascades to users",
    r.status_code == 200 and any(u["username"] == "dir_tmp1" and u["agency_number"] == "TMP2" for u in tmp_users),
)
check("used agency cannot be deleted", client.delete(f"/agencies/{tmp1_id}", headers=auth(admin_token)).status_code == 400)
client.patch(f"/agencies/{tmp1_id}", json={"is_active": False}, headers=auth(admin_token))
r = client.post("/users", json={
    "username": "dir_tmp_inactive", "full_name": "X", "role": "directeur_agence",
    "password": "password123", "agency_number": "TMP2",
}, headers=auth(admin_token))
check("inactive agency rejected for new users", r.status_code == 400)
visible = [a["name"] for a in client.get("/agencies", headers=auth(charge101_token)).json()]
check("non-admin agency list hides inactive", "TMP2" not in visible and "101" in visible)
tmp3_id = client.post("/agencies", json={"name": "TMP3"}, headers=auth(admin_token)).json()["id"]
check("unused agency can be deleted", client.delete(f"/agencies/{tmp3_id}", headers=auth(admin_token)).status_code == 204)

# ---------- Mots de passe et sessions ----------
r = client.post("/users", json={
    "username": "weakpw", "full_name": "Weak", "role": "directeur_agence",
    "password": "abc", "agency_number": "101",
}, headers=auth(admin_token))
check("weak password rejected on user creation", r.status_code == 400)

make_user("pwuser", charge101_token)
r = raw_login("pwuser", "password123")
old_access, old_refresh = r.json()["access_token"], r.json()["refresh_token"]
check("login returns a refresh token", bool(old_refresh))

r = client.post("/auth/change-password", json={"current_password": "mauvais", "new_password": "nouveau123"}, headers=auth(old_access))
check("change-password rejects wrong current password", r.status_code == 400)
r = client.post("/auth/change-password", json={"current_password": "password123", "new_password": "court"}, headers=auth(old_access))
check("change-password rejects weak password", r.status_code == 400)
r = client.post("/auth/change-password", json={"current_password": "password123", "new_password": "password123"}, headers=auth(old_access))
check("change-password rejects same password", r.status_code == 400)
r = client.post("/auth/change-password", json={"current_password": "password123", "new_password": "nouveau123"}, headers=auth(old_access))
check("change-password succeeds and returns new tokens", r.status_code == 200 and bool(r.json().get("refresh_token")))
new_access = r.json()["access_token"]
check("old access token revoked after password change", client.get("/auth/me", headers=auth(old_access)).status_code == 401)
check("new access token works", client.get("/auth/me", headers=auth(new_access)).status_code == 200)
check("old refresh token revoked after password change", client.post("/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401)
check("old password no longer works", raw_login("pwuser", "password123").status_code == 401)
check("new password works", raw_login("pwuser", "nouveau123").status_code == 200)

# ---------- Refresh tokens ----------
rt1 = raw_login("pwuser", "nouveau123").json()["refresh_token"]
r = client.post("/auth/refresh", json={"refresh_token": rt1})
check("refresh returns new tokens", r.status_code == 200 and r.json()["refresh_token"] != rt1)
rt2, access2 = r.json()["refresh_token"], r.json()["access_token"]
check("rotated token rejected on immediate reuse", client.post("/auth/refresh", json={"refresh_token": rt1}).status_code == 401)
check("immediate reuse (multi-tab race) keeps the session", client.get("/auth/me", headers=auth(access2)).status_code == 200)
advance_clock(30)
check("late reuse of a rotated token is rejected", client.post("/auth/refresh", json={"refresh_token": rt1}).status_code == 401)
reset_clock()
check("late reuse revokes the whole session", client.get("/auth/me", headers=auth(access2)).status_code == 401)
check("refresh token of revoked session rejected", client.post("/auth/refresh", json={"refresh_token": rt2}).status_code == 401)

rt3 = raw_login("pwuser", "nouveau123").json()["refresh_token"]
r_out = client.post("/auth/logout", json={"refresh_token": rt3})
check("logout revokes the refresh token", r_out.status_code == 204 and client.post("/auth/refresh", json={"refresh_token": rt3}).status_code == 401)

# ---------- Limitation de débit ----------
for _ in range(5):
    r = raw_login("pwuser", "faux-mot-de-passe")
check("five failed logins return 401", r.status_code == 401)
r = raw_login("pwuser", "nouveau123")
check("sixth attempt blocked even with the right password", r.status_code == 429 and int(r.headers.get("retry-after", "0")) > 0)
advance_clock(65)
check("block lifts after the delay (attempt processed)", raw_login("pwuser", "faux-mot-de-passe").status_code == 401)
r = raw_login("pwuser", "nouveau123")
check("block duration grows after repeated failures", r.status_code == 429 and int(r.headers["retry-after"]) > 60)
reset_clock()
advance_clock(65 + 200)
check("successful login after the block resets the counter", raw_login("pwuser", "nouveau123").status_code == 200)
reset_clock()
for _ in range(5):
    raw_login("utilisateur-inconnu", "x")
check("unknown usernames are throttled too", raw_login("utilisateur-inconnu", "x").status_code == 429)

# ---------- Réinitialisation par un responsable et changement forcé ----------
rst_id = make_user("rstuser", charge101_token)
charge101_id = next(u["id"] for u in client.get("/users", headers=auth(admin_token)).json() if u["username"] == "charge101")
r = client.post(f"/users/{rst_id}/reset-password", headers=auth(gars101a_token))
check("personnel cannot reset a password", r.status_code == 403)
r = client.post(f"/users/{rst_id}/reset-password", headers=auth(charge202_token))
check("manager outside the cascade cannot reset", r.status_code == 403)
r = client.post(f"/users/{rst_id}/reset-password", headers=auth(charge101_token))
temp_password = r.json().get("temporary_password", "")
check("manager in the cascade gets a temporary password", r.status_code == 200 and len(temp_password) >= 12)
r = raw_login("rstuser", temp_password)
check("temporary password logs in and flags the change", r.status_code == 200 and r.json()["user"]["must_change_password"] is True)
rst_token = r.json()["access_token"]
check("dev mode does not block the API", client.get("/epi", headers=auth(rst_token)).status_code == 200)
cfg.IS_PROD = True
r = client.get("/epi", headers=auth(rst_token))
check("prod blocks the API until the password is changed", r.status_code == 403 and r.headers.get("x-auth-error") == "password_change_required")
check("prod still allows /auth/me while blocked", client.get("/auth/me", headers=auth(rst_token)).status_code == 200)
r = client.post("/auth/change-password", json={"current_password": temp_password, "new_password": "definitif123"}, headers=auth(rst_token))
check("forced change-password works in prod", r.status_code == 200 and r.json()["user"]["must_change_password"] is False)
check("API unlocked after the change", client.get("/epi", headers=auth(r.json()["access_token"])).status_code == 200)
cfg.IS_PROD = False
check("manager cannot reset own password via this route", client.post(f"/users/{charge101_id}/reset-password", headers=auth(charge101_token)).status_code == 400)

# ---------- Mot de passe oublié ----------
mail_id = make_user("mailuser", charge101_token, email="mail@example.com")
r1 = client.post("/auth/forgot-password", json={"identifier": "mailuser"})
r2 = client.post("/auth/forgot-password", json={"identifier": "inconnu-total"})
check("forgot-password answers identically for unknown accounts", r1.status_code == 200 and r1.json() == r2.json())
with database.SessionLocal() as s:
    tokens_known = s.query(PasswordResetToken).filter(PasswordResetToken.user_id == mail_id).count()
check("forgot-password creates a token even when SMTP fails", tokens_known == 1)
for _ in range(5):
    client.post("/auth/forgot-password", json={"identifier": "mail@example.com"})
with database.SessionLocal() as s:
    check("forgot-password is throttled per account", s.query(PasswordResetToken).filter(PasswordResetToken.user_id == mail_id).count() <= 3)
    s.add(PasswordResetToken(user_id=mail_id, token_hash=hash_token("known-token-abc"), created_at=datetime.utcnow(), expires_at=datetime.utcnow() + timedelta(minutes=30)))
    s.add(PasswordResetToken(user_id=mail_id, token_hash=hash_token("expired-token"), created_at=datetime.utcnow(), expires_at=datetime.utcnow() - timedelta(minutes=1)))
    s.commit()
check("reset rejects a weak password", client.post("/auth/reset-password", json={"token": "known-token-abc", "new_password": "abc"}).status_code == 400)
check("reset rejects an expired token", client.post("/auth/reset-password", json={"token": "expired-token", "new_password": "reset12345"}).status_code == 400)
check("reset rejects an unknown token", client.post("/auth/reset-password", json={"token": "nope", "new_password": "reset12345"}).status_code == 400)
check("reset with a valid token succeeds", client.post("/auth/reset-password", json={"token": "known-token-abc", "new_password": "reset12345"}).status_code == 200)
check("reset token is single-use", client.post("/auth/reset-password", json={"token": "known-token-abc", "new_password": "reset67890"}).status_code == 400)
check("old password rejected after reset", raw_login("mailuser", "password123").status_code == 401)
check("new password accepted after reset", raw_login("mailuser", "reset12345").status_code == 200)

# ---------- Profil ----------
r = client.patch("/auth/me", json={"email": "pas-un-email"}, headers=auth(gars101a_token))
check("profile rejects an invalid email", r.status_code == 422)
r = client.patch("/auth/me", json={"email": "gars@example.com", "phone": "0600000000", "current_password": "password123"}, headers=auth(gars101a_token))
check("profile update works", r.status_code == 200 and r.json()["email"] == "gars@example.com")

# ---------- Suppression / réaffectation / désactivation ----------
h1 = make_user("holder1", charge101_token)
h2 = make_user("holder2", charge101_token)
h1_token = login("holder1")
r = client.post("/personal-tools", json={"name": "Perceuse H1", "unique_code": "HOLD-1", "state": 5}, headers=auth(h1_token))
hold_tool_id = r.json()["id"]
r = client.delete(f"/users/{h1}", headers=auth(admin_token))
check("deleting a user who owns tools is refused with details", r.status_code == 400 and "outil" in r.json()["detail"])
check("personnel cannot reassign tools", client.post(f"/users/{h1}/reassign-tools", json={"to_user_id": h2}, headers=auth(gars101a_token)).status_code == 403)
check("manager outside the cascade cannot reassign", client.post(f"/users/{h1}/reassign-tools", json={"to_user_id": h2}, headers=auth(charge202_token)).status_code == 403)
check("reassign to self is refused", client.post(f"/users/{h1}/reassign-tools", json={"to_user_id": h1}, headers=auth(charge101_token)).status_code == 400)
r = client.post(f"/users/{h1}/reassign-tools", json={"to_user_id": h2}, headers=auth(charge101_token))
check("manager in the cascade reassigns tools", r.status_code == 200 and r.json()["personal_tools"] >= 1)
with database.SessionLocal() as s:
    holder = s.query(PersonalTool).filter(PersonalTool.id == hold_tool_id).first().current_holder_id
check("holder updated after reassignment", holder == h2)
tmpdel_id = make_user("tmpdel", admin_token)
check("a user without holdings can be deleted", client.delete(f"/users/{tmpdel_id}", headers=auth(admin_token)).status_code == 204)
h2_token = login("holder2")
client.patch(f"/users/{h2}", json={"is_active": False}, headers=auth(admin_token))
check("deactivation revokes existing sessions", client.get("/auth/me", headers=auth(h2_token)).status_code == 401)
check("deactivated user cannot log in", raw_login("holder2", "password123").status_code == 401)

# ---------- Journal d'audit ----------
r = client.get("/audit-log", headers=auth(charge101_token))
check("audit log is admin-only", r.status_code == 403)
r = client.get("/audit-log?limit=500", headers=auth(admin_token))
actions = {e["action"] for e in r.json()}
check("audit log lists sensitive actions", {"login_failed", "login_success", "user_created", "password_changed", "password_reset_by_manager", "agency_created"} <= actions)
check("audit log exposes a total count", int(r.headers["x-total-count"]) >= len(r.json()) > 0)
r = client.get("/audit-log?action=login_failed", headers=auth(admin_token))
check("audit log filters by action", r.json() and all(e["action"] == "login_failed" for e in r.json()))
with database.SessionLocal() as s:
    blob = " ".join((row.details or "") for row in s.query(AuditLog).all())
check(
    "audit log never stores secrets",
    all(secret not in blob for secret in ("password123", "nouveau123", "reset12345", "definitif123", temp_password, "known-token-abc")),
)
r = client.get("/audit-log/export", headers=auth(admin_token))
check("audit export is a BOM-prefixed semicolon CSV", r.status_code == 200 and r.text.startswith("﻿Date;") and "attachment" in r.headers["content-disposition"])

# ---------- Tâches planifiées ----------
r = client.get("/admin/jobs", headers=auth(charge101_token))
check("job list is admin-only", r.status_code == 403)
r = client.get("/admin/jobs", headers=auth(admin_token))
check("job list returns the registered jobs", {"purge_login_attempts", "purge_expired_tokens"} <= {j["name"] for j in r.json()})
with database.SessionLocal() as s:
    s.add(LoginAttempt(identifier="ancien-test", ip="9.9.9.9", success=False, created_at=datetime.utcnow() - timedelta(days=40)))
    s.commit()
r = client.post("/admin/jobs/purge_login_attempts/run", headers=auth(admin_token))
check("manual job run purges old data", r.status_code == 200 and r.json()["status"] == "ok" and r.json()["message"].startswith("1 "))
with database.SessionLocal() as s:
    check("old login attempts were deleted", s.query(LoginAttempt).filter(LoginAttempt.identifier == "ancien-test").count() == 0)
r = client.post("/admin/jobs/purge_login_attempts/run", headers=auth(admin_token))
check("job is idempotent (second run ok, nothing to purge)", r.json()["status"] == "ok" and r.json()["message"].startswith("0 "))
with database.SessionLocal() as s:
    s.add(JobRun(name="purge_expired_tokens", trigger="test", started_at=datetime.utcnow(), status="running"))
    s.commit()
r = client.post("/admin/jobs/purge_expired_tokens/run", headers=auth(admin_token))
check("a job already running is skipped", r.json()["status"] == "skipped")
with database.SessionLocal() as s:
    s.query(JobRun).filter(JobRun.name == "purge_expired_tokens", JobRun.status == "running").update(
        {"started_at": datetime.utcnow() - timedelta(minutes=30)}
    )
    s.commit()
r = client.post("/admin/jobs/purge_expired_tokens/run", headers=auth(admin_token))
check("a stale running job is closed and rerun", r.json()["status"] == "ok")
check("unknown job returns 404", client.post("/admin/jobs/inconnue/run", headers=auth(admin_token)).status_code == 404)
check("cron endpoint refuses a missing key", client.post("/cron/purge_login_attempts").status_code == 403)
check("cron endpoint refuses a wrong key", client.post("/cron/purge_login_attempts", headers={"X-Cron-Token": "mauvais"}).status_code == 403)
r = client.post("/cron/purge_login_attempts", headers={"X-Cron-Token": "cron-test-token"})
check("cron endpoint runs the job with the right key", r.status_code == 200 and r.json()["status"] == "ok")
with database.SessionLocal() as s:
    check("job runs are journaled", s.query(JobRun).filter(JobRun.name == "purge_login_attempts").count() >= 3)

# ---------- Filtres serveur et pagination ----------
for i in range(3):
    client.post("/agency-tools", json={"name": f"Scie pagination {i}", "type": "TypeA", "unique_code": f"PAG-A-{i}", "purchase_price": 10}, headers=auth(charge101_token))
client.post("/agency-tools", json={"name": "Niveau laser", "type": "TypeB", "unique_code": "PAG-B-0", "purchase_price": 10}, headers=auth(charge202_token))

r_all = client.get("/agency-tools", headers=auth(charge101_token))
check("list without params is unchanged and exposes the total", int(r_all.headers["x-total-count"]) == len(r_all.json()) >= 4)
r = client.get("/agency-tools?limit=2&offset=0", headers=auth(charge101_token))
r2 = client.get("/agency-tools?limit=2&offset=2", headers=auth(charge101_token))
ids_p1 = [t["id"] for t in r.json()]
ids_p2 = [t["id"] for t in r2.json()]
check("limit returns a page and the full total", len(ids_p1) == 2 and int(r.headers["x-total-count"]) == len(r_all.json()))
check("offset returns the next distinct page", ids_p2 and not set(ids_p1) & set(ids_p2))
r = client.get("/agency-tools?q=pag-a-1", headers=auth(charge101_token))
check("search is case-insensitive on the code", [t["unique_code"] for t in r.json()] == ["PAG-A-1"])
r = client.get("/agency-tools?type=TypeA", headers=auth(charge101_token))
check("type filter works", len(r.json()) == 3 and int(r.headers["x-total-count"]) == 3)
r = client.get("/agency-tools?status=disponible&type=TypeA&limit=2", headers=auth(charge101_token))
check("filters combine with pagination (total ignores limit)", len(r.json()) == 2 and int(r.headers["x-total-count"]) == 3)
check("invalid status value is rejected", client.get("/agency-tools?status=nimportequoi", headers=auth(charge101_token)).status_code == 422)
r = client.get("/agency-tools?q=PAG-A", headers=auth(charge202_token))
check("search never crosses agencies", r.json() == [])
check("wildcard characters in search are literal", client.get("/agency-tools?q=%25", headers=auth(charge101_token)).json() == [])
types_101 = client.get("/agency-tools/types", headers=auth(charge101_token)).json()
types_202 = client.get("/agency-tools/types", headers=auth(charge202_token)).json()
check("types list is scoped to the agency", "TypeA" in types_101 and "TypeB" not in types_101 and "TypeB" in types_202)

client.post("/epi", json={"name": "Casque test", "type": "Casque", "unique_code": "EPI-PAG-1", "state": 5}, headers=auth(charge101_token))
client.post("/epi", json={"name": "Gants test", "type": "Gants", "unique_code": "EPI-PAG-2", "state": 5}, headers=auth(charge101_token))
r = client.get("/epi?type=Gants", headers=auth(charge101_token))
check("epi type filter works", [e["unique_code"] for e in r.json()] == ["EPI-PAG-2"])
r = client.get("/epi?q=casque&limit=5", headers=auth(charge101_token))
check("epi search and pagination work", len(r.json()) == 1 and r.headers["x-total-count"] == "1")
check("epi search never crosses agencies", client.get("/epi?q=test", headers=auth(charge202_token)).json() == [])
check("epi types list is scoped", "Casque" in client.get("/epi/types", headers=auth(charge101_token)).json() and "Casque" not in client.get("/epi/types", headers=auth(charge202_token)).json())

r = client.get("/loans?scope=agency&limit=1", headers=auth(charge101_token))
check("loans pagination exposes the total", len(r.json()) <= 1 and "x-total-count" in r.headers)
r = client.get(f"/state-history?kind=agency&tool_id={agy101_tool_id}&limit=1", headers=auth(charge101_token))
check("state history pagination works", len(r.json()) == 1 and int(r.headers["x-total-count"]) > 1)

# ---------- Fuseaux horaires : entrée aware -> UTC naïf, sortie naïve -> suffixe Z ----------
_tz_tool = client.post("/agency-tools", json={"name": "Outil TZ", "unique_code": "TZ-1", "purchase_price": 1, "purchase_date": "2024-03-10T12:00:00+02:00"}, headers=auth(admin_token))
check("an offset date is accepted and converted to UTC", _tz_tool.status_code == 201 and _tz_tool.json()["purchase_date"] == "2024-03-10T10:00:00Z")
_tz_z = client.patch(f"/agency-tools/{_tz_tool.json()['id']}", json={"purchase_date": "2024-03-10T08:30:00.000Z"}, headers=auth(admin_token))
check("a Z date is accepted and returned with the Z suffix", _tz_z.status_code == 200 and _tz_z.json()["purchase_date"] == "2024-03-10T08:30:00Z")
check("naive input is left as UTC", client.patch(f"/agency-tools/{_tz_tool.json()['id']}", json={"purchase_date": "2024-03-10T09:00:00"}, headers=auth(admin_token)).json()["purchase_date"] == "2024-03-10T09:00:00Z")
check("free text that is not a date is untouched", client.patch(f"/agency-tools/{_tz_tool.json()['id']}", json={"comment": "rdv 10/03 à 12h"}, headers=auth(admin_token)).json()["comment"] == "rdv 10/03 à 12h")
check("an aware reservation start no longer crashes", client.post("/loans", json={"tool_id": _tz_tool.json()["id"], "start_datetime": (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "end_datetime_planned": (datetime.utcnow() + timedelta(days=3, hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}, headers=auth(admin_token)).status_code == 201)
