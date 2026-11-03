"""Copie les données métier de la base SQLite locale vers PostgreSQL. Ne modifie jamais la base SQLite.

Usage, depuis backend/, base cible préparée par python -m app.db_setup :
    OUTILLAGE_DATABASE_URL=... python migrate_to_postgres.py [chemin/vers/outillage.db]

Ne sont pas repris : comptes, jetons, clés d'API, journaux, messages de l'assistant et notifications.
Les références à un ancien compte sont rattachées à l'admin de la base cible. Refuse d'écrire dans une base déjà remplie.
"""
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, inspect, select, text

from app import config, database, models, models_ext, models_p2, models_p3, models_p4, models_p5, models_p6, models_p7, models_p8, models_p9  # noqa: F401

EXCLUDED = {
    "users", "refresh_tokens", "password_reset_tokens", "login_attempts", "audit_log", "job_runs", "schema_migrations",
    "idempotency_keys", "api_keys", "push_subscriptions", "notifications", "notification_preferences",
    "assistant_actions", "assistant_messages", "assistant_usage", "rate_events", "charter_acceptances",
}


def _user_columns(table) -> set:
    return {fk.parent.name for fk in table.foreign_keys if fk.column.table.name == "users"}


def main() -> int:
    source_path = Path(sys.argv[1] if len(sys.argv) > 1 else config.DB_PATH).resolve()
    if not source_path.exists():
        print(f"Base source introuvable : {source_path}")
        return 1
    target = database.engine
    if target.dialect.name != "postgresql":
        print("La cible doit être PostgreSQL : définissez OUTILLAGE_DATABASE_URL.")
        return 1
    source = create_engine(f"sqlite:///file:{source_path.as_posix()}?mode=ro&uri=true")
    tables = [t for t in database.Base.metadata.sorted_tables if t.name not in EXCLUDED]

    with source.connect() as src, target.begin() as dst:
        admin_id = dst.execute(text("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")).scalar()
        if admin_id is None:
            print("Aucun admin dans la base cible : lancez d'abord python -m app.db_setup avec OUTILLAGE_ADMIN_PASSWORD.")
            return 1
        filled = [t.name for t in tables if dst.execute(select(func.count()).select_from(t)).scalar()]
        if filled:
            print(f"Base cible déjà remplie, rien n'a été écrit : {', '.join(filled)}")
            return 1

        existing = set(inspect(src).get_table_names())
        for table in tables:
            if table.name not in existing:
                continue
            rows = [dict(r._mapping) for r in src.execute(select(table).order_by(*table.primary_key.columns))]
            if not rows:
                continue
            for row in rows:
                for column in _user_columns(table):
                    if row[column] is not None:
                        row[column] = admin_id
            dst.execute(table.insert(), rows)
            copied = dst.execute(select(func.count()).select_from(table)).scalar()
            if copied != len(rows):
                raise RuntimeError(f"Volumes différents pour {table.name} : {copied}/{len(rows)}")
            print(f"{table.name} : {copied}/{len(rows)}")
            if "id" in table.columns:
                dst.execute(text("SELECT setval(pg_get_serial_sequence(:t, 'id'), :v)"), {"t": table.name, "v": max(r["id"] for r in rows)})
    print("Migration terminée.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
