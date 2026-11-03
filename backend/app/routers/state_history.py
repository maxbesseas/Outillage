from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import controls, schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import PeerTransfer, StateHistory, ToolKind, User, UserRole

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
    if current_user.role != UserRole.admin:
        tool = controls.get_tool(db, kind, tool_id)
        # Une personne qui a participé à un transfert garde l'historique de l'outil, même rendu depuis.
        party = kind == "personal" and db.query(PeerTransfer).filter(
            PeerTransfer.tool_id == tool_id, or_(PeerTransfer.from_user_id == current_user.id, PeerTransfer.to_user_id == current_user.id)
        ).first() is not None
        if tool is None or not (party or controls.can_access(db, current_user, kind, tool)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à cet outil")

    query = db.query(StateHistory).filter(StateHistory.tool_kind == kind, StateHistory.tool_id == tool_id)
    response.headers["X-Total-Count"] = str(query.count())
    query = query.order_by(StateHistory.changed_at.desc(), StateHistory.id.desc())
    if limit is not None:
        query = query.offset(max(offset, 0)).limit(max(1, min(limit, 500)))
    return query.all()
