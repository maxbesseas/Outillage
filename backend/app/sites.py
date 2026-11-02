"""Chantiers : calculs de coût et rattachement des réservations."""
import math
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import appsettings, utils
from .models import AgencyTool, Loan, LoanStatus, User, UserRole
from .models_p6 import Site

COUNTED = (LoanStatus.en_cours, LoanStatus.termine)


def resolve_for_loan(db: Session, tool: AgencyTool, site_id: Optional[int]) -> Optional[Site]:
    if site_id is None:
        return None
    site = db.query(Site).filter(Site.id == site_id).first()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chantier introuvable")
    if (site.agency_number or None) != (tool.agency_number or None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce chantier appartient à une autre agence")
    if site.status != "actif":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce chantier est clos")
    return site


def daily_rate(db: Session, tool: AgencyTool, default: Optional[float] = None) -> float:
    if tool.daily_rate is not None:
        return tool.daily_rate
    return default if default is not None else appsettings.get_float(db, "cost.default_daily_rate")


def loan_days(loan: Loan, now: Optional[datetime] = None) -> int:
    """Jours facturables (tout jour entamé compte) d'une sortie effective ; 0 si l'outil n'est jamais sorti."""
    if loan.status not in COUNTED:
        return 0
    now = now or utils.now()
    start = loan.checked_out_at or loan.start_datetime
    end = loan.actual_return_datetime or now
    if end < start:
        return 0
    return max(1, math.ceil((end - start).total_seconds() / 86400))


def site_cost(db: Session, site: Site, now: Optional[datetime] = None) -> dict:
    default = appsettings.get_float(db, "cost.default_daily_rate")
    loans = db.query(Loan).filter(Loan.site_id == site.id, Loan.status.in_(COUNTED)).all()
    tools = {t.id: t for t in db.query(AgencyTool).filter(AgencyTool.id.in_([l.tool_id for l in loans] or [0]))}
    lines, total = {}, 0.0
    for loan in loans:
        tool = tools.get(loan.tool_id)
        if tool is None:
            continue
        days = loan_days(loan, now)
        rate = daily_rate(db, tool, default)
        entry = lines.setdefault(tool.id, {"tool_id": tool.id, "tool_name": tool.name, "type": tool.type, "days": 0, "rate": rate, "cost": 0.0})
        entry["days"] += days
        entry["cost"] = round(entry["days"] * rate, 2)
    for entry in lines.values():
        total += entry["cost"]
    return {"total": round(total, 2), "days": sum(l["days"] for l in lines.values()),
            "lines": sorted(lines.values(), key=lambda l: -l["cost"])}


def can_see(user: User, site: Site) -> bool:
    return user.role == UserRole.admin or (site.agency_number or None) == (user.agency_number or None)
