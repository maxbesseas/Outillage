# ---------- Mise en ligne : cron sans thread, compte admin initial, base chiffrée, IP derrière proxy ----------
from types import SimpleNamespace as _NS12

from app import config as _cfg12, utils as _ut12

check("the cron tick refuses a missing or wrong token", client.get("/cron/tick").status_code == 403 and client.get("/cron/tick", headers={"Authorization": "Bearer nope"}).status_code == 403)
r = client.get("/cron/tick", headers={"Authorization": "Bearer cron-test-token"})
check("the cron tick runs the jobs that are due", r.status_code == 200 and isinstance(r.json()["results"], list))

_saved12 = (_cfg12.IS_PROD, _cfg12.ADMIN_PASSWORD, _cfg12.DATABASE_URL, _cfg12.TRUST_PROXY_HEADERS)


def _raises12(**kwargs):
    try:
        _cfg12.validate_startup(is_prod=True, secret_key="une-cle-de-test", **kwargs)
    except RuntimeError:
        return True
    return False


try:
    _cfg12.IS_PROD, _cfg12.ADMIN_PASSWORD = True, None
    check("production creates no admin without a provided password", _cfg12.initial_admin_password() is None)
    _cfg12.ADMIN_PASSWORD = "un-mot-de-passe-fourni"
    check("production uses the provided admin password", _cfg12.initial_admin_password() == "un-mot-de-passe-fourni")
    _cfg12.ADMIN_PASSWORD = _cfg12.DEFAULT_ADMIN_PASSWORD
    check("production refuses the development admin password", _raises12())
    _cfg12.ADMIN_PASSWORD = None
    _cfg12.IS_PROD = False
    check("development keeps its default admin password", _cfg12.initial_admin_password() == _cfg12.DEFAULT_ADMIN_PASSWORD)

    _cfg12.DATABASE_URL = "postgresql+psycopg://u:p@h/db"
    check("production refuses an unencrypted PostgreSQL connection", _raises12())
    _cfg12.DATABASE_URL = "postgresql+psycopg://u:p@h/db?sslmode=disable"
    check("production refuses sslmode=disable", _raises12())
    _cfg12.DATABASE_URL = "postgresql+psycopg://u:p@h/db?sslmode=require"
    check("production accepts an encrypted PostgreSQL connection", not _raises12())

    _req12 = _NS12(headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, client=_NS12(host="10.0.0.1"))
    _cfg12.TRUST_PROXY_HEADERS = False
    check("the forwarded IP is ignored by default (it could be forged)", _ut12.client_ip(_req12) == "10.0.0.1")
    _cfg12.TRUST_PROXY_HEADERS = True
    check("behind a trusted proxy the forwarded IP is used", _ut12.client_ip(_req12) == "203.0.113.9")
finally:
    _cfg12.IS_PROD, _cfg12.ADMIN_PASSWORD, _cfg12.DATABASE_URL, _cfg12.TRUST_PROXY_HEADERS = _saved12

from app import database as _db12

check("a transaction pooler gets no client pool and no prepared statements", _db12.engine_options("postgresql+psycopg://u:p@h:6543/db?sslmode=require") == {"poolclass": _db12.NullPool, "connect_args": {"prepare_threshold": None}})
check("a session connection keeps its small pool", _db12.engine_options("postgresql+psycopg://u:p@h:5432/db?sslmode=require")["pool_size"] == 2)

import io as _io12

from fastapi import HTTPException as _HE12, UploadFile as _UF12

_big12 = _UF12(file=_io12.BytesIO(b"x" * (_ut12.MAX_DOCUMENT_BYTES + 1)), filename="grosse.jpg")
try:
    _ut12.save_upload_file(_big12, "test12")
    _refused12 = False
except _HE12 as exc:
    _refused12 = exc.status_code == 400
check("an oversized photo is refused", _refused12)
_small12 = _ut12.save_upload_file(_UF12(file=_io12.BytesIO(b"petite"), filename="petite.png"), "test12")
check("a normal photo is still saved", _small12.startswith("/uploads/test12/") and _small12.endswith(".png"))

import jwt as _jwt12

_forged12 = _jwt12.encode({"sub": "admin", "tv": 0}, "pas-la-bonne-cle-pas-la-bonne-cle-pas-la-bonne", algorithm="HS256")
check("a token signed with another key is refused", client.get("/users", headers={"Authorization": f"Bearer {_forged12}"}).status_code == 401)
_none12 = _jwt12.encode({"sub": "admin", "tv": 0}, None, algorithm="none")
check("an unsigned token is refused", client.get("/users", headers={"Authorization": f"Bearer {_none12}"}).status_code == 401)
check("an unknown account gets the same answer as a wrong password", client.post("/auth/login", json={"username": "inconnu12", "password": "x"}).status_code == 401)
check("reports need an API key", client.get("/reports").status_code in (401, 403))

_mgr12 = next(u["id"] for u in client.get("/users", headers=auth(admin_token)).json() if u["username"] == "charge101")
_uid12 = make_user("del12", admin_token, "gars_chantier", manager_id=_mgr12)
login("del12")
check("a session token does not prevent deleting an account", client.delete(f"/users/{_uid12}", headers=auth(admin_token)).status_code == 204)
