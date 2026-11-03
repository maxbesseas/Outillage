"""Phase 7 : amortissement, TCO, pertes et litiges, budgets, prévisions."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, finance, utils
from ..agencies import agency_scope
from ..auth import get_current_admin, get_current_manager
from ..database import get_db
from ..models import AgencyTool, AgencyToolStatus, User, UserRole
from ..models_p7 import Budget, DepreciationPolicy, LossRecord

router = APIRouter(prefix="/finance", tags=["finance"])
losses_router = APIRouter(prefix="/losses", tags=["pertes"])

LOSS_KINDS = ("vol", "perte", "casse", "litige")
INSURANCE = ("none", "declared", "accepted", "refused")
LITIGATION = ("none", "open", "closed")
BUDGET_WRITERS = (UserRole.admin, UserRole.directeur_agence)


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


def scope_agency(user: User, requested: Optional[str] = None) -> Optional[str]:
    return agency_scope(user, requested)


# ------------------------------------------------------------------ amortissement

class PolicyIn(BaseModel):
    type: Optional[str] = None
    years: float = Field(gt=0, le=50)
    residual_pct: float = Field(default=0, ge=0, le=100)


@router.get("/depreciation-policies")
def list_policies(db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    rows = db.query(DepreciationPolicy).order_by(DepreciationPolicy.type).all()
    return {
        "defaults": finance.policy_values(db, None, {}),
        "policies": [{"id": p.id, "type": p.type, "years": p.years, "residual_pct": p.residual_pct} for p in rows],
    }


@router.put("/depreciation-policies")
def upsert_policy(payload: PolicyIn, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    type_ = (payload.type or "").strip() or None
    row = db.query(DepreciationPolicy).filter(DepreciationPolicy.type == type_).first() if type_ else db.query(DepreciationPolicy).filter(DepreciationPolicy.type.is_(None)).first()
    if row is None:
        row = DepreciationPolicy(type=type_)
        db.add(row)
    row.years = payload.years
    row.residual_pct = payload.residual_pct
    row.updated_at = utils.now()
    db.flush()
    audit.record(db, "depreciation_policy_set", current_user.id, "depreciation_policy", row.id, request,
                 {"type": type_, "years": payload.years, "residual_pct": payload.residual_pct})
    db.commit()
    return {"id": row.id, "type": row.type, "years": row.years, "residual_pct": row.residual_pct}


@router.delete("/depreciation-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(policy_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    row = db.query(DepreciationPolicy).filter(DepreciationPolicy.id == policy_id).first()
    if row is None:
        _fail("Règle introuvable", status.HTTP_404_NOT_FOUND)
    audit.record(db, "depreciation_policy_deleted", current_user.id, "depreciation_policy", row.id, request, {"type": row.type})
    db.delete(row)
    db.commit()


@router.get("/assets")
def list_assets(agency: Optional[str] = None, type: Optional[str] = None, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_manager)):
    return finance.assets(db, scope_agency(current_user, agency), type)


@router.get("/tco")
def list_tco(agency: Optional[str] = None, limit: int = 100, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    rows = finance.tco(db, scope_agency(current_user, agency))
    return {"tools": rows[: max(1, min(limit, 1000))], "total_tco": round(sum(r["tco"] for r in rows), 2), "count": len(rows)}


# ------------------------------------------------------------------ budgets et prévisions

class BudgetIn(BaseModel):
    year: int = Field(ge=2000, le=2100)
    category: str
    amount: float = Field(ge=0)
    agency_number: Optional[str] = None


@router.get("/budgets")
def get_budgets(year: Optional[int] = None, agency: Optional[str] = None, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_manager)):
    return finance.budget_status(db, scope_agency(current_user, agency), year or utils.now().year)


@router.put("/budgets")
def set_budget(payload: BudgetIn, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    if current_user.role not in BUDGET_WRITERS:
        _fail("Seuls les directeurs d'agence et l'administrateur fixent les budgets", status.HTTP_403_FORBIDDEN)
    if payload.category not in finance.BUDGET_CATEGORIES:
        _fail("Catégorie de budget invalide")
    agency = scope_agency(current_user, payload.agency_number)
    row = db.query(Budget).filter(Budget.agency_number == agency, Budget.year == payload.year, Budget.category == payload.category).first()
    if row is None:
        row = Budget(agency_number=agency, year=payload.year, category=payload.category)
        db.add(row)
    row.amount = payload.amount
    row.updated_by_id = current_user.id
    row.updated_at = utils.now()
    db.flush()
    audit.record(db, "budget_set", current_user.id, "budget", row.id, request,
                 {"year": payload.year, "category": payload.category, "amount": payload.amount, "agency": agency})
    db.commit()
    return finance.budget_status(db, agency, payload.year)


@router.get("/forecast")
def get_forecast(months: int = 12, agency: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    return finance.forecast(db, scope_agency(current_user, agency), max(1, min(months, 60)))


# ------------------------------------------------------------------ pertes et litiges

class LossIn(BaseModel):
    tool_id: int
    kind: str
    occurred_at: Optional[datetime] = None
    responsible_id: Optional[int] = None
    site_id: Optional[int] = None
    circumstances: Optional[str] = Field(default=None, max_length=2000)
    declared_value: Optional[float] = Field(default=None, ge=0)
    police_report_ref: Optional[str] = Field(default=None, max_length=80)
    insurance_status: str = "none"
    insurance_ref: Optional[str] = Field(default=None, max_length=80)
    refunded_amount: float = Field(default=0, ge=0)
    litigation_status: str = "none"
    litigation_note: Optional[str] = Field(default=None, max_length=2000)


class LossPatch(BaseModel):
    responsible_id: Optional[int] = None
    circumstances: Optional[str] = Field(default=None, max_length=2000)
    declared_value: Optional[float] = Field(default=None, ge=0)
    police_report_ref: Optional[str] = Field(default=None, max_length=80)
    insurance_status: Optional[str] = None
    insurance_ref: Optional[str] = Field(default=None, max_length=80)
    refunded_amount: Optional[float] = Field(default=None, ge=0)
    litigation_status: Optional[str] = None
    litigation_note: Optional[str] = Field(default=None, max_length=2000)


def _loss_view(l: LossRecord, tools: dict, names: dict) -> dict:
    tool = tools.get(l.tool_id)
    return {
        "id": l.id, "tool_id": l.tool_id, "tool_name": tool.name if tool else "(supprimé)", "tool_code": tool.unique_code if tool else None,
        "agency_number": l.agency_number, "kind": l.kind, "occurred_at": l.occurred_at, "responsible_id": l.responsible_id,
        "responsible_name": names.get(l.responsible_id), "site_id": l.site_id, "circumstances": l.circumstances,
        "declared_value": l.declared_value, "police_report_ref": l.police_report_ref, "insurance_status": l.insurance_status,
        "insurance_ref": l.insurance_ref, "refunded_amount": l.refunded_amount, "net_loss": round(max(0.0, l.declared_value - l.refunded_amount), 2),
        "litigation_status": l.litigation_status, "litigation_note": l.litigation_note, "created_at": l.created_at,
    }


def _validate_loss_fields(kind=None, insurance=None, litigation=None):
    if kind is not None and kind not in LOSS_KINDS:
        _fail("Type de perte invalide")
    if insurance is not None and insurance not in INSURANCE:
        _fail("Statut d'assurance invalide")
    if litigation is not None and litigation not in LITIGATION:
        _fail("Statut de litige invalide")


def _check_responsible(db: Session, agency: Optional[str], responsible_id: Optional[int]):
    if responsible_id is None:
        return
    person = db.query(User).filter(User.id == responsible_id).first()
    if person is None or ((person.agency_number or None) != (agency or None) and person.role != UserRole.admin):
        _fail("Personne responsable introuvable dans cette agence")


@losses_router.get("")
def list_losses(kind: Optional[str] = None, agency: Optional[str] = None, year: Optional[int] = None, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_manager)):
    query = db.query(LossRecord)
    scope = scope_agency(current_user, agency)
    if scope is not None:
        query = query.filter(LossRecord.agency_number == scope)
    if kind:
        query = query.filter(LossRecord.kind == kind)
    if year:
        query = query.filter(LossRecord.occurred_at >= datetime(year, 1, 1), LossRecord.occurred_at < datetime(year + 1, 1, 1))
    rows = query.order_by(LossRecord.occurred_at.desc()).limit(1000).all()
    tools = {t.id: t for t in db.query(AgencyTool).filter(AgencyTool.id.in_([r.tool_id for r in rows] or [0]))}
    names = {u.id: u.full_name for u in db.query(User)}
    views = [_loss_view(r, tools, names) for r in rows]
    return {
        "records": views,
        "totals": {
            "count": len(views), "declared": round(sum(v["declared_value"] for v in views), 2),
            "refunded": round(sum(v["refunded_amount"] for v in views), 2), "net": round(sum(v["net_loss"] for v in views), 2),
            "open_litigations": sum(1 for v in views if v["litigation_status"] == "open"),
        },
    }


@losses_router.post("", status_code=status.HTTP_201_CREATED)
def add_loss(payload: LossIn, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    _validate_loss_fields(payload.kind, payload.insurance_status, payload.litigation_status)
    tool = db.query(AgencyTool).filter(AgencyTool.id == payload.tool_id).first()
    if tool is None:
        _fail("Outil introuvable", status.HTTP_404_NOT_FOUND)
    if current_user.role != UserRole.admin and tool.agency_number != current_user.agency_number:
        _fail("Cet outil appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    _check_responsible(db, tool.agency_number, payload.responsible_id)
    record = finance.create_loss_record(
        db, tool, payload.kind, current_user.id, payload.occurred_at, payload.circumstances,
        declared_value=payload.declared_value, responsible_id=payload.responsible_id, site_id=payload.site_id,
        police_report_ref=payload.police_report_ref, insurance_status=payload.insurance_status, insurance_ref=payload.insurance_ref,
        refunded_amount=payload.refunded_amount, litigation_status=payload.litigation_status, litigation_note=payload.litigation_note,
    )
    audit.record(db, "loss_recorded", current_user.id, "loss_record", record.id, request, {"tool_id": tool.id, "kind": payload.kind})
    db.commit()
    return _loss_view(record, {tool.id: tool}, {})


@losses_router.patch("/{loss_id}")
def update_loss(loss_id: int, payload: LossPatch, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    record = db.query(LossRecord).filter(LossRecord.id == loss_id).first()
    if record is None:
        _fail("Dossier introuvable", status.HTTP_404_NOT_FOUND)
    if current_user.role != UserRole.admin and record.agency_number != current_user.agency_number:
        _fail("Ce dossier appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    data = payload.model_dump(exclude_unset=True)
    _validate_loss_fields(None, data.get("insurance_status"), data.get("litigation_status"))
    if "responsible_id" in data:
        _check_responsible(db, record.agency_number, data["responsible_id"])
    for field, value in data.items():
        if field in ("declared_value", "refunded_amount") and value is None:
            continue
        setattr(record, field, value)
    record.updated_at = utils.now()
    audit.record(db, "loss_updated", current_user.id, "loss_record", record.id, request, {"fields": sorted(data.keys())})
    db.commit()
    tool = db.query(AgencyTool).filter(AgencyTool.id == record.tool_id).first()
    return _loss_view(record, {record.tool_id: tool} if tool else {}, {u.id: u.full_name for u in db.query(User)})
