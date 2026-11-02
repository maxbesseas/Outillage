"""Cohérence des fuseaux horaires : la base stocke de l'UTC « naïf ».

- Entrée : toute date ISO portant un fuseau (« ...Z », « +02:00 ») dans un corps JSON est convertie en UTC naïf,
  ce qui évite les comparaisons naïf/aware et l'enregistrement d'heures décalées.
- Sortie : toute date ISO naïve d'une réponse JSON reçoit le suffixe « Z », pour que le navigateur la lise comme de l'UTC
  (sans quoi il l'interprète en heure locale et affiche un décalage d'une ou deux heures).
"""
import json
import re
from datetime import datetime, timedelta, timezone

AWARE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$")
NAIVE_IN_JSON = re.compile(rb'(?<=")(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)(?=")')
BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def to_naive_utc(text: str) -> str:
    value = text[:-1] + "+00:00" if text.endswith("Z") else text
    if re.search(r"[+-]\d{4}$", value):
        value = value[:-2] + ":" + value[-2:]
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return text
    if dt.tzinfo is None:
        return text
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def _walk(node):
    if isinstance(node, dict):
        return {k: _walk(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v) for v in node]
    if isinstance(node, str) and AWARE.match(node):
        return to_naive_utc(node)
    return node


class NaiveUtcMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope["method"] in BODY_METHODS:
            headers = {k.lower(): v for k, v in scope["headers"]}
            if b"application/json" in headers.get(b"content-type", b""):
                body, more = b"", True
                while more:
                    message = await receive()
                    body += message.get("body", b"")
                    more = message.get("more_body", False)
                try:
                    body = json.dumps(_walk(json.loads(body)), ensure_ascii=False).encode("utf-8") if body else body
                except ValueError:
                    pass
                scope = dict(scope)
                scope["headers"] = [(k, str(len(body)).encode() if k.lower() == b"content-length" else v) for k, v in scope["headers"]]
                sent = False

                async def receive():  # noqa: F811
                    nonlocal sent
                    if not sent:
                        sent = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return {"type": "http.disconnect"}

        state = {"json": False, "start": None}

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                ctype = dict((k.lower(), v) for k, v in message.get("headers", [])).get(b"content-type", b"")
                if b"application/json" in ctype:
                    state["json"], state["start"], state["chunks"] = True, message, []
                    return
                await send(message)
                return
            if message["type"] == "http.response.body" and state["json"]:
                state["chunks"].append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                body = NAIVE_IN_JSON.sub(rb"\1Z", b"".join(state["chunks"]))
                start = dict(state["start"])
                start["headers"] = [(k, str(len(body)).encode() if k.lower() == b"content-length" else v) for k, v in start["headers"]]
                await send(start)
                await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        await self.app(scope, receive, wrapped_send)
