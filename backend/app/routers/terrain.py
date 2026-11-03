"""Phase 3 : fiche outil unifiée, recherche par code (scan), lots de scan, galerie photos."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, controls, maintenance, utils
from ..agencies import agency_scope
from ..auth import get_current_manager, get_current_user
from ..database import get_db
from ..models import AgencyTool, AgencyToolStatus, Epi, Loan, LoanStatus, PersonalTool, User, UserRole
from ..models_p3 import ToolLabel, ToolPhoto
from ..models_p5 import MaintenanceTicket, ToolAccessory

router = APIRouter(prefix="/tools", tags=["terrain"])
photos_router = APIRouter(prefix="/tool-photos", tags=["terrain"])

PHOTO_KINDS = ("reference", "etat", "dommage", "autre")
MAX_PHOTOS_PER_TOOL = 40
LABELS_LIMIT = 2000


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


def _find_by_code(db: Session, code: str):
    code = (code or "").strip()
    for kind, model in (("agency", AgencyTool), ("epi", Epi), ("personal", PersonalTool)):
        tool = db.query(model).filter(model.unique_code == code).first()
        if tool:
            return kind, tool
    return None, None


def _enum(v):
    return getattr(v, "value", v)


def _summary(db: Session, kind: str, tool) -> dict:
    holder_id = getattr(tool, "current_holder_id", None) or getattr(tool, "assigned_to_id", None) or getattr(tool, "owner_id", None)
    holder = db.query(User).filter(User.id == holder_id).first() if holder_id else None
    return {
        "kind": kind, "id": tool.id, "name": tool.name, "type": tool.type, "brand": tool.brand,
        "unique_code": tool.unique_code, "state": tool.state, "photo_path": tool.photo_path,
        "status": _enum(getattr(tool, "status", None)), "agency_number": controls.tool_agency(db, kind, tool),
        "holder_name": holder.full_name if holder else None,
    }


def _resolve(db: Session, user: User, code: str):
    kind, tool = _find_by_code(db, code)
    if tool is None:
        return None, "not_found"
    if not controls.can_access(db, user, kind, tool):
        return None, "forbidden"
    return (kind, tool), "ok"


@router.get("/lookup")
def lookup(code: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    found, result = _resolve(db, current_user, code)
    if result == "not_found":
        _fail("Aucun outil ne correspond à ce code", status.HTTP_404_NOT_FOUND)
    if result == "forbidden":
        _fail("Cet outil appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    return _summary(db, *found)


class BatchIn(BaseModel):
    codes: List[str] = Field(min_length=1, max_length=200)


@router.post("/lookup-batch")
def lookup_batch(payload: BatchIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    out = []
    for code in dict.fromkeys(c.strip() for c in payload.codes if c and c.strip()):
        found, result = _resolve(db, current_user, code)
        out.append({"code": code, "result": result, "tool": _summary(db, *found) if found else None})
    return out


@router.get("/labels")
def label_list(response: Response, kind: str = "agency", type_: Optional[str] = None, only_unprinted: bool = False, q: Optional[str] = None,
               limit: int = LABELS_LIMIT, offset: int = 0, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    if kind not in ("agency", "epi"):
        _fail("Étiquettes disponibles pour les outils d'agence et les EPI")
    model = controls.MODELS[kind]
    query = db.query(model)
    if current_user.role != UserRole.admin:
        query = query.filter(model.agency_number == current_user.agency_number)
    if kind == "agency":
        query = query.filter(model.status != AgencyToolStatus.sorti_du_parc)
    if type_:
        query = query.filter(model.type == type_)
    if q:
        like = f"%{q}%"
        query = query.filter((model.name.ilike(like)) | (model.unique_code.ilike(like)))
    printed = {r.tool_id: r.printed_at for r in db.query(ToolLabel).filter_by(tool_kind=kind)}
    if only_unprinted and printed:
        query = query.filter(model.id.notin_(list(printed)))
    response.headers["X-Total-Count"] = str(query.count())
    return [
        {"id": t.id, "name": t.name, "type": t.type, "unique_code": t.unique_code, "printed_at": printed.get(t.id)}
        for t in query.order_by(model.name, model.id).offset(max(offset, 0)).limit(max(1, min(limit, LABELS_LIMIT)))
    ]


class PrintedIn(BaseModel):
    kind: str
    ids: List[int] = Field(min_length=1, max_length=2000)


@router.post("/labels/printed")
def mark_printed(payload: PrintedIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    if payload.kind not in ("agency", "epi"):
        _fail("Type d'outil invalide")
    count = 0
    for tool_id in dict.fromkeys(payload.ids):
        tool = controls.get_tool(db, payload.kind, tool_id)
        if tool is None or not controls.can_access(db, current_user, payload.kind, tool):
            continue
        row = db.query(ToolLabel).filter_by(tool_kind=payload.kind, tool_id=tool_id).first()
        if row is None:
            db.add(ToolLabel(tool_kind=payload.kind, tool_id=tool_id, printed_at=utils.now(), printed_by_id=current_user.id))
        else:
            row.printed_at = utils.now()
            row.printed_by_id = current_user.id
        count += 1
    db.commit()
    return {"marked": count}


def _tool_or_error(db: Session, user: User, kind: str, tool_id: int):
    if kind not in controls.MODELS:
        _fail("Type d'outil inconnu")
    tool = controls.get_tool(db, kind, tool_id)
    if tool is None:
        _fail("Outil introuvable", status.HTTP_404_NOT_FOUND)
    if not controls.can_access(db, user, kind, tool):
        _fail("Cet outil appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    return tool


@router.get("/{kind}/{tool_id}/sheet")
def tool_sheet(kind: str, tool_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tool = _tool_or_error(db, current_user, kind, tool_id)
    data = _summary(db, kind, tool)
    data.update({
        "serial_number": getattr(tool, "serial_number", None), "comment": tool.comment,
        "description": getattr(tool, "description", None), "purchase_date": getattr(tool, "purchase_date", None),
        "expiration_date": getattr(tool, "expiration_date", None),
        "control": controls.due_info(db, kind, tool) if controls._controllable(kind, tool) else None,
        "warranty": maintenance.warranty_info(tool) if kind == "agency" else None,
    })
    if kind == "agency":
        loan = (
            db.query(Loan).filter(Loan.tool_id == tool.id, Loan.status == LoanStatus.en_cours).order_by(Loan.id.desc()).first()
        )
        nxt = (
            db.query(Loan).filter(Loan.tool_id == tool.id, Loan.status == LoanStatus.reserve,
                                  Loan.start_datetime >= utils.now()).order_by(Loan.start_datetime).limit(3).all()
        )
        borrowers = {u.id: u.full_name for u in db.query(User).filter(User.id.in_([l.borrower_id for l in ([loan] if loan else []) + nxt] or [0]))}
        data["current_loan"] = (
            {"id": loan.id, "borrower_id": loan.borrower_id, "borrower_name": borrowers.get(loan.borrower_id),
             "end_datetime_planned": loan.end_datetime_planned, "site": loan.site} if loan else None
        )
        data["next_reservations"] = [
            {"id": l.id, "borrower_name": borrowers.get(l.borrower_id), "start_datetime": l.start_datetime,
             "end_datetime_planned": l.end_datetime_planned} for l in nxt
        ]
        data["accessories"] = [
            {"name": a.name, "quantity": a.quantity, "required": a.required}
            for a in db.query(ToolAccessory).filter(ToolAccessory.tool_id == tool.id)
        ]
    tickets = (
        db.query(MaintenanceTicket)
        .filter(MaintenanceTicket.tool_kind == kind, MaintenanceTicket.tool_id == tool.id,
                MaintenanceTicket.status.in_(maintenance.OPEN_STATUSES))
        .order_by(MaintenanceTicket.id.desc()).all()
    )
    data["open_tickets"] = [
        {"id": t.id, "category": t.category, "severity": t.severity, "status": t.status, "opened_at": t.opened_at}
        for t in tickets
    ]
    data["photos"] = _photos(db, kind, tool.id)
    data["can_manage"] = current_user.role != UserRole.gars_chantier
    return data


def _photos(db: Session, kind: str, tool_id: int) -> list:
    rows = db.query(ToolPhoto).filter_by(tool_kind=kind, tool_id=tool_id).order_by(ToolPhoto.id.desc()).all()
    names = {u.id: u.full_name for u in db.query(User).filter(User.id.in_([r.taken_by_id for r in rows if r.taken_by_id] or [0]))}
    return [
        {"id": r.id, "path": r.path, "kind": r.kind, "caption": r.caption, "taken_by": names.get(r.taken_by_id),
         "created_at": r.created_at}
        for r in rows
    ]


@photos_router.get("/{kind}/{tool_id}")
def list_photos(kind: str, tool_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _tool_or_error(db, current_user, kind, tool_id)
    return _photos(db, kind, tool_id)


@photos_router.post("/{kind}/{tool_id}", status_code=status.HTTP_201_CREATED)
def add_photo(kind: str, tool_id: int, file: UploadFile, request: Request, photo_kind: str = "etat", caption: Optional[str] = None,
              db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _tool_or_error(db, current_user, kind, tool_id)
    if photo_kind not in PHOTO_KINDS:
        _fail("Type de photo invalide")
    if db.query(ToolPhoto).filter_by(tool_kind=kind, tool_id=tool_id).count() >= MAX_PHOTOS_PER_TOOL:
        _fail(f"Maximum {MAX_PHOTOS_PER_TOOL} photos par outil")
    path = utils.save_document(file, f"tool_photos/{kind}", allowed={".jpg", ".jpeg", ".png", ".webp"})
    photo = ToolPhoto(tool_kind=kind, tool_id=tool_id, path=path, kind=photo_kind,
                      caption=(caption or None) and caption[:300], taken_by_id=current_user.id, created_at=utils.now())
    db.add(photo)
    db.flush()
    audit.record(db, "tool_photo_added", current_user.id, "tool_photo", photo.id, request, {"tool_kind": kind, "tool_id": tool_id})
    db.commit()
    return {"id": photo.id, "path": path, "kind": photo.kind}


@photos_router.delete("/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(photo_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    photo = db.query(ToolPhoto).filter_by(id=photo_id).first()
    if photo is None:
        _fail("Photo introuvable", status.HTTP_404_NOT_FOUND)
    _tool_or_error(db, current_user, photo.tool_kind, photo.tool_id)
    manager = current_user.role != UserRole.gars_chantier
    if not manager and photo.taken_by_id != current_user.id:
        _fail("Seul l'auteur ou un responsable peut supprimer cette photo", status.HTTP_403_FORBIDDEN)
    audit.record(db, "tool_photo_deleted", current_user.id, "tool_photo", photo.id, request, {"tool_kind": photo.tool_kind, "tool_id": photo.tool_id})
    db.delete(photo)
    db.commit()


# ------------------------------------------------------------------ recherche globale (Phase 10)

search_router = APIRouter(prefix="/search", tags=["recherche"])
SEARCH_LIMIT = 6


def _agency_scope(user: User) -> Optional[str]:
    return agency_scope(user)


@search_router.get("")
def global_search(q: str = "", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from ..hierarchy import visible_user_ids
    from ..models_p6 import Site

    query = (q or "").strip()
    if len(query) < 2:
        return {"query": query, "categories": []}
    like = f"%{query}%"
    categories = []

    for kind, model, label in (("agency", AgencyTool, "Outils d'agence"), ("epi", Epi, "EPI")):
        rows = db.query(model).filter(model.name.ilike(like) | model.unique_code.ilike(like) | model.type.ilike(like))
        if _agency_scope(current_user) is not None:
            rows = rows.filter(model.agency_number == _agency_scope(current_user))
        rows = rows.order_by(model.name).limit(SEARCH_LIMIT).all()
        if rows:
            categories.append({"label": label, "items": [
                {"title": t.name, "subtitle": t.unique_code, "link": f"#/outil/{kind}/{t.id}"} for t in rows
            ]})

    ptools = db.query(PersonalTool).filter(PersonalTool.name.ilike(like) | PersonalTool.unique_code.ilike(like))
    ids = visible_user_ids(db, current_user)
    if ids is not None:
        ptools = ptools.filter((PersonalTool.owner_id.in_(ids)) | (PersonalTool.current_holder_id == current_user.id))
    ptools = ptools.order_by(PersonalTool.name).limit(SEARCH_LIMIT).all()
    if ptools:
        categories.append({"label": "Outils personnels", "items": [
            {"title": t.name, "subtitle": t.unique_code, "link": f"#/outil/personal/{t.id}"} for t in ptools
        ]})

    sites = db.query(Site).filter(Site.name.ilike(like) | Site.client.ilike(like) | Site.code.ilike(like))
    if _agency_scope(current_user) is not None:
        sites = sites.filter(Site.agency_number == _agency_scope(current_user))
    sites = sites.order_by(Site.name).limit(SEARCH_LIMIT).all()
    if sites:
        categories.append({"label": "Chantiers", "items": [
            {"title": s.name, "subtitle": s.client or (s.status == "clos" and "Clos") or "", "link": "#/chantiers"} for s in sites
        ]})

    if current_user.role != UserRole.gars_chantier:
        tickets = db.query(MaintenanceTicket).filter(MaintenanceTicket.description.ilike(like))
        if _agency_scope(current_user) is not None:
            tickets = tickets.filter(MaintenanceTicket.agency_number == _agency_scope(current_user))
        tickets = tickets.order_by(MaintenanceTicket.id.desc()).limit(SEARCH_LIMIT).all()
        if tickets:
            categories.append({"label": "Tickets de maintenance", "items": [
                {"title": f"Ticket n°{t.id}", "subtitle": (t.description or "")[:80], "link": "#/maintenance"} for t in tickets
            ]})

        users_q = db.query(User).filter(User.full_name.ilike(like) | User.username.ilike(like))
        if _agency_scope(current_user) is not None:
            users_q = users_q.filter(User.agency_number == _agency_scope(current_user))
        elif ids is not None:
            users_q = users_q.filter(User.id.in_(ids))
        users_rows = users_q.order_by(User.full_name).limit(SEARCH_LIMIT).all()
        if users_rows:
            categories.append({"label": "Équipe", "items": [
                {"title": u.full_name, "subtitle": u.username, "link": "#/utilisateurs"} for u in users_rows
            ]})

    return {"query": query, "categories": categories}
