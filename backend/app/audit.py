import json
import re
from typing import Any, Optional

from sqlalchemy.orm import Session
from starlette.requests import Request

from . import utils
from .models import AuditLog

SENSITIVE = re.compile(r"password|passwd|secret|token|api_?key|authorization", re.IGNORECASE)


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if SENSITIVE.search(str(k)) else sanitize(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    return value


def record(
    db: Session,
    action: str,
    user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[Any] = None,
    request: Optional[Request] = None,
    details: Optional[dict] = None,
):
    ip = utils.client_ip(request)
    user_agent = request.headers.get("user-agent", "")[:200] if request is not None else None
    entry = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        ip=ip,
        user_agent=user_agent,
        details=json.dumps(sanitize(details), ensure_ascii=False, default=str) if details else None,
        created_at=utils.now(),
    )
    db.add(entry)
    return entry
