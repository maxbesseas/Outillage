import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from . import config, utils


def _columns(conn: Connection, table: str) -> set:
    return {column["name"] for column in inspect(conn).get_columns(table)}


def _table_exists(conn: Connection, table: str) -> bool:
    return inspect(conn).has_table(table)


def _ddl(conn: Connection, ddl: str) -> str:
    """Les migrations sont écrites pour SQLite : équivalents PostgreSQL des types et valeurs par défaut."""
    if conn.dialect.name == "postgresql":
        return ddl.replace("DATETIME", "TIMESTAMP").replace("BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE")
    return ddl


def add_column_if_missing(conn: Connection, table: str, column: str, ddl: str):
    if not _table_exists(conn, table):
        return
    if column not in _columns(conn, table):
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {_ddl(conn, ddl)}"))


def create_index_if_missing(conn: Connection, name: str, table: str, columns: str):
    if _table_exists(conn, table):
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})"))


def m001_users_accounts(conn: Connection):
    add_column_if_missing(conn, "users", "email", "VARCHAR")
    add_column_if_missing(conn, "users", "phone", "VARCHAR")
    add_column_if_missing(conn, "users", "must_change_password", "BOOLEAN NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "users", "token_version", "INTEGER NOT NULL DEFAULT 0")


def m002_indexes(conn: Connection):
    create_index_if_missing(conn, "ix_state_history_tool", "state_history", "tool_kind, tool_id")
    create_index_if_missing(conn, "ix_loans_tool_status", "loans", "tool_id, status")
    create_index_if_missing(conn, "ix_loans_borrower", "loans", "borrower_id")
    create_index_if_missing(conn, "ix_loans_start", "loans", "start_datetime")
    create_index_if_missing(conn, "ix_agency_tools_status", "agency_tools", "status")
    create_index_if_missing(conn, "ix_agency_tools_type", "agency_tools", "type")
    create_index_if_missing(conn, "ix_epi_assigned_to", "epi", "assigned_to_id")


def m003_seed_agencies(conn: Connection):
    if not _table_exists(conn, "agencies"):
        return
    names = set()
    for table in ("users", "agency_tools", "epi"):
        if _table_exists(conn, table):
            for (value,) in conn.execute(
                text(f"SELECT DISTINCT agency_number FROM {table} WHERE agency_number IS NOT NULL AND agency_number != ''")
            ):
                names.add(value)
    existing = {row[0] for row in conn.execute(text("SELECT name FROM agencies"))}
    for name in sorted(names - existing):
        conn.execute(
            text("INSERT INTO agencies (name, is_active, created_at) VALUES (:n, :active, :d)"),
            {"n": name, "active": True, "d": utils.now()},
        )


def m004_flag_default_admin_password(conn: Connection):
    from .auth import verify_password

    row = conn.execute(
        text("SELECT id, hashed_password FROM users WHERE username = :u"),
        {"u": config.DEFAULT_ADMIN_USERNAME},
    ).fetchone()
    if row and verify_password(config.DEFAULT_ADMIN_PASSWORD, row[1]):
        conn.execute(text("UPDATE users SET must_change_password = :flag WHERE id = :i"), {"flag": True, "i": row[0]})


def m005_loans_phase4(conn: Connection):
    add_column_if_missing(conn, "loans", "series_id", "VARCHAR")
    add_column_if_missing(conn, "loans", "created_by_id", "INTEGER")
    add_column_if_missing(conn, "loans", "checked_out_at", "DATETIME")
    add_column_if_missing(conn, "loans", "approved_by_id", "INTEGER")
    add_column_if_missing(conn, "loans", "approval_comment", "TEXT")
    add_column_if_missing(conn, "loans", "signature_json", "TEXT")
    add_column_if_missing(conn, "loans", "signed_name", "VARCHAR")
    add_column_if_missing(conn, "loans", "signed_at", "DATETIME")
    add_column_if_missing(conn, "transfers", "to_external_email", "VARCHAR")
    add_column_if_missing(conn, "transfers", "to_external_phone", "VARCHAR")
    add_column_if_missing(conn, "transfers", "signature_json", "TEXT")
    add_column_if_missing(conn, "transfers", "signed_name", "VARCHAR")
    add_column_if_missing(conn, "transfers", "signed_at", "DATETIME")
    add_column_if_missing(conn, "agency_tools", "home_agency", "VARCHAR")
    add_column_if_missing(conn, "users", "calendar_token", "VARCHAR")
    create_index_if_missing(conn, "ix_loans_series", "loans", "series_id")
    if _table_exists(conn, "users"):
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_calendar_token ON users (calendar_token)"))


def m006_agency_tools_phase5(conn: Connection):
    add_column_if_missing(conn, "agency_tools", "exit_reason", "VARCHAR")
    add_column_if_missing(conn, "agency_tools", "exit_date", "DATETIME")
    add_column_if_missing(conn, "agency_tools", "exit_note", "TEXT")
    add_column_if_missing(conn, "agency_tools", "residual_value", "FLOAT")
    add_column_if_missing(conn, "agency_tools", "parent_tool_id", "INTEGER")


def m007_sites(conn: Connection):
    add_column_if_missing(conn, "loans", "site_id", "INTEGER")
    add_column_if_missing(conn, "stock_movements", "site_id", "INTEGER")
    add_column_if_missing(conn, "agency_tools", "daily_rate", "FLOAT")
    create_index_if_missing(conn, "ix_loans_site_id", "loans", "site_id")
    create_index_if_missing(conn, "ix_stock_movements_site_id", "stock_movements", "site_id")
    if not all(_table_exists(conn, t) for t in ("sites", "loans", "agency_tools")):
        return
    pairs = conn.execute(text(
        "SELECT DISTINCT a.agency_number, TRIM(l.site) FROM loans l JOIN agency_tools a ON a.id = l.tool_id "
        "WHERE l.site IS NOT NULL AND TRIM(l.site) <> '' AND l.site_id IS NULL"
    )).fetchall()
    now = utils.now().strftime("%Y-%m-%d %H:%M:%S")
    for agency, name in pairs:
        row = conn.execute(
            text("SELECT id FROM sites WHERE COALESCE(agency_number,'') = COALESCE(:a,'') AND lower(name) = lower(:n)"),
            {"a": agency, "n": name},
        ).fetchone()
        if row is None:
            active = conn.execute(text(
                "SELECT COUNT(*) FROM loans l JOIN agency_tools a ON a.id = l.tool_id WHERE TRIM(l.site) = :n "
                "AND COALESCE(a.agency_number,'') = COALESCE(:a,'') AND l.status IN ('reserve','en_cours','attente_validation')"
            ), {"a": agency, "n": name}).scalar()
            conn.execute(
                text("INSERT INTO sites (agency_number, name, status, created_at) VALUES (:a, :n, :s, :c)"),
                {"a": agency, "n": name, "s": "actif" if active else "clos", "c": now},
            )
            row = conn.execute(
                text("SELECT id FROM sites WHERE COALESCE(agency_number,'') = COALESCE(:a,'') AND lower(name) = lower(:n)"),
                {"a": agency, "n": name},
            ).fetchone()
        conn.execute(
            text("UPDATE loans SET site_id = :sid WHERE site_id IS NULL AND TRIM(site) = :n AND tool_id IN "
                 "(SELECT id FROM agency_tools WHERE COALESCE(agency_number,'') = COALESCE(:a,''))"),
            {"sid": row[0], "n": name, "a": agency},
        )


def m008_microsoft_login(conn: Connection):
    add_column_if_missing(conn, "users", "microsoft_tid", "VARCHAR")
    add_column_if_missing(conn, "users", "microsoft_oid", "VARCHAR")
    if _table_exists(conn, "users"):
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_users_microsoft ON users (microsoft_tid, microsoft_oid)"))


def m009_rate_events(conn: Connection):
    if not _table_exists(conn, "rate_events"):
        conn.execute(text(_ddl(conn, "CREATE TABLE rate_events (id INTEGER PRIMARY KEY, key VARCHAR(200) NOT NULL, amount INTEGER NOT NULL DEFAULT 1, created_at DATETIME NOT NULL)").replace("id INTEGER PRIMARY KEY", "id SERIAL PRIMARY KEY" if conn.dialect.name == "postgresql" else "id INTEGER PRIMARY KEY")))
    create_index_if_missing(conn, "ix_rate_events_key_created", "rate_events", "key, created_at")


def m010_mfa_and_charter(conn: Connection):
    add_column_if_missing(conn, "users", "totp_secret", "VARCHAR")
    add_column_if_missing(conn, "users", "totp_enabled", "BOOLEAN NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "users", "totp_last_step", "INTEGER")
    add_column_if_missing(conn, "users", "charter_version", "INTEGER NOT NULL DEFAULT 0")


MIGRATIONS: List[Tuple[int, str, Callable[[Connection], None]]] = [
    (1, "users: email, phone, must_change_password, token_version", m001_users_accounts),
    (2, "index de performance", m002_indexes),
    (3, "agences existantes vers la table agencies", m003_seed_agencies),
    (4, "admin au mot de passe par défaut : changement obligatoire", m004_flag_default_admin_password),
    (5, "réservations : séries, signature, validation ; agences ; agenda", m005_loans_phase4),
    (6, "outils d'agence : sortie de parc et composition", m006_agency_tools_phase5),
    (7, "chantiers : table sites, rattachement des réservations et du stock, tarif journalier", m007_sites),
    (8, "connexion Microsoft : identité liée au compte", m008_microsoft_login),
    (9, "compteurs anti-abus partagés", m009_rate_events),
    (10, "double authentification et acceptation de la charte", m010_mfa_and_charter),
]


def _ensure_table(conn: Connection):
    # Le rôle applicatif ne peut pas créer de table : on ne le tente que si elle manque.
    if _table_exists(conn, "schema_migrations"):
        return
    conn.execute(
        text(_ddl(conn,
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, description VARCHAR, applied_at DATETIME)"
        ))
    )


def applied_versions(engine: Engine) -> set:
    with engine.begin() as conn:
        _ensure_table(conn)
        return {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}


def current_version(engine: Engine) -> int:
    versions = applied_versions(engine)
    return max(versions) if versions else 0


def backup_database(engine: Engine, backup_dir: Path, label: str) -> Optional[Path]:
    if engine.dialect.name != "sqlite":
        return None  # PostgreSQL : sauvegardes assurées par l'hébergeur de la base
    db_file = engine.url.database
    if not db_file or db_file == ":memory:" or not Path(db_file).exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"outillage_{stamp}_{label}.db"
    source = sqlite3.connect(db_file)
    try:
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return target


def _has_user_data(engine: Engine) -> bool:
    with engine.begin() as conn:
        if not _table_exists(conn, "users"):
            return False
        return conn.execute(text("SELECT COUNT(*) FROM users")).scalar() > 0


def run_migrations(engine: Engine, backup_dir: Optional[Path] = None) -> List[int]:
    done = applied_versions(engine)
    pending = [m for m in MIGRATIONS if m[0] not in done]
    if not pending:
        return []

    if _has_user_data(engine):
        backup_database(engine, backup_dir or config.BACKUP_DIR, f"avant-migration-v{pending[-1][0]}")

    applied = []
    for version, description, func in pending:
        with engine.begin() as conn:
            func(conn)
            conn.execute(
                text("INSERT INTO schema_migrations (version, description, applied_at) VALUES (:v, :d, :a)"),
                {"v": version, "d": description, "a": utils.now()},
            )
        applied.append(version)
    return applied
