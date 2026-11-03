import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session
from starlette.types import Scope

from . import alerts_p5, config, database, file_access, limits, migrations, models_security, storage, models_ext, models_p2, models_p3, models_p4, models_p5, models_p6, models_p7, models_p8, models_p9  # noqa: F401
from .auth import hash_password, user_from_file_cookie
from .config import DEFAULT_ADMIN_USERNAME, FRONTEND_DIR, UPLOAD_DIR
from .idempotency import idempotency_middleware
from .jobs import scheduler
from .models import User, UserRole
from .routers import (
    charter as charter_router,
    microsoft,
    admin,
    agencies,
    agency_tools,
    agency_transfers,
    calendar_feed,
    departure,
    planning,
    transfers_docs,
    assistant,
    auth,
    backups_gdpr,
    epi,
    exports,
    finance,
    imports,
    inspections,
    loans,
    maintenance,
    notifications,
    peer_transfers,
    personal_tools,
    settings,
    sites,
    state_history,
    terrain,
    transfers,
    users,
)
from .security import apply_security_headers
from .tzmiddleware import NaiveUtcMiddleware

config.validate_startup()


def create_default_admin():
    password = config.initial_admin_password()
    if password is None:
        return
    db = database.SessionLocal()
    try:
        if not db.query(User).filter(User.username == DEFAULT_ADMIN_USERNAME).first():
            admin_user = User(
                username=DEFAULT_ADMIN_USERNAME,
                hashed_password=hash_password(password),
                full_name="Administrateur",
                role=UserRole.admin,
                must_change_password=True,
            )
            db.add(admin_user)
            db.commit()
    finally:
        db.close()


if config.AUTO_MIGRATE:
    database.Base.metadata.create_all(bind=database.engine)
    migrations.run_migrations(database.engine)
    create_default_admin()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.SCHEDULER_ENABLED:
        scheduler.start()
    yield
    scheduler.stop()


docs_enabled = not config.IS_PROD

app = FastAPI(
    title="FAUCHÉ — Gestion Outillage",
    lifespan=lifespan,
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
    openapi_url="/openapi.json" if docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS if config.IS_PROD else ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Idempotent-Replay", "X-Excel-Sync", "X-Notification", "X-Total-Count", "X-Auth-Error", "Content-Disposition", "Retry-After"],
)


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, exc: IntegrityError):
    text_error = str(exc.orig).lower()
    duplicate = "unique" in text_error or "duplicate" in text_error
    detail = "Cette valeur existe déjà : choisissez-en une autre." if duplicate else "Opération impossible : des données y sont encore liées."
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": detail})


@app.exception_handler(OverflowError)
@app.exception_handler(DataError)
async def value_out_of_range(request: Request, exc: Exception):
    """Un identifiant trop grand pour la base ne désigne aucun élément."""
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "Élément introuvable"})


app.middleware("http")(idempotency_middleware)
app.middleware("http")(limits.limits_middleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    return apply_security_headers(response, request)


app.add_middleware(NaiveUtcMiddleware)


@app.get("/uploads/{path:path}", include_in_schema=False)
def uploaded_file(path: str, request: Request, db: Session = Depends(database.get_db)):
    user = user_from_file_cookie(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Connexion requise")
    if not file_access.can_read(db, user, f"/uploads/{path}"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier introuvable")
    if storage.enabled():
        return RedirectResponse(storage.presigned_url(path), status_code=status.HTTP_307_TEMPORARY_REDIRECT, headers={"Cache-Control": "no-store"})
    local = (UPLOAD_DIR / path).resolve()
    if not local.is_relative_to(UPLOAD_DIR.resolve()) or not local.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fichier introuvable")
    return FileResponse(local, headers={"Cache-Control": "private, no-store"})


app.include_router(auth.router)
app.include_router(charter_router.router)
app.include_router(microsoft.router)
app.include_router(users.router)
app.include_router(agencies.router)
app.include_router(personal_tools.router)
app.include_router(agency_tools.router)
app.include_router(loans.router)
app.include_router(transfers.router)
app.include_router(peer_transfers.router)
app.include_router(epi.router)
app.include_router(settings.router)
app.include_router(state_history.router)
app.include_router(assistant.router)
app.include_router(admin.audit_router)
app.include_router(admin.jobs_router)
app.include_router(admin.cron_router)
app.include_router(inspections.policies_router)
app.include_router(inspections.templates_router)
app.include_router(inspections.router)
app.include_router(inspections.calibrations_router)
app.include_router(inspections.qualification_types_router)
app.include_router(inspections.qualifications_router)
app.include_router(inspections.requirements_router)
app.include_router(planning.kits_router)
app.include_router(planning.waitlist_router)
app.include_router(planning.blackouts_router)
app.include_router(planning.rules_router)
app.include_router(agency_transfers.router)
app.include_router(calendar_feed.router)
app.include_router(departure.router)
app.include_router(transfers_docs.router)
app.include_router(maintenance.tickets_router)
app.include_router(maintenance.accessories_router)
app.include_router(maintenance.exit_router)
app.include_router(maintenance.stock_router)
app.include_router(imports.router)
app.include_router(backups_gdpr.backups_router)
app.include_router(backups_gdpr.excel_router)
app.include_router(backups_gdpr.gdpr_router)
app.include_router(finance.router)
app.include_router(finance.losses_router)
app.include_router(exports.router)
app.include_router(exports.keys_router)
app.include_router(exports.reports_router)
app.include_router(sites.router)
app.include_router(sites.stats_router)
app.include_router(terrain.router)
app.include_router(terrain.photos_router)
app.include_router(terrain.search_router)
app.include_router(notifications.router)
app.include_router(notifications.push_router)
app.include_router(notifications.dashboard_router)
app.include_router(notifications.app_settings_router)


@app.get("/health")
def health():
    return {"status": "ok", "version": config.VERSION}


@app.get("/health/ready")
def health_ready():
    """Vérifie que la base est accessible et que le schéma est à jour ; utilisable comme readiness probe."""
    checks = {}
    try:
        db = database.SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        finally:
            db.close()
    except Exception as exc:
        checks["database"] = f"error: {exc.__class__.__name__}"

    expected = len(migrations.MIGRATIONS)
    applied = len(migrations.applied_versions(database.engine))
    checks["migrations"] = "ok" if applied >= expected else f"pending ({applied}/{expected})"
    checks["scheduler"] = "on" if scheduler.is_running() else ("disabled" if not config.SCHEDULER_ENABLED else "not_running")

    ready = checks["database"] == "ok" and checks["migrations"] == "ok"
    return Response(
        content=json.dumps({"status": "ready" if ready else "not_ready", "version": config.VERSION, "checks": checks}),
        media_type="application/json",
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", NoCacheStaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
