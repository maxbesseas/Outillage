from typing import Optional

from sqlalchemy.orm import Session

from .models import StateHistory, ToolKind


def log_state_change(
    db: Session,
    tool_kind: ToolKind,
    tool_id: int,
    old_state: Optional[int],
    new_state: int,
    old_status: Optional[str],
    new_status: Optional[str],
    changed_by_id: Optional[int],
    source: str,
    comment: Optional[str] = None,
    force: bool = False,
):
    if not force and old_state == new_state and old_status == new_status:
        return None

    entry = StateHistory(
        tool_kind=tool_kind,
        tool_id=tool_id,
        old_state=old_state,
        new_state=new_state,
        old_status=old_status,
        new_status=new_status,
        source=source,
        comment=comment,
        changed_by_id=changed_by_id,
    )
    db.add(entry)
    return entry
