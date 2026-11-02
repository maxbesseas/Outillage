from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import StateHistory, ToolKind, User

router = APIRouter(prefix="/state-history", tags=["state-history"])

VALID_KINDS = {k.value for k in ToolKind}


@router.get("", response_model=list[schemas.StateHistoryOut])
def list_state_history(
    response: Response,
    kind: str,
    tool_id: int,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if kind not in VALID_KINDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Type d'outil invalide")

    query = db.query(StateHistory).filter(StateHistory.tool_kind == kind, StateHistory.tool_id == tool_id)
    response.headers["X-Total-Count"] = str(query.count())
    query = query.order_by(StateHistory.changed_at.desc(), StateHistory.id.desc())
    if limit is not None:
        query = query.offset(max(offset, 0)).limit(max(1, min(limit, 500)))
    return query.all()
