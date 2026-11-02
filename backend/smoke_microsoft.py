# ---------- Connexion Microsoft : compte créé par l'admin, e-mail vérifié, puis identité Microsoft ----------
import time as _time_ms
from urllib.parse import parse_qs as _pq_ms, urlsplit as _us_ms

import jwt as _jwt_ms
from cryptography.hazmat.primitives.asymmetric import rsa as _rsa_ms

from app import config as _cfg_ms
from app.routers import microsoft as _ms

check("Microsoft login is hidden until it is configured", client.get("/auth/microsoft/config").json() == {"enabled": False} and client.get("/auth/microsoft/login", follow_redirects=False).status_code == 404)
check("the Microsoft callback is closed until it is configured", client.get("/auth/microsoft/callback?code=x&state=y", follow_redirects=False).status_code == 404)

_key_ms = _rsa_ms.generate_private_key(public_exponent=65537, key_size=2048)
_other_key_ms = _rsa_ms.generate_private_key(public_exponent=65537, key_size=2048)
_org_ms = "11111111-1111-1111-1111-111111111111"
_saved_ms = (_cfg_ms.MS_CLIENT_ID, _cfg_ms.MS_CLIENT_SECRET, _ms._signing_key, _ms._redeem_code)
_cfg_ms.MS_CLIENT_ID, _cfg_ms.MS_CLIENT_SECRET = "client-id-test", "client-secret-test"
_ms._signing_key = lambda token: _key_ms.public_key()


def _flow_ms(oid="oid-1", email=None, tid=_org_ms, sign_with=None, state=None, **overrides):
    start = client.get("/auth/microsoft/login", follow_redirects=False)
    query = _pq_ms(_us_ms(start.headers["location"]).query)
    claims = {
        "iss": f"https://login.microsoftonline.com/{tid}/v2.0", "aud": _cfg_ms.MS_CLIENT_ID, "tid": tid, "oid": oid,
        "nonce": query["nonce"][0], "iat": int(_time_ms.time()), "exp": int(_time_ms.time()) + 300, "xms_edov": True,
    }
    if email:
        claims["email"] = email
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    token = _jwt_ms.encode(claims, sign_with or _key_ms, algorithm="RS256")
    _ms._redeem_code = lambda code, verifier: token if _ms._pkce_challenge(verifier) == query["code_challenge"][0] else None
    end = client.get("/auth/microsoft/callback", params={"code": "code-ms", "state": state or query["state"][0]}, follow_redirects=False)
    return end.headers.get("location", "")


def _sso_ms(location):
    return _pq_ms(location.split("?", 1)[1]).get("sso", [None])[0] if "?" in location else None


try:
    _start_ms = client.get("/auth/microsoft/login", follow_redirects=False)
    _q_ms = _pq_ms(_us_ms(_start_ms.headers["location"]).query)
    check("the Microsoft redirect uses a PKCE challenge and a nonce", _q_ms["code_challenge_method"] == ["S256"] and _q_ms["nonce"] and _q_ms["state"])
    check("the flow cookie is not readable by scripts", "httponly" in _start_ms.headers["set-cookie"].lower() and "samesite=lax" in _start_ms.headers["set-cookie"].lower())
    check("no client secret travels through the browser", "client-secret-test" not in _start_ms.headers["location"])

    _mgr_ms = next(u["id"] for u in client.get("/users", headers=auth(admin_token)).json() if u["username"] == "charge101")
    _uid_ms = make_user("msuser", admin_token, "gars_chantier", manager_id=_mgr_ms)
    client.patch(f"/users/{_uid_ms}", headers=auth(admin_token), json={"email": "MS.User@exemple.fr"})

    check("an unknown Microsoft account is refused", _flow_ms(email="inconnu@exemple.fr").endswith("sso_error=no_account"))
    check("no account is created by a Microsoft login", all(u["email"] != "inconnu@exemple.fr" for u in client.get("/users", headers=auth(admin_token)).json()))
    check("an unverified e-mail cannot link an account", _flow_ms(oid="attaquant", email="ms.user@exemple.fr", xms_edov=None).endswith("sso_error=no_account"))
    check("xms_edov false cannot link an account", _flow_ms(oid="attaquant", email="ms.user@exemple.fr", xms_edov=False).endswith("sso_error=no_account"))
    check("a token signed by another key is refused", _flow_ms(email="ms.user@exemple.fr", sign_with=_other_key_ms).endswith("sso_error=failed"))
    check("a token for another application is refused", _flow_ms(email="ms.user@exemple.fr", aud="autre-appli").endswith("sso_error=failed"))
    check("a token from another issuer is refused", _flow_ms(email="ms.user@exemple.fr", iss="https://evil.example/v2.0").endswith("sso_error=failed"))
    check("a replayed nonce is refused", _flow_ms(email="ms.user@exemple.fr", nonce="ancien-nonce").endswith("sso_error=failed"))
    check("an expired token is refused", _flow_ms(email="ms.user@exemple.fr", exp=int(_time_ms.time()) - 3600).endswith("sso_error=failed"))
    check("a wrong state is refused", _flow_ms(email="ms.user@exemple.fr", state="mauvais").endswith("sso_error=failed"))
    client.cookies.clear()
    check("a callback without the flow cookie is refused", client.get("/auth/microsoft/callback?code=x&state=y", follow_redirects=False).headers["location"].endswith("sso_error=failed"))

    _loc_ms = _flow_ms(oid="oid-msuser", email="ms.user@exemple.fr")
    _code_ms = _sso_ms(_loc_ms)
    check("a verified e-mail links the account created by the admin", bool(_code_ms))
    _tok_ms = client.post("/auth/refresh", json={"refresh_token": _code_ms})
    check("the one-time code opens a session on the right account", _tok_ms.status_code == 200 and _tok_ms.json()["user"]["username"] == "msuser")
    check("the session works", client.get("/auth/me", headers=auth(_tok_ms.json()["access_token"])).json()["id"] == _uid_ms)
    check("the one-time code cannot be used twice", client.post("/auth/refresh", json={"refresh_token": _code_ms}).status_code == 401)
    check("the password still works alongside Microsoft", client.post("/auth/login", json={"username": "msuser", "password": "password123"}).status_code == 200)

    check("the Microsoft identity is used afterwards, whatever the e-mail claim", bool(_sso_ms(_flow_ms(oid="oid-msuser", email="autre@exemple.fr", xms_edov=None))))
    check("a second Microsoft identity cannot take a linked account", _flow_ms(oid="oid-autre", email="ms.user@exemple.fr").endswith("sso_error=no_account"))

    client.patch(f"/users/{_uid_ms}", headers=auth(admin_token), json={"is_active": False})
    check("a deactivated account is refused", _flow_ms(oid="oid-msuser").endswith("sso_error=no_account"))
    client.patch(f"/users/{_uid_ms}", headers=auth(admin_token), json={"is_active": True})

    client.patch(f"/users/{_uid_ms}", headers=auth(admin_token), json={"email": "nouveau@exemple.fr"})
    check("changing the e-mail removes the old Microsoft link", _flow_ms(oid="oid-msuser").endswith("sso_error=no_account"))
    check("the new e-mail can link again", bool(_sso_ms(_flow_ms(oid="oid-nouveau", email="nouveau@exemple.fr"))))

    _admin_id_ms = client.get("/auth/me", headers=auth(admin_token)).json()["id"]
    _admin_email_ms = client.get("/auth/me", headers=auth(admin_token)).json().get("email")
    client.patch(f"/users/{_admin_id_ms}", headers=auth(admin_token), json={"email": "admin.ms@exemple.fr"})
    check("an admin account is never linked automatically", _flow_ms(oid="oid-admin", email="admin.ms@exemple.fr").endswith("sso_error=no_account"))
    client.patch(f"/users/{_admin_id_ms}", headers=auth(admin_token), json={"email": _admin_email_ms})

    _uid2_ms = make_user("msperso", admin_token, "gars_chantier", manager_id=_mgr_ms)
    client.patch(f"/users/{_uid2_ms}", headers=auth(admin_token), json={"email": "perso@outlook.com"})
    check("a personal Microsoft account links without xms_edov", bool(_sso_ms(_flow_ms(oid="oid-perso", email="perso@outlook.com", tid=_ms.PERSONAL_ACCOUNTS_TENANT, xms_edov=None))))

    _uid3_ms = make_user("msdouble1", admin_token, "gars_chantier", manager_id=_mgr_ms)
    _uid4_ms = make_user("msdouble2", admin_token, "gars_chantier", manager_id=_mgr_ms)
    client.patch(f"/users/{_uid3_ms}", headers=auth(admin_token), json={"email": "double@exemple.fr"})
    client.patch(f"/users/{_uid4_ms}", headers=auth(admin_token), json={"email": "double@exemple.fr"})
    check("an e-mail shared by two accounts links neither", _flow_ms(oid="oid-double", email="double@exemple.fr").endswith("sso_error=no_account"))

    _r_ms = client.post(f"/gdpr/anonymize/{_uid2_ms}", headers=auth(admin_token))
    check("anonymising removes the Microsoft link", _r_ms.status_code == 200 and _flow_ms(oid="oid-perso", tid=_ms.PERSONAL_ACCOUNTS_TENANT).endswith("sso_error=no_account"))
finally:
    client.cookies.clear()
    _cfg_ms.MS_CLIENT_ID, _cfg_ms.MS_CLIENT_SECRET, _ms._signing_key, _ms._redeem_code = _saved_ms
