"""Phase 6 : chantiers, coûts par chantier, statistiques d'utilisation du parc."""
import re
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import appsettings, audit, sites, utils
from ..agencies import agency_scope
from ..auth import get_current_manager, get_current_user
from ..database import get_db
from ..models import AgencyTool, AgencyToolStatus, Loan, LoanStatus, User, UserRole
from ..models_p4 import WaitlistEntry
from ..models_p5 import StockItem, StockMovement
from ..models_p6 import Site

router = APIRouter(prefix="/sites", tags=["chantiers"])
stats_router = APIRouter(prefix="/stats", tags=["statistiques"])

OPEN_LOAN_STATUSES = (LoanStatus.en_cours, LoanStatus.reserve, LoanStatus.attente_validation)


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: Optional[str] = Field(default=None, max_length=40)
    client: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=250)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    manager_id: Optional[int] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    agency_number: Optional[str] = None


class SitePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    code: Optional[str] = Field(default=None, max_length=40)
    client: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=250)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    manager_id: Optional[int] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


def _view(db: Session, s: Site, names: Optional[dict] = None) -> dict:
    names = names if names is not None else {u.id: u.full_name for u in db.query(User)}
    on_site = db.query(Loan).filter(Loan.site_id == s.id, Loan.status == LoanStatus.en_cours).count()
    return {
        "id": s.id, "agency_number": s.agency_number, "name": s.name, "code": s.code, "client": s.client,
        "address": s.address, "start_date": s.start_date, "end_date": s.end_date, "status": s.status,
        "manager_id": s.manager_id, "manager_name": names.get(s.manager_id), "notes": s.notes,
        "created_at": s.created_at, "closed_at": s.closed_at, "tools_on_site": on_site,
    }


def _site_or_404(db: Session, user: User, site_id: int) -> Site:
    site = db.query(Site).filter(Site.id == site_id).first()
    if site is None:
        _fail("Chantier introuvable", status.HTTP_404_NOT_FOUND)
    if not sites.can_see(user, site):
        _fail("Ce chantier appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    return site


def _agency_for(user: User, requested: Optional[str]) -> Optional[str]:
    if user.role == UserRole.admin:
        return requested
    return user.agency_number


def _clean_code(db: Session, agency: Optional[str], code: Optional[str], site_id: Optional[int] = None) -> Optional[str]:
    code = (code or "").strip() or None
    if code is None:
        return None
    pattern = appsettings.get(db, "site.code_pattern")
    try:
        valid = not pattern or re.fullmatch(pattern, code) is not None
    except re.error:
        valid = True
    if not valid:
        _fail("Le code du chantier doit contenir 6 chiffres" if pattern == r"\d{6}" else "Le code du chantier n'a pas le format attendu")
    clash = db.query(Site).filter(Site.agency_number == agency, Site.code == code)
    if site_id is not None:
        clash = clash.filter(Site.id != site_id)
    if clash.first():
        _fail("Ce code de chantier existe déjà dans l'agence")
    return code


def _check_manager_user(db: Session, agency: Optional[str], manager_id: Optional[int]):
    if manager_id is None:
        return
    person = db.query(User).filter(User.id == manager_id, User.is_active.is_(True)).first()
    if person is None:
        _fail("Responsable de chantier introuvable")
    if (person.agency_number or None) != (agency or None) and person.role != UserRole.admin:
        _fail("Le responsable doit appartenir à l'agence du chantier")


@router.get("")
def list_sites(response: Response, status_filter: Optional[str] = None, q: Optional[str] = None, limit: int = 200, offset: int = 0,
               db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(Site)
    if current_user.role != UserRole.admin:
        query = query.filter(Site.agency_number == current_user.agency_number)
    if status_filter:
        query = query.filter(Site.status == status_filter)
    if q:
        like = f"%{q}%"
        query = query.filter(Site.name.ilike(like) | Site.client.ilike(like) | Site.code.ilike(like))
    response.headers["X-Total-Count"] = str(query.count())
    rows = query.order_by(Site.status, Site.name).offset(max(offset, 0)).limit(max(1, min(limit, 500))).all()
    names = {u.id: u.full_name for u in db.query(User)}
    return [_view(db, s, names) for s in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_site(payload: SiteIn, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    agency = _agency_for(current_user, payload.agency_number)
    name = payload.name.strip()
    if not name:
        _fail("Le nom du chantier est obligatoire")
    if db.query(Site).filter(Site.agency_number == agency, Site.name.ilike(name)).first():
        _fail("Un chantier de ce nom existe déjà dans l'agence")
    if payload.start_date and payload.end_date and payload.end_date < payload.start_date:
        _fail("La date de fin est antérieure au début")
    _check_manager_user(db, agency, payload.manager_id)
    code = _clean_code(db, agency, payload.code)
    site = Site(agency_number=agency, name=name, code=code, client=payload.client, address=payload.address,
                start_date=payload.start_date, end_date=payload.end_date, manager_id=payload.manager_id,
                notes=payload.notes, status="actif", created_at=utils.now())
    db.add(site)
    db.flush()
    audit.record(db, "site_created", current_user.id, "site", site.id, request, {"name": name})
    db.commit()
    return _view(db, site)


@router.get("/{site_id}")
def get_site(site_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _view(db, _site_or_404(db, current_user, site_id))


@router.patch("/{site_id}")
def update_site(site_id: int, payload: SitePatch, request: Request, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_manager)):
    site = _site_or_404(db, current_user, site_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            _fail("Le nom du chantier est obligatoire")
        clash = db.query(Site).filter(Site.agency_number == site.agency_number, Site.name.ilike(name), Site.id != site.id).first()
        if clash:
            _fail("Un chantier de ce nom existe déjà dans l'agence")
        data["name"] = name
    if "manager_id" in data:
        _check_manager_user(db, site.agency_number, data["manager_id"])
    if "code" in data:
        data["code"] = _clean_code(db, site.agency_number, data["code"], site.id)
    start = data.get("start_date", site.start_date)
    end = data.get("end_date", site.end_date)
    if start and end and end < start:
        _fail("La date de fin est antérieure au début")
    for field, value in data.items():
        setattr(site, field, value)
    if "name" in data:
        db.query(Loan).filter(Loan.site_id == site.id).update({"site": site.name}, synchronize_session=False)
    audit.record(db, "site_updated", current_user.id, "site", site.id, request, {"fields": sorted(data.keys())})
    db.commit()
    return _view(db, site)


@router.post("/{site_id}/close")
def close_site(site_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    site = _site_or_404(db, current_user, site_id)
    if site.status == "clos":
        _fail("Ce chantier est déjà clos")
    open_loans = db.query(Loan).filter(Loan.site_id == site.id, Loan.status.in_(OPEN_LOAN_STATUSES)).all()
    if open_loans:
        names = {t.id: t.name for t in db.query(AgencyTool).filter(AgencyTool.id.in_([l.tool_id for l in open_loans]))}
        listing = ", ".join(sorted({names.get(l.tool_id, "?") for l in open_loans})[:6])
        _fail(f"{len(open_loans)} réservation(s) restent ouvertes sur ce chantier ({listing}). Rendez ou annulez-les avant la clôture.")
    site.status = "clos"
    site.closed_at = utils.now()
    site.closed_by_id = current_user.id
    audit.record(db, "site_closed", current_user.id, "site", site.id, request, {})
    db.commit()
    return _view(db, site)


@router.post("/{site_id}/reopen")
def reopen_site(site_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    site = _site_or_404(db, current_user, site_id)
    if site.status != "clos":
        _fail("Ce chantier n'est pas clos")
    site.status = "actif"
    site.closed_at = None
    site.closed_by_id = None
    audit.record(db, "site_reopened", current_user.id, "site", site.id, request, {})
    db.commit()
    return _view(db, site)


@router.get("/{site_id}/sheet")
def site_sheet(site_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    site = _site_or_404(db, current_user, site_id)
    names = {u.id: u.full_name for u in db.query(User)}
    loans = db.query(Loan).filter(Loan.site_id == site.id).order_by(Loan.start_datetime.desc()).limit(200).all()
    tools = {t.id: t for t in db.query(AgencyTool).filter(AgencyTool.id.in_([l.tool_id for l in loans] or [0]))}
    stock = db.query(StockMovement).filter(StockMovement.site_id == site.id, StockMovement.kind == "sortie").order_by(StockMovement.id.desc()).all()
    items = {i.id: i for i in db.query(StockItem).filter(StockItem.id.in_([m.item_id for m in stock] or [0]))}
    cost = sites.site_cost(db, site)
    return {
        "site": _view(db, site, names),
        "current_tools": [
            {"loan_id": l.id, "tool_id": l.tool_id, "tool_name": tools[l.tool_id].name if l.tool_id in tools else "?",
             "borrower_name": names.get(l.borrower_id), "since": l.checked_out_at or l.start_datetime, "planned_end": l.end_datetime_planned}
            for l in loans if l.status == LoanStatus.en_cours
        ],
        "loans": [
            {"id": l.id, "tool_name": tools[l.tool_id].name if l.tool_id in tools else "?", "borrower_name": names.get(l.borrower_id),
             "status": l.status.value, "start_datetime": l.start_datetime, "end_datetime_planned": l.end_datetime_planned,
             "actual_return_datetime": l.actual_return_datetime, "days": sites.loan_days(l)}
            for l in loans
        ],
        "stock_issued": [
            {"item": items[m.item_id].name if m.item_id in items else "?", "unit": items[m.item_id].unit if m.item_id in items else "",
             "quantity": m.quantity, "date": m.created_at, "to_user_name": names.get(m.to_user_id)}
            for m in stock
        ],
        "cost": cost,
    }


def _scope_agency(user: User, agency: Optional[str]) -> Optional[str]:
    return agency_scope(user, agency)


@stats_router.get("/sites-cost")
def sites_cost(agency: Optional[str] = None, include_closed: bool = True, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_manager)):
    scope = _scope_agency(current_user, agency)
    query = db.query(Site)
    if scope is not None:
        query = query.filter(Site.agency_number == scope)
    if not include_closed:
        query = query.filter(Site.status == "actif")
    out = []
    for s in query.order_by(Site.name):
        c = sites.site_cost(db, s)
        out.append({"id": s.id, "name": s.name, "status": s.status, "agency_number": s.agency_number, "days": c["days"], "cost": c["total"]})
    out.sort(key=lambda r: -r["cost"])
    return {"sites": out, "total": round(sum(r["cost"] for r in out), 2)}


def _overlap_seconds(loan: Loan, w_start: datetime, w_end: datetime) -> float:
    start = loan.checked_out_at or loan.start_datetime
    end = loan.actual_return_datetime or w_end
    s, e = max(start, w_start), min(end, w_end)
    return max(0.0, (e - s).total_seconds())


@stats_router.get("/utilization")
def utilization(days: int = 90, agency: Optional[str] = None, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_manager)):
    days = max(7, min(days, 730))
    now = utils.now()
    w_start = now - timedelta(days=days)
    scope = _scope_agency(current_user, agency)
    dormant_days = appsettings.get_int(db, "stats.dormant_days")
    saturated_pct = appsettings.get_float(db, "stats.saturated_pct")

    query = db.query(AgencyTool).filter(AgencyTool.status.notin_([AgencyToolStatus.hors_service, AgencyToolStatus.sorti_du_parc]))
    if scope is not None:
        query = query.filter(AgencyTool.agency_number == scope)
    tools = query.all()
    ids = [t.id for t in tools] or [0]
    loans = db.query(Loan).filter(Loan.tool_id.in_(ids), Loan.status.in_((LoanStatus.en_cours, LoanStatus.termine))).all()
    by_tool = {}
    for l in loans:
        by_tool.setdefault(l.tool_id, []).append(l)
    waits = {}
    for w in db.query(WaitlistEntry).filter(WaitlistEntry.tool_id.in_(ids), WaitlistEntry.created_at >= w_start):
        waits[w.tool_id] = waits.get(w.tool_id, 0) + 1

    rows = []
    window = days * 86400.0
    for t in tools:
        ls = by_tool.get(t.id, [])
        busy = sum(_overlap_seconds(l, w_start, now) for l in ls)
        in_window = sum(1 for l in ls if _overlap_seconds(l, w_start, now) > 0)
        last = max(((l.checked_out_at or l.start_datetime) for l in ls), default=None)
        util = round(min(100.0, busy / window * 100), 1)
        reference = last or t.created_at or now
        is_dormant = t.status == AgencyToolStatus.disponible and (now - reference).days >= dormant_days
        rows.append({
            "tool_id": t.id, "name": t.name, "type": t.type, "unique_code": t.unique_code, "status": t.status.value,
            "utilization_pct": util, "loans": in_window, "last_loan_at": last, "waitlist": waits.get(t.id, 0),
            "dormant": is_dormant, "saturated": util >= saturated_pct or waits.get(t.id, 0) > 0,
        })
    by_type = {}
    for r in rows:
        label = r["type"] or "Non renseigné"
        agg = by_type.setdefault(label, {"type": label, "tools": 0, "util_sum": 0.0, "loans": 0})
        agg["tools"] += 1
        agg["util_sum"] += r["utilization_pct"]
        agg["loans"] += r["loans"]
    type_rows = sorted(
        ({"type": a["type"], "tools": a["tools"], "avg_utilization_pct": round(a["util_sum"] / a["tools"], 1), "loans": a["loans"]} for a in by_type.values()),
        key=lambda a: -a["avg_utilization_pct"],
    )
    rows.sort(key=lambda r: -r["utilization_pct"])
    return {
        "window_days": days, "dormant_days": dormant_days, "saturated_pct": saturated_pct, "tools": rows, "by_type": type_rows,
        "dormant": [r for r in rows if r["dormant"]], "saturated": [r for r in rows if r["saturated"]],
        "average_utilization_pct": round(sum(r["utilization_pct"] for r in rows) / len(rows), 1) if rows else 0.0,
    }
