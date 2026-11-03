from typing import Any, Dict, List

from sqlalchemy.orm import Session

from .models_ext import AppSetting

# clé -> (valeur par défaut, description). Les valeurs sont stockées en texte.
DEFAULTS: Dict[str, tuple] = {
    "alert.overdue_escalation_days": ("2", "Jours de retard avant d'alerter le responsable et le directeur"),
    "alert.loan_reminder_hours": ("24", "Heures avant la fin d'une réservation pour rappeler à l'emprunteur"),
    "alert.epi_expiry_days": ("60,30,7", "Jours avant péremption d'un EPI pour alerter (séparés par des virgules)"),
    "alert.warranty_days": ("90,30", "Jours avant fin de garantie pour alerter les managers"),
    "alert.peer_pending_days": ("2", "Jours avant de relancer un transfert entre collègues non confirmé"),
    "alert.repair_days": ("14", "Jours en réparation avant d'alerter le magasinier et les managers"),
    "alert.digest_hour": ("7", "Heure (UTC) d'envoi du digest email quotidien"),
    "inspection.default_periodicity_days": ("365", "Périodicité de contrôle par défaut, à valider par le responsable sécurité"),
    "inspection.default_warn_days": ("30", "Jours avant l'échéance de contrôle pour prévenir, à valider par le responsable sécurité"),
    "inspection.nonconform_status": ("reparation", "Statut appliqué à un outil dont un point obligatoire est non conforme (reparation ou hors_service)"),
    "calibration.block_reservation": ("false", "Interdire la réservation d'un instrument dont l'étalonnage est échu (sinon simple avertissement)"),
    "qualification.block": ("false", "Interdire la réservation sans habilitation valide requise (sinon simple avertissement)"),
    "loan.no_show_hours": ("4", "Heures après le début d'une réservation non retirée avant annulation automatique"),
    "loan.max_days_default": ("90", "Durée maximale de réservation par défaut, en jours (365 au plus dans tous les cas)"),
    "loan.waitlist_offer_hours": ("24", "Durée de validité d'une offre de liste d'attente"),
    "photo.required_on_bad_return": ("false", "Photo obligatoire au retour d'un outil rendu en état 1 ou moins"),
    "photo.required_on_nonconform": ("false", "Photo obligatoire pour un contrôle non conforme"),
    "photo.max_px": ("1600", "Taille maximale (px) des photos après compression côté client"),
    "photo.quality": ("0.8", "Qualité JPEG des photos compressées (0 à 1)"),
    "exit.requires_approval": ("true", "Une sortie de parc proposée par un manager doit être validée par un directeur ou l'administrateur"),
    "exit.release_code": ("true", "Libérer le code unique d'un outil sorti du parc"),
    "site.code_pattern": (r"\d{6}", "Format obligatoire du code de chantier (expression régulière ; vide = aucun contrôle)"),
    "cost.default_daily_rate": ("0", "Forfait d'usage journalier par défaut (euros), utilisé pour un outil sans tarif propre"),
    "excel.sync_mode": ("create", "Synchronisation vers les classeurs Excel d'agence : create (nouveaux outils seulement) ou full (créations, modifications et sorties de parc)"),
    "backup.keep": ("14", "Nombre de sauvegardes automatiques conservées"),
    "backup.hour": ("2", "Heure (UTC) de la sauvegarde automatique quotidienne"),
    "finance.depreciation_years": ("5", "Durée d'amortissement linéaire par défaut (années), à valider par la comptabilité"),
    "finance.residual_pct": ("0", "Valeur résiduelle par défaut (% du prix d'achat), à valider par la comptabilité"),
    "stats.dormant_days": ("90", "Jours sans sortie au-delà desquels un outil disponible est dit dormant, à valider par le responsable"),
    "stats.saturated_pct": ("80", "Taux d'utilisation (%) à partir duquel un outil est dit saturé, à valider par le responsable"),
    "retention.audit_days": ("365", "Durée de conservation du journal d'audit et des adresses IP (jours), à valider par le responsable du traitement"),
    "retention.assistant_days": ("180", "Durée de conservation des échanges avec l'assistant (jours)"),
    "retention.notification_days": ("180", "Durée de conservation des notifications (jours)"),
    "charter.creator": ("le créateur de l'application", "Nom du créateur de l'application, affiché dans la charte"),
    "charter.controller": ("Fauché", "Responsable du traitement des données, affiché dans la charte"),
    "charter.contact": ("", "Contact pour exercer les droits sur les données, affiché dans la charte"),
    "assistant.daily_token_cap": ("200000", "Plafond de tokens par jour et par utilisateur pour l'assistant"),
    "assistant.rate_per_minute": ("10", "Nombre de messages par minute et par utilisateur pour l'assistant"),
}


def get(db: Session, key: str) -> str:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is not None and row.value is not None:
        return row.value
    return DEFAULTS[key][0] if key in DEFAULTS else ""


def get_int(db: Session, key: str) -> int:
    try:
        return int(float(get(db, key)))
    except ValueError:
        return int(float(DEFAULTS[key][0]))


def get_float(db: Session, key: str) -> float:
    try:
        return float(get(db, key))
    except ValueError:
        return float(DEFAULTS[key][0])


def get_bool(db: Session, key: str) -> bool:
    return get(db, key).strip().lower() in ("1", "true", "oui", "yes", "on")


def get_int_list(db: Session, key: str) -> List[int]:
    values = []
    for part in get(db, key).split(","):
        part = part.strip()
        if part.isdigit():
            values.append(int(part))
    return sorted(values, reverse=True)


def set_value(db: Session, key: str, value: Any):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    text = str(value).lower() if isinstance(value, bool) else str(value)
    if row is None:
        db.add(AppSetting(key=key, value=text))
    else:
        row.value = text


def all_settings(db: Session) -> list:
    return [
        {"key": key, "value": get(db, key), "default": default, "description": description}
        for key, (default, description) in DEFAULTS.items()
    ]
