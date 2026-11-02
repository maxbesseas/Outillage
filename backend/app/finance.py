"""Phase 7 : amortissement, coût total de possession, budgets et prévisions."""
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from . import appsettings, sites as sites_mod, utils
from .models import AgencyTool, AgencyToolStatus, Epi, Loan, LoanStatus
from .models_p5 import MaintenanceTicket
from .models_p7 import Budget, DepreciationPolicy, LossRecord

YEAR_DAYS = 365.25
BUDGET_CATEGORIES = ("achats", "reparations", "pertes")
ACTIVE_ASSET_EXCLUDED = (AgencyToolStatus.hors_service, AgencyToolStatus.sorti_du_parc)


def policies(db: Session) -> Dict[Optional[str], DepreciationPolicy]:
    return {p.type: p for p in db.query(DepreciationPolicy)}


def policy_values(db: Session, type_: Optional[str], cache: Optional[dict] = None) -> dict:
    cache = cache if cache is not None else policies(db)
    row = cache.get(type_) if type_ else None
    if row is None:
        row = cache.get(None)
    if row is not None:
        return {"years": row.years, "residual_pct": row.residual_pct, "source": "type" if row.type else "defaut"}
    return {
        "years": appsettings.get_float(db, "finance.depreciation_years"),
        "residual_pct": appsettings.get_float(db, "finance.residual_pct"),
        "source": "parametres",
    }


def asset_line(db: Session, tool: AgencyTool, cache: Optional[dict] = None, now: Optional[datetime] = None) -> dict:
    now = now or utils.now()
    pol = policy_values(db, tool.type, cache)
    price = tool.purchase_price or 0.0
    line = {
        "tool_id": tool.id, "name": tool.name, "type": tool.type, "unique_code": tool.unique_code,
        "agency_number": tool.agency_number, "purchase_date": tool.purchase_date, "purchase_price": price,
        "years": pol["years"], "residual_pct": pol["residual_pct"], "policy_source": pol["source"],
        "age_years": None, "accumulated": None, "book_value": None, "end_of_life": None,
        "fully_depreciated": False, "complete": bool(tool.purchase_date and price),
    }
    if not line["complete"] or pol["years"] <= 0:
        return line
    age = max(0.0, (now - tool.purchase_date).days / YEAR_DAYS)
    depreciable = price * (1 - pol["residual_pct"] / 100)
    accumulated = min(depreciable, depreciable * age / pol["years"])
    line.update({
        "age_years": round(age, 2), "accumulated": round(accumulated, 2), "book_value": round(price - accumulated, 2),
        "end_of_life": tool.purchase_date + timedelta(days=pol["years"] * YEAR_DAYS),
        "fully_depreciated": age >= pol["years"],
    })
    return line


def assets(db: Session, agency: Optional[str], type_: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    query = db.query(AgencyTool).filter(AgencyTool.status.notin_(ACTIVE_ASSET_EXCLUDED))
    if agency is not None:
        query = query.filter(AgencyTool.agency_number == agency)
    if type_:
        query = query.filter(AgencyTool.type == type_)
    cache = policies(db)
    lines = [asset_line(db, t, cache, now) for t in query.order_by(AgencyTool.name)]
    complete = [l for l in lines if l["book_value"] is not None]
    by_type: Dict[str, dict] = {}
    for l in complete:
        agg = by_type.setdefault(l["type"] or "Non renseigné", {"type": l["type"] or "Non renseigné", "count": 0, "acquisition": 0.0, "book_value": 0.0})
        agg["count"] += 1
        agg["acquisition"] = round(agg["acquisition"] + l["purchase_price"], 2)
        agg["book_value"] = round(agg["book_value"] + l["book_value"], 2)
    return {
        "lines": lines,
        "totals": {
            "count": len(lines), "incomplete": len(lines) - len(complete),
            "acquisition": round(sum(l["purchase_price"] for l in complete), 2),
            "accumulated": round(sum(l["accumulated"] for l in complete), 2),
            "book_value": round(sum(l["book_value"] for l in complete), 2),
            "fully_depreciated": sum(1 for l in complete if l["fully_depreciated"]),
        },
        "by_type": sorted(by_type.values(), key=lambda a: -a["book_value"]),
    }


def tco(db: Session, agency: Optional[str], now: Optional[datetime] = None) -> List[dict]:
    """Coût total de possession = achat + réparations réelles + coût d'usage facturé, net de la valeur de cession."""
    now = now or utils.now()
    query = db.query(AgencyTool)
    if agency is not None:
        query = query.filter(AgencyTool.agency_number == agency)
    tools = query.all()
    ids = [t.id for t in tools] or [0]
    repairs: Dict[int, float] = {}
    for tk in db.query(MaintenanceTicket).filter(MaintenanceTicket.tool_kind == "agency", MaintenanceTicket.tool_id.in_(ids)):
        repairs[tk.tool_id] = repairs.get(tk.tool_id, 0.0) + (tk.actual_cost or 0.0)
    days: Dict[int, int] = {}
    for loan in db.query(Loan).filter(Loan.tool_id.in_(ids), Loan.status.in_(sites_mod.COUNTED)):
        days[loan.tool_id] = days.get(loan.tool_id, 0) + sites_mod.loan_days(loan, now)
    out = []
    for t in tools:
        repair = round(repairs.get(t.id, 0.0), 2)
        used = days.get(t.id, 0)
        price = t.purchase_price or 0.0
        residual = t.residual_value or 0.0
        total = round(price + repair - residual, 2)
        out.append({
            "tool_id": t.id, "name": t.name, "type": t.type, "unique_code": t.unique_code, "status": t.status.value,
            "purchase_price": price, "repair_cost": repair, "residual_value": residual, "tco": total, "days_used": used,
            "cost_per_day_used": round(total / used, 2) if used else None,
        })
    out.sort(key=lambda r: -r["tco"])
    return out


def _year_bounds(year: int):
    return datetime(year, 1, 1), datetime(year + 1, 1, 1)


def budget_actuals(db: Session, agency: Optional[str], year: int) -> Dict[str, float]:
    start, end = _year_bounds(year)
    q = db.query(AgencyTool).filter(AgencyTool.purchase_date >= start, AgencyTool.purchase_date < end)
    if agency is not None:
        q = q.filter(AgencyTool.agency_number == agency)
    achats = sum(t.purchase_price or 0 for t in q)
    tq = db.query(MaintenanceTicket).filter(MaintenanceTicket.tool_kind == "agency", MaintenanceTicket.opened_at >= start, MaintenanceTicket.opened_at < end)
    if agency is not None:
        tq = tq.filter(MaintenanceTicket.agency_number == agency)
    reparations = sum(t.actual_cost or 0 for t in tq)
    lq = db.query(LossRecord).filter(LossRecord.occurred_at >= start, LossRecord.occurred_at < end)
    if agency is not None:
        lq = lq.filter(LossRecord.agency_number == agency)
    pertes = sum(max(0.0, (l.declared_value or 0) - (l.refunded_amount or 0)) for l in lq)
    return {"achats": round(achats, 2), "reparations": round(reparations, 2), "pertes": round(pertes, 2)}


def budget_status(db: Session, agency: Optional[str], year: int) -> dict:
    lines = db.query(Budget).filter(Budget.year == year)
    if agency is not None:
        lines = lines.filter(Budget.agency_number == agency)
    planned: Dict[str, float] = {c: 0.0 for c in BUDGET_CATEGORIES}
    for b in lines:
        planned[b.category] = planned.get(b.category, 0.0) + (b.amount or 0.0)
    actual = budget_actuals(db, agency, year)
    rows = []
    for c in BUDGET_CATEGORIES:
        rows.append({
            "category": c, "planned": round(planned[c], 2), "actual": actual[c], "remaining": round(planned[c] - actual[c], 2),
            "consumed_pct": round(actual[c] / planned[c] * 100, 1) if planned[c] else None,
        })
    return {"year": year, "rows": rows, "planned_total": round(sum(planned.values()), 2), "actual_total": round(sum(actual.values()), 2)}


def forecast(db: Session, agency: Optional[str], months: int, now: Optional[datetime] = None) -> dict:
    now = now or utils.now()
    horizon = now + timedelta(days=30.44 * months)
    cache = policies(db)
    query = db.query(AgencyTool).filter(AgencyTool.status.notin_(ACTIVE_ASSET_EXCLUDED))
    if agency is not None:
        query = query.filter(AgencyTool.agency_number == agency)
    replacements = []
    for t in query:
        line = asset_line(db, t, cache, now)
        if line["end_of_life"] is not None and line["end_of_life"] <= horizon:
            replacements.append({
                "tool_id": t.id, "name": t.name, "type": t.type, "end_of_life": line["end_of_life"],
                "overdue": line["end_of_life"] < now, "estimated_cost": line["purchase_price"],
            })
    replacements.sort(key=lambda r: r["end_of_life"])
    eq = db.query(Epi).filter(Epi.expiration_date.isnot(None), Epi.expiration_date <= horizon)
    if agency is not None:
        eq = eq.filter(Epi.agency_number == agency)
    epi_by_type: Dict[str, int] = {}
    for e in eq:
        label = e.type or "Non renseigné"
        epi_by_type[label] = epi_by_type.get(label, 0) + 1
    return {
        "months": months, "replacements": replacements,
        "replacements_total": round(sum(r["estimated_cost"] for r in replacements), 2),
        "epi_to_renew": [{"type": k, "count": v} for k, v in sorted(epi_by_type.items(), key=lambda kv: -kv[1])],
        "epi_total": sum(epi_by_type.values()),
    }


def create_loss_record(db: Session, tool: AgencyTool, kind: str, user_id: Optional[int], occurred_at: Optional[datetime] = None,
                       circumstances: Optional[str] = None, declared_value: Optional[float] = None, **extra) -> LossRecord:
    now = utils.now()
    record = LossRecord(
        tool_id=tool.id, agency_number=tool.agency_number, kind=kind, occurred_at=occurred_at or now, circumstances=circumstances,
        declared_value=declared_value if declared_value is not None else (tool.purchase_price or 0.0),
        created_by_id=user_id, created_at=now, updated_at=now, **extra,
    )
    db.add(record)
    db.flush()
    return record
