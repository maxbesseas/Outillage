import unicodedata
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from .. import audit, schemas
from ..agencies import registry_name_for
from ..auth import get_current_user
from ..database import get_db
from ..excel_export import sync_new_agency_tool
from ..hierarchy import visible_user_ids
from ..history import log_state_change
from ..models import AgencyTool, AgencyToolStatus, PersonalTool, ToolKind, User
from .. import notify
from ..notifications import notify_magasinier
from ..utils import save_upload_file

router = APIRouter(prefix="/personal-tools", tags=["personal-tools"])


def _ascii_header_safe(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _get_manageable_or_404(db: Session, tool_id: int, current_user: User) -> PersonalTool:
    tool = db.query(PersonalTool).filter(PersonalTool.id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outil introuvable")

    if current_user.role == "admin":
        return tool
    if tool.owner_id == current_user.id or tool.current_holder_id == current_user.id:
        return tool

    ids = visible_user_ids(db, current_user)
    if ids is not None and tool.owner_id in ids:
        return tool

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à cet outil")


def _get_deletable_or_404(db: Session, tool_id: int, current_user: User) -> PersonalTool:
    tool = db.query(PersonalTool).filter(PersonalTool.id == tool_id).first()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outil introuvable")

    if current_user.role == "admin" or tool.owner_id == current_user.id:
        return tool

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Seul le propriétaire peut supprimer cet outil")


@router.get("", response_model=list[schemas.PersonalToolOut])
def list_personal_tools(
    owner_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if owner_id is not None:
        ids = visible_user_ids(db, current_user)
        if ids is not None and owner_id not in ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à ce salarié")
        return db.query(PersonalTool).filter(PersonalTool.owner_id == owner_id).order_by(PersonalTool.name).all()

    ids = visible_user_ids(db, current_user)
    query = db.query(PersonalTool)
    if ids is not None:
        query = query.filter(
            (PersonalTool.owner_id.in_(ids)) | (PersonalTool.current_holder_id == current_user.id)
        )
    return query.order_by(PersonalTool.name).all()


@router.post("", response_model=schemas.PersonalToolOut, status_code=status.HTTP_201_CREATED)
def create_personal_tool(
    payload: schemas.PersonalToolCreate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = (
        db.query(PersonalTool).filter(PersonalTool.unique_code == payload.unique_code).first()
        or db.query(AgencyTool).filter(AgencyTool.unique_code == payload.unique_code).first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce code existe déjà")

    tool = PersonalTool(
        owner_id=current_user.id,
        current_holder_id=current_user.id,
        **payload.model_dump(),
    )
    db.add(tool)
    db.flush()

    log_state_change(
        db, ToolKind.personal, tool.id, None, tool.state, None, tool.state_reason.value,
        current_user.id, "création",
    )

    mirror = AgencyTool(
        name=tool.name,
        type=tool.type,
        brand=tool.brand,
        unique_code=tool.unique_code,
        state=tool.state,
        status=AgencyToolStatus.dotation,
        assigned_to_id=current_user.id,
        agency_number=current_user.agency_number,
        purchase_date=tool.purchase_date,
        purchase_price=tool.purchase_price,
        warranty_expiration_date=tool.warranty_expiration_date,
        last_control_date=tool.last_control_date,
    )
    db.add(mirror)
    db.flush()
    log_state_change(
        db, ToolKind.agency, mirror.id, None, mirror.state, None, mirror.status.value,
        current_user.id, "création",
    )

    db.commit()
    db.refresh(tool)

    ok, message = sync_new_agency_tool(mirror, registry_name_for(db, mirror.agency_number))
    response.headers["X-Excel-Sync"] = "ok" if ok else _ascii_header_safe(message)

    return tool


@router.get("/lookup/{code}", response_model=schemas.PersonalToolLookup)
def lookup_personal_tool(code: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tool = db.query(PersonalTool).filter(PersonalTool.unique_code == code).first()
    if not tool:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aucun outil trouvé pour ce code")

    return schemas.PersonalToolLookup(
        id=tool.id,
        name=tool.name,
        unique_code=tool.unique_code,
        owner_id=tool.owner_id,
        owner_name=tool.owner.full_name,
        current_holder_id=tool.current_holder_id,
    )


@router.get("/{tool_id}", response_model=schemas.PersonalToolOut)
def get_personal_tool(tool_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _get_manageable_or_404(db, tool_id, current_user)


@router.patch("/{tool_id}", response_model=schemas.PersonalToolOut)
def update_personal_tool(
    tool_id: int,
    payload: schemas.PersonalToolUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tool = _get_manageable_or_404(db, tool_id, current_user)
    data = payload.model_dump(exclude_unset=True)

    old_state = tool.state
    for field, value in data.items():
        setattr(tool, field, value)

    if "state" in data and data["state"] != old_state:
        log_state_change(
            db, ToolKind.personal, tool.id, old_state, tool.state,
            tool.state_reason.value, tool.state_reason.value,
            current_user.id, "édition",
        )

    db.commit()
    db.refresh(tool)
    return tool


@router.patch("/{tool_id}/state", response_model=schemas.PersonalToolOut)
def update_personal_tool_state(
    tool_id: int,
    payload: schemas.PersonalToolStateUpdate,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tool = _get_manageable_or_404(db, tool_id, current_user)

    old_state = tool.state
    old_reason = tool.state_reason

    tool.state = payload.state
    tool.state_reason = payload.state_reason
    tool.state_comment = payload.state_comment

    log_state_change(
        db, ToolKind.personal, tool.id, old_state, tool.state,
        old_reason.value, tool.state_reason.value,
        current_user.id, "changement d'état", comment=payload.state_comment,
    )

    db.commit()
    db.refresh(tool)

    if tool.state_reason.value != "normal":
        notify.on_tool_problem(db, "personal", tool, current_user.id, tool.state_reason.value)
        ok, message = notify_magasinier(
            db,
            f"Outil signalé : {tool.name}",
            f"L'outil {tool.name} ({tool.unique_code}) a été signalé : {tool.state_reason.value}.\n"
            f"Commentaire : {tool.state_comment or '-'}",
        )
        db.commit()
        response.headers["X-Notification"] = "ok" if ok else _ascii_header_safe(message)
    else:
        response.headers["X-Notification"] = "ok"

    return tool


@router.post("/{tool_id}/photo", response_model=schemas.PersonalToolOut)
def upload_personal_tool_photo(
    tool_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tool = _get_manageable_or_404(db, tool_id, current_user)
    tool.photo_path = save_upload_file(file, "personal_tools")
    db.commit()
    db.refresh(tool)
    return tool


@router.post("/{tool_id}/state-photo", response_model=schemas.PersonalToolOut)
def upload_personal_tool_state_photo(
    tool_id: int,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tool = _get_manageable_or_404(db, tool_id, current_user)
    tool.state_photo_path = save_upload_file(file, "personal_tools_damage")
    db.commit()
    db.refresh(tool)
    return tool


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_personal_tool(
    tool_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tool = _get_deletable_or_404(db, tool_id, current_user)
    audit.record(db, "personal_tool_deleted", current_user.id, "personal_tool", tool.id, request,
                 {"name": tool.name, "code": tool.unique_code})
    db.delete(tool)
    db.commit()
    return None
