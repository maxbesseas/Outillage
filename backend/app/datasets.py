"""Jeux de données partagés par les exports (CSV/Excel) et l'API de rapports. Chaque jeu = (colonnes, lignes)."""
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from . import finance, sites as sites_mod
from .models import AgencyTool, Epi, Loan, User
from .models_p5 import MaintenanceTicket, StockItem
from .models_p6 import Site
from .models_p7 import Budget, LossRecord

Columns = "OrderedDict[str, str]"  # clé technique -> en-tête français


def _val(v):
    return getattr(v, "value", v)


def tools(db: Session, agency: Optional[str]) -> Tuple[OrderedDict, List[dict]]:
    cols = OrderedDict([
        ("id", "N°"), ("unique_code", "Code"), ("name", "Désignation"), ("type", "Type"), ("brand", "Marque"), ("agency_number", "Agence"),
        ("status", "Statut"), ("state", "État (0-5)"), ("serial_number", "N° de série"), ("purchase_date", "Date d'achat"),
        ("purchase_price", "Prix d'achat (€)"), ("warranty_expiration_date", "Fin de garantie"), ("last_control_date", "Dernier contrôle"),
        ("daily_rate", "Tarif journalier (€)"),
    ])
    q = db.query(AgencyTool)
    if agency is not None:
        q = q.filter(AgencyTool.agency_number == agency)
    return cols, [{k: _val(getattr(t, k)) for k in cols} for t in q.order_by(AgencyTool.id)]


def epi(db: Session, agency: Optional[str]):
    cols = OrderedDict([
        ("id", "N°"), ("unique_code", "Code"), ("name", "Désignation"), ("type", "Type"), ("brand", "Marque"), ("agency_number", "Agence"),
        ("state", "État (0-5)"), ("expiration_date", "Péremption"), ("last_control_date", "Dernier contrôle"),
    ])
    q = db.query(Epi)
    if agency is not None:
        q = q.filter(Epi.agency_number == agency)
    return cols, [{k: _val(getattr(t, k)) for k in cols} for t in q.order_by(Epi.id)]


def loans(db: Session, agency: Optional[str]):
    cols = OrderedDict([
        ("id", "N°"), ("tool_code", "Code outil"), ("tool_name", "Outil"), ("borrower", "Emprunteur"), ("site", "Chantier"),
        ("status", "Statut"), ("start_datetime", "Début"), ("end_datetime_planned", "Fin prévue"), ("actual_return_datetime", "Retour effectif"),
        ("state_before", "État départ"), ("state_after", "État retour"),
    ])
    q = db.query(Loan, AgencyTool).join(AgencyTool, AgencyTool.id == Loan.tool_id)
    if agency is not None:
        q = q.filter(AgencyTool.agency_number == agency)
    names = {u.id: u.full_name for u in db.query(User)}
    rows = []
    for l, t in q.order_by(Loan.id.desc()).limit(20000):
        rows.append({"id": l.id, "tool_code": t.unique_code, "tool_name": t.name, "borrower": names.get(l.borrower_id), "site": l.site,
                     "status": l.status.value, "start_datetime": l.start_datetime, "end_datetime_planned": l.end_datetime_planned,
                     "actual_return_datetime": l.actual_return_datetime, "state_before": l.state_before, "state_after": l.state_after})
    return cols, rows


def tickets(db: Session, agency: Optional[str]):
    cols = OrderedDict([
        ("id", "N°"), ("tool_kind", "Nature"), ("tool_name", "Outil"), ("category", "Catégorie"), ("severity", "Gravité"), ("status", "Statut"),
        ("opened_at", "Ouvert le"), ("closed_at", "Clos le"), ("provider", "Prestataire"), ("estimated_cost", "Coût estimé (€)"),
        ("actual_cost", "Coût réel (€)"), ("warranty_claim", "Garantie"), ("resolution", "Résolution"),
    ])
    from . import controls

    q = db.query(MaintenanceTicket)
    if agency is not None:
        q = q.filter(MaintenanceTicket.agency_number == agency)
    rows = []
    for t in q.order_by(MaintenanceTicket.id.desc()).limit(20000):
        tool = controls.get_tool(db, t.tool_kind, t.tool_id)
        rows.append({"id": t.id, "tool_kind": t.tool_kind, "tool_name": tool.name if tool else "(supprimé)", "category": t.category,
                     "severity": t.severity, "status": t.status, "opened_at": t.opened_at, "closed_at": t.closed_at, "provider": t.provider,
                     "estimated_cost": t.estimated_cost, "actual_cost": t.actual_cost, "warranty_claim": bool(t.warranty_claim), "resolution": t.resolution})
    return cols, rows


def losses(db: Session, agency: Optional[str]):
    cols = OrderedDict([
        ("id", "N°"), ("tool_code", "Code outil"), ("tool_name", "Outil"), ("kind", "Nature"), ("occurred_at", "Date"), ("responsible", "Responsable"),
        ("declared_value", "Valeur déclarée (€)"), ("refunded_amount", "Remboursé (€)"), ("net_loss", "Perte nette (€)"), ("police_report_ref", "Dépôt de plainte"),
        ("insurance_status", "Assurance"), ("insurance_ref", "Réf. assurance"), ("litigation_status", "Litige"), ("circumstances", "Circonstances"),
    ])
    q = db.query(LossRecord)
    if agency is not None:
        q = q.filter(LossRecord.agency_number == agency)
    names = {u.id: u.full_name for u in db.query(User)}
    rows = []
    for l in q.order_by(LossRecord.occurred_at.desc()):
        tool = db.query(AgencyTool).filter(AgencyTool.id == l.tool_id).first()
        rows.append({"id": l.id, "tool_code": tool.unique_code if tool else None, "tool_name": tool.name if tool else "(supprimé)", "kind": l.kind,
                     "occurred_at": l.occurred_at, "responsible": names.get(l.responsible_id), "declared_value": l.declared_value,
                     "refunded_amount": l.refunded_amount, "net_loss": round(max(0.0, l.declared_value - l.refunded_amount), 2),
                     "police_report_ref": l.police_report_ref, "insurance_status": l.insurance_status, "insurance_ref": l.insurance_ref,
                     "litigation_status": l.litigation_status, "circumstances": l.circumstances})
    return cols, rows


def assets(db: Session, agency: Optional[str]):
    cols = OrderedDict([
        ("unique_code", "Code"), ("name", "Désignation"), ("type", "Type"), ("agency_number", "Agence"), ("purchase_date", "Date d'achat"),
        ("purchase_price", "Valeur d'acquisition (€)"), ("years", "Durée d'amortissement (ans)"), ("residual_pct", "Résiduel (%)"),
        ("age_years", "Âge (ans)"), ("accumulated", "Amortissements cumulés (€)"), ("book_value", "Valeur nette comptable (€)"),
        ("end_of_life", "Fin d'amortissement"),
    ])
    return cols, [{k: l[k] for k in cols} for l in finance.assets(db, agency)["lines"]]


def tco(db: Session, agency: Optional[str]):
    cols = OrderedDict([
        ("unique_code", "Code"), ("name", "Désignation"), ("type", "Type"), ("purchase_price", "Achat (€)"), ("repair_cost", "Réparations (€)"),
        ("residual_value", "Valeur de cession (€)"), ("tco", "Coût total de possession (€)"), ("days_used", "Jours d'utilisation"),
        ("cost_per_day_used", "Coût par jour d'utilisation (€)"),
    ])
    return cols, [{k: r[k] for k in cols} for r in finance.tco(db, agency)]


def sites_cost(db: Session, agency: Optional[str]):
    cols = OrderedDict([("id", "N°"), ("name", "Chantier"), ("agency_number", "Agence"), ("client", "Client"), ("status", "Statut"),
                        ("days", "Jours-outils"), ("cost", "Coût d'usage (€)")])
    q = db.query(Site)
    if agency is not None:
        q = q.filter(Site.agency_number == agency)
    rows = []
    for s in q.order_by(Site.name):
        c = sites_mod.site_cost(db, s)
        rows.append({"id": s.id, "name": s.name, "agency_number": s.agency_number, "client": s.client, "status": s.status,
                     "days": c["days"], "cost": c["total"]})
    return cols, rows


def stock(db: Session, agency: Optional[str]):
    cols = OrderedDict([("id", "N°"), ("name", "Désignation"), ("reference", "Référence"), ("agency_number", "Agence"), ("unit", "Unité"),
                        ("quantity", "Quantité"), ("threshold", "Seuil"), ("location", "Emplacement")])
    q = db.query(StockItem).filter(StockItem.is_active.is_(True))
    if agency is not None:
        q = q.filter(StockItem.agency_number == agency)
    return cols, [{k: getattr(i, k) for k in cols} for i in q.order_by(StockItem.name)]


def budgets(db: Session, agency: Optional[str]):
    cols = OrderedDict([("year", "Année"), ("agency_number", "Agence"), ("category", "Catégorie"), ("amount", "Budget (€)")])
    q = db.query(Budget)
    if agency is not None:
        q = q.filter(Budget.agency_number == agency)
    return cols, [{k: getattr(b, k) for k in cols} for b in q.order_by(Budget.year.desc(), Budget.category)]


DATASETS: Dict[str, Tuple[str, Callable]] = {
    "tools": ("Outils", tools), "epi": ("EPI", epi), "loans": ("Réservations", loans), "tickets": ("Maintenance", tickets),
    "losses": ("Pertes", losses), "assets": ("Actifs", assets), "tco": ("TCO", tco), "sites-cost": ("Chantiers", sites_cost),
    "stock": ("Stock", stock), "budgets": ("Budgets", budgets),
}
WORKBOOK_ORDER = ["tools", "epi", "assets", "tco", "loans", "tickets", "losses", "sites-cost", "stock", "budgets"]
