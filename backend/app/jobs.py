import threading
from datetime import timedelta
from typing import Callable, Dict, NamedTuple, Optional

from sqlalchemy.orm import Session

from . import database, utils
from .models import JobRun, LoginAttempt, PasswordResetToken, RefreshToken

STALE_RUNNING_MINUTES = 15
TICK_SECONDS = 30


class Job(NamedTuple):
    description: str
    interval_seconds: int
    func: Callable[[Session], str]


def purge_login_attempts(db: Session) -> str:
    limit = utils.now() - timedelta(days=30)
    count = db.query(LoginAttempt).filter(LoginAttempt.created_at < limit).delete(synchronize_session=False)
    return f"{count} tentative(s) de connexion supprimée(s)"


def purge_idempotency(db: Session) -> str:
    from .idempotency import purge_old

    return f"{purge_old(db)} clé(s) supprimée(s)"


def purge_expired_tokens(db: Session) -> str:
    now = utils.now()
    refresh_count = (
        db.query(RefreshToken)
        .filter(
            (RefreshToken.expires_at < now - timedelta(days=7))
            | (RefreshToken.revoked_at.isnot(None) & (RefreshToken.revoked_at < now - timedelta(days=30)))
        )
        .delete(synchronize_session=False)
    )
    reset_count = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.expires_at < now - timedelta(days=7))
        .delete(synchronize_session=False)
    )
    return f"{refresh_count} jeton(s) de session et {reset_count} jeton(s) de réinitialisation supprimé(s)"


def generate_alerts(db: Session) -> str:
    from . import alerts

    results = alerts.run_all(db)
    return ", ".join(f"{k}={v}" for k, v in results.items() if v) or "aucune nouvelle alerte"


def send_digests(db: Session) -> str:
    from . import alerts

    result = alerts.send_digests(db)
    return f"{result['emails']} email(s) envoyé(s), {result['failed']} échec(s)"


def expire_no_shows(db: Session) -> str:
    from . import reservations

    return f"{reservations.expire_no_shows(db)} réservation(s) non retirée(s) annulée(s)"


def process_waitlists(db: Session) -> str:
    from . import reservations

    return f"{reservations.expire_offers(db)} offre(s) de liste d'attente expirée(s)"


def retry_excel_sync(db: Session) -> str:
    from . import excel_export

    done, failed = excel_export.retry_pending(db)
    return f"{done} mise(s) à jour Excel rejouée(s), {failed} abandonnée(s)"


def backup_daily(db: Session) -> str:
    from . import backups

    return backups.daily_backup(db)


def cleanup_orphan_uploads(db: Session) -> str:
    from . import uploads_cleanup

    return uploads_cleanup.cleanup_orphan_uploads(db)


JOBS: Dict[str, Job] = {
    "expire_no_shows": Job("Annulation des réservations non retirées", 600, expire_no_shows),
    "process_waitlists": Job("Expiration des offres de liste d'attente", 300, process_waitlists),
    "generate_alerts": Job("Génération des alertes et rappels", 3600, generate_alerts),
    "send_digests": Job("Envoi du digest email quotidien", 3600, send_digests),
    "purge_login_attempts": Job("Purge des tentatives de connexion de plus de 30 jours", 86400, purge_login_attempts),
    "purge_expired_tokens": Job("Purge des jetons de session et de réinitialisation expirés", 86400, purge_expired_tokens),
    "retry_excel_sync": Job("Reprise des mises à jour Excel en attente (fichier verrouillé)", 300, retry_excel_sync),
    "backup_daily": Job("Sauvegarde quotidienne de la base et des fichiers", 3600, backup_daily),
    "cleanup_orphan_uploads": Job("Purge des fichiers orphelins du dossier uploads", 86400, cleanup_orphan_uploads),
    "purge_idempotency": Job("Purge des clés d'idempotence de plus de 7 jours", 86400, purge_idempotency),
}


def _close_stale_runs(db: Session):
    limit = utils.now() - timedelta(minutes=STALE_RUNNING_MINUTES)
    stale = db.query(JobRun).filter(JobRun.status == "running", JobRun.started_at < limit).all()
    for run in stale:
        run.status = "error"
        run.finished_at = utils.now()
        run.message = "Interrompue (aucune fin enregistrée)"
    if stale:
        db.commit()


def run_job(name: str, trigger: str = "scheduler") -> dict:
    job = JOBS.get(name)
    if job is None:
        raise KeyError(name)

    db = database.SessionLocal()
    try:
        _close_stale_runs(db)
        if db.query(JobRun).filter(JobRun.name == name, JobRun.status == "running").first():
            return {"name": name, "status": "skipped", "message": "Déjà en cours d'exécution"}

        run = JobRun(name=name, trigger=trigger, started_at=utils.now(), status="running")
        db.add(run)
        db.commit()
        run_id = run.id

        try:
            message = job.func(db)
            db.commit()
            status = "ok"
        except Exception as exc:
            db.rollback()
            status, message = "error", str(exc)[:500]

        run = db.query(JobRun).filter(JobRun.id == run_id).first()
        run.status = status
        run.message = message
        run.finished_at = utils.now()
        db.commit()
        return {"name": name, "status": status, "message": message}
    finally:
        db.close()


def list_jobs(db: Session) -> list:
    result = []
    for name, job in JOBS.items():
        last = db.query(JobRun).filter(JobRun.name == name).order_by(JobRun.id.desc()).first()
        result.append(
            {
                "name": name,
                "description": job.description,
                "interval_seconds": job.interval_seconds,
                "last_started_at": last.started_at if last else None,
                "last_finished_at": last.finished_at if last else None,
                "last_status": last.status if last else None,
                "last_message": last.message if last else None,
            }
        )
    return result


def _due(name: str, job: Job) -> bool:
    db = database.SessionLocal()
    try:
        last = db.query(JobRun).filter(JobRun.name == name).order_by(JobRun.id.desc()).first()
        if last is None:
            return True
        return (utils.now() - last.started_at).total_seconds() >= job.interval_seconds
    finally:
        db.close()


def run_due(trigger: str) -> list:
    results = []
    for name, job in JOBS.items():
        try:
            if _due(name, job):
                results.append(run_job(name, trigger))
        except Exception:
            pass
    return results


class Scheduler:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _loop(self):
        while not self._stop.wait(TICK_SECONDS):
            run_due("scheduler")

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="outillage-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())


scheduler = Scheduler()
