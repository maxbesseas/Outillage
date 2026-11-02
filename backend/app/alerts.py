from datetime import datetime, timedelta
from typing import Callable, Dict, List

from sqlalchemy.orm import Session

from . import appsettings, notify, utils
from .models import (
    AgencyTool,
    AgencyToolStatus,
    Epi,
    Loan,
    LoanStatus,
    PeerTransfer,
    PeerTransferStatus,
    PersonalTool,
    Transfer,
    TransferStatus,
    User,
    UserRole,
)
from .models_ext import Notification

Generator = Callable[[Session, datetime], int]
GENERATORS: Dict[str, Generator] = {}


def generator(name: str):
    def decorate(func: Generator) -> Generator:
        GENERATORS[name] = func
        return func

    return decorate


def _user(db: Session, user_id):
    return db.query(User).filter(User.id == user_id).first() if user_id else None


def _bucket(days_left: int, thresholds: List[int]):
    """Plus petit seuil atteint (ex. 7 si reste 5 jours avec seuils 60/30/7)."""
    reached = [t for t in thresholds if days_left <= t]
    return min(reached) if reached else None


@generator("loan_overdue")
def loan_overdue(db: Session, now: datetime) -> int:
    escalation = appsettings.get_int(db, "alert.overdue_escalation_days")
    count = 0
    loans = db.query(Loan).filter(Loan.status == LoanStatus.en_cours, Loan.end_datetime_planned < now).all()
    for loan in loans:
        tool = db.query(AgencyTool).filter(AgencyTool.id == loan.tool_id).first()
        borrower = _user(db, loan.borrower_id)
        if tool is None or borrower is None:
            continue
        days = (now - loan.end_datetime_planned).days
        day_key = now.date().isoformat()
        title = f"Réservation en retard : {tool.name}"
        body = f"Retour prévu le {loan.end_datetime_planned:%d/%m/%Y %H:%M} ({days} jour(s) de retard)."
        if notify.create(db, borrower.id, "loan_overdue", title, body, entity_kind="loan", entity_id=loan.id,
                         link="#/reservations", dedup_key=f"loan_overdue:{loan.id}:{day_key}"):
            count += 1
        if days >= escalation:
            managers = notify.chain_managers(db, borrower)
            count += notify.create_many(
                db, managers, "loan_overdue", f"Retard de {borrower.full_name} : {tool.name}", body,
                entity_kind="loan", entity_id=loan.id, link="#/reservations",
                dedup_prefix=f"loan_overdue_esc:{loan.id}:{day_key}",
            )
    return count


@generator("loan_ending_soon")
def loan_ending_soon(db: Session, now: datetime) -> int:
    hours = appsettings.get_int(db, "alert.loan_reminder_hours")
    count = 0
    loans = (
        db.query(Loan)
        .filter(Loan.status == LoanStatus.en_cours, Loan.end_datetime_planned >= now,
                Loan.end_datetime_planned <= now + timedelta(hours=hours))
        .all()
    )
    for loan in loans:
        tool = db.query(AgencyTool).filter(AgencyTool.id == loan.tool_id).first()
        if tool and notify.create(
            db, loan.borrower_id, "loan_ending_soon", f"À rendre bientôt : {tool.name}",
            f"Fin prévue le {loan.end_datetime_planned:%d/%m/%Y %H:%M}.",
            entity_kind="loan", entity_id=loan.id, link="#/reservations", dedup_key=f"loan_soon:{loan.id}",
        ):
            count += 1
    return count


@generator("transfer_overdue")
def transfer_overdue(db: Session, now: datetime) -> int:
    escalation = appsettings.get_int(db, "alert.overdue_escalation_days")
    count = 0
    transfers = (
        db.query(Transfer)
        .filter(Transfer.status == TransferStatus.en_cours, Transfer.planned_return_date.isnot(None),
                Transfer.planned_return_date < now)
        .all()
    )
    for transfer in transfers:
        sender = _user(db, transfer.from_user_id)
        if sender is None:
            continue
        tool = db.query(PersonalTool).filter(PersonalTool.id == transfer.tool_id).first() if transfer.tool_id \
            else db.query(AgencyTool).filter(AgencyTool.id == transfer.agency_tool_id).first()
        name = tool.name if tool else "outil"
        days = (now - transfer.planned_return_date).days
        day_key = now.date().isoformat()
        title = f"Prêt externe en retard : {name}"
        body = f"Prêté à {transfer.to_external_name}, retour prévu le {transfer.planned_return_date:%d/%m/%Y}."
        if notify.create(db, sender.id, "transfer_overdue", title, body, entity_kind="transfer",
                         entity_id=transfer.id, link="#/transferts", dedup_key=f"transfer_overdue:{transfer.id}:{day_key}"):
            count += 1
        if days >= escalation:
            count += notify.create_many(
                db, notify.chain_managers(db, sender), "transfer_overdue", f"{title} ({sender.full_name})", body,
                entity_kind="transfer", entity_id=transfer.id, link="#/transferts",
                dedup_prefix=f"transfer_overdue_esc:{transfer.id}:{day_key}",
            )
    return count


@generator("peer_pending")
def peer_pending(db: Session, now: datetime) -> int:
    days = appsettings.get_int(db, "alert.peer_pending_days")
    count = 0
    pending = (
        db.query(PeerTransfer)
        .filter(PeerTransfer.status == PeerTransferStatus.en_attente,
                PeerTransfer.transfer_date < now - timedelta(days=days))
        .all()
    )
    for transfer in pending:
        other_id = transfer.to_user_id if transfer.declared_by_id == transfer.from_user_id else transfer.from_user_id
        tool = db.query(PersonalTool).filter(PersonalTool.id == transfer.tool_id).first()
        if notify.create(
            db, other_id, "peer_pending", f"Transfert à confirmer : {tool.name if tool else 'outil'}",
            "Une déclaration attend votre confirmation.", entity_kind="peer_transfer", entity_id=transfer.id,
            link="#/entre-collegues", dedup_key=f"peer_pending:{transfer.id}:{now.date().isoformat()}",
        ):
            count += 1
    return count


@generator("epi_expiring")
def epi_expiring(db: Session, now: datetime) -> int:
    thresholds = appsettings.get_int_list(db, "alert.epi_expiry_days")
    today = now.date()
    count = 0
    for epi in db.query(Epi).filter(Epi.expiration_date.isnot(None)).all():
        days_left = (epi.expiration_date.date() - today).days
        recipients: List[User] = []
        holder = _user(db, epi.assigned_to_id)
        if holder:
            recipients = [holder] + notify.chain_managers(db, holder)
        else:
            recipients = notify.agency_managers(db, epi.agency_number)
        if days_left < 0:
            count += notify.create_many(
                db, recipients, "epi_expired", f"EPI périmé : {epi.name}",
                f"{epi.name} ({epi.unique_code}) est périmé depuis le {epi.expiration_date:%d/%m/%Y}.",
                entity_kind="epi", entity_id=epi.id, link="#/epi", dedup_prefix=f"epi_expired:{epi.id}",
            )
            continue
        bucket = _bucket(days_left, thresholds)
        if bucket is not None:
            count += notify.create_many(
                db, recipients, "epi_expiring", f"EPI bientôt périmé : {epi.name}",
                f"{epi.name} ({epi.unique_code}) expire dans {days_left} jour(s).",
                entity_kind="epi", entity_id=epi.id, link="#/epi", dedup_prefix=f"epi_exp:{epi.id}:{bucket}",
            )
    return count


@generator("warranty_expiring")
def warranty_expiring(db: Session, now: datetime) -> int:
    thresholds = appsettings.get_int_list(db, "alert.warranty_days")
    today = now.date()
    count = 0
    tools = (
        db.query(AgencyTool)
        .filter(AgencyTool.warranty_expiration_date.isnot(None), AgencyTool.status != AgencyToolStatus.hors_service)
        .all()
    )
    for tool in tools:
        days_left = (tool.warranty_expiration_date.date() - today).days
        if days_left < 0:
            continue
        bucket = _bucket(days_left, thresholds)
        if bucket is None:
            continue
        count += notify.create_many(
            db, notify.agency_managers(db, tool.agency_number), "warranty_expiring",
            f"Garantie bientôt expirée : {tool.name}",
            f"{tool.name} ({tool.unique_code}) : garantie jusqu'au {tool.warranty_expiration_date:%d/%m/%Y} "
            f"({days_left} jour(s)). Pensez à un contrôle avant l'échéance.",
            entity_kind="agency", entity_id=tool.id, link="#/garanties",
            dedup_prefix=f"warranty:agency:{tool.id}:{bucket}",
        )
    return count


@generator("repair_long")
def repair_long(db: Session, now: datetime) -> int:
    days = appsettings.get_int(db, "alert.repair_days")
    week = now.isocalendar()
    count = 0
    tools = (
        db.query(AgencyTool)
        .filter(AgencyTool.status == AgencyToolStatus.reparation, AgencyTool.updated_at < now - timedelta(days=days))
        .all()
    )
    for tool in tools:
        count += notify.create_many(
            db, notify.agency_managers(db, tool.agency_number), "repair_long",
            f"En réparation depuis plus de {days} jours : {tool.name}",
            f"{tool.name} ({tool.unique_code}) est immobilisé.",
            entity_kind="agency", entity_id=tool.id, link="#/agence",
            dedup_prefix=f"repair:{tool.id}:{week[0]}-{week[1]}",
        )
    return count


def _control_counts(db: Session, agency: str) -> int:
    try:
        from . import controls

        return controls.count_due_for_agency(db, agency)
    except ImportError:
        return 0


@generator("weekly_summary")
def weekly_summary(db: Session, now: datetime) -> int:
    if now.weekday() != 0:
        return 0
    monday = now.date().isoformat()
    count = 0
    agencies = {a for (a,) in db.query(User.agency_number).filter(User.agency_number.isnot(None)).distinct()}
    for agency in sorted(agencies):
        overdue = (
            db.query(Loan).join(AgencyTool, Loan.tool_id == AgencyTool.id)
            .filter(AgencyTool.agency_number == agency, Loan.status == LoanStatus.en_cours,
                    Loan.end_datetime_planned < now).count()
        )
        epi_bad = (
            db.query(Epi)
            .filter(Epi.agency_number == agency, (Epi.state <= 2) | (Epi.expiration_date < now))
            .count()
        )
        immobilized = sum(
            t.purchase_price or 0
            for t in db.query(AgencyTool).filter(
                AgencyTool.agency_number == agency,
                AgencyTool.status.in_((AgencyToolStatus.reparation, AgencyToolStatus.hors_service)),
            )
        )
        controls_due = _control_counts(db, agency)
        body = (
            f"Agence {agency} : {overdue} retard(s), {controls_due} contrôle(s) à faire, "
            f"{epi_bad} EPI à remplacer ou périmé(s), {immobilized:.0f} € de matériel immobilisé."
        )
        count += notify.create_many(
            db, notify.agency_managers(db, agency), "weekly_summary", f"Résumé de la semaine — {agency}", body,
            link="#/", dedup_prefix=f"weekly:{agency}:{monday}",
        )
    return count


def run_all(db: Session, now: datetime = None) -> Dict[str, int]:
    now = now or utils.now()
    results = {}
    for name, func in GENERATORS.items():
        results[name] = func(db, now)
    return results


# ------------------------------------------------------------------ digest email

def _digest_html(name: str, items: List[Notification]) -> str:
    color = {"critical": "#b91c1c", "warning": "#b45309", "info": "#194196"}
    rows = "".join(
        f'<tr><td style="padding:6px 10px;border-bottom:1px solid #e5e7eb">'
        f'<strong style="color:{color.get(n.severity, "#194196")}">{_esc(n.title)}</strong><br>'
        f'<span style="color:#475569;font-size:13px">{_esc(n.body or "")}</span></td></tr>'
        for n in items
    )
    return (
        '<div style="font-family:Arial,sans-serif;max-width:560px">'
        '<div style="background:#194196;color:#fff;padding:12px 16px;font-size:16px">Fauché — Gestion Outillage</div>'
        f'<p>Bonjour {_esc(name)}, voici vos alertes :</p>'
        f'<table style="width:100%;border-collapse:collapse">{rows}</table>'
        '<p style="color:#64748b;font-size:12px">Réglez vos préférences dans « Mon profil ».</p></div>'
    )


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_digests(db: Session, now: datetime = None, force: bool = False) -> Dict[str, int]:
    from .notifications import send_email

    now = now or utils.now()
    result = {"emails": 0, "failed": 0}
    if not force:
        if now.hour != appsettings.get_int(db, "alert.digest_hour"):
            return result
        if appsettings.get(db, "digest.last_date") == now.date().isoformat():
            return result
        appsettings.set_value(db, "digest.last_date", now.date().isoformat())
        db.commit()

    user_ids = [
        uid for (uid,) in db.query(Notification.user_id)
        .filter(Notification.email_wanted.is_(True), Notification.emailed_at.is_(None)).distinct()
    ]
    for uid in user_ids:
        user = _user(db, uid)
        if user is None or not user.email or not user.is_active:
            continue
        items = (
            db.query(Notification)
            .filter(Notification.user_id == uid, Notification.email_wanted.is_(True), Notification.emailed_at.is_(None))
            .order_by(Notification.created_at)
            .all()
        )
        text = "\n".join(f"- {n.title}: {n.body or ''}" for n in items)
        ok, _ = send_email(
            db, user.email, f"Fauché — {len(items)} alerte(s)",
            f"Bonjour {user.full_name},\n\nVos alertes :\n{text}\n", html=_digest_html(user.full_name, items),
        )
        if ok:
            for n in items:
                n.emailed_at = now
            result["emails"] += 1
        else:
            result["failed"] += 1
    db.commit()
    return result


# ------------------------------------------------------------------ phase 2 : contrôles, étalonnage, habilitations

@generator("control_due")
def control_due(db: Session, now: datetime) -> int:
    from . import controls

    return controls.generate_control_alerts(db, now)


@generator("calibration_due")
def calibration_due(db: Session, now: datetime) -> int:
    from . import controls

    return controls.generate_calibration_alerts(db, now)


@generator("qualification_expiring")
def qualification_expiring(db: Session, now: datetime) -> int:
    from . import controls

    return controls.generate_qualification_alerts(db, now)
