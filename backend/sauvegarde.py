"""Sauvegarde complète de la base et des fichiers du compartiment dans un zip, et restauration sur une base vide.

Sauvegarder, depuis backend/ :
    python sauvegarde.py --env C:\\chemin\\fauche-sauvegarde.env --dest C:\\chemin\\Sauvegardes [--garder 30]
Restaurer, sur une base préparée par python -m app.db_setup et sans aucune donnée :
    python sauvegarde.py --env ... --restaurer C:\\chemin\\fauche-20261103-123000.zip

Le fichier --env contient une variable par ligne : OUTILLAGE_DATABASE_URL (compte postgres, port 5432), OUTILLAGE_SECRET_KEY,
et si des fichiers existent OUTILLAGE_S3_BUCKET, OUTILLAGE_S3_ENDPOINT, OUTILLAGE_S3_REGION, OUTILLAGE_S3_ACCESS_KEY, OUTILLAGE_S3_SECRET_KEY.
Le zip contient toutes les données, comptes compris : il ne doit jamais rejoindre le dépôt.
"""
import argparse
import base64
import json
import os
import sys
import tempfile
import zipfile
from datetime import date, datetime
from enum import Enum
from pathlib import Path

# Compteurs et réponses rejouables : sans valeur après une restauration.
SKIPPED_TABLES = {"schema_migrations", "rate_events", "idempotency_keys"}


def _load_env(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip('"')


def _encode(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__b64__": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def backup(dest: Path, keep: int) -> Path:
    from sqlalchemy import select

    from app import database, storage, utils

    dest.mkdir(parents=True, exist_ok=True)
    moment = utils.now()
    final = dest / f"fauche-{moment:%Y%m%d-%H%M%S}.zip"
    partial = final.with_suffix(".partiel")
    counts, files = {}, 0
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive, database.engine.connect() as conn:
        for table in database.Base.metadata.sorted_tables:
            if table.name in SKIPPED_TABLES:
                continue
            rows = [{k: _encode(v) for k, v in row._mapping.items()} for row in conn.execute(select(table))]
            archive.writestr(f"base/{table.name}.json", json.dumps(rows, ensure_ascii=False))
            counts[table.name] = len(rows)
        if storage.enabled():
            client = storage._client()
            for key, _ in storage.list_files():
                archive.writestr(f"fichiers/{key}", client.get_object(Bucket=storage.config.S3_BUCKET, Key=key)["Body"].read())
                files += 1
        archive.writestr("manifest.json", json.dumps({"date": moment.isoformat(), "tables": counts, "fichiers": files}, ensure_ascii=False))
    partial.replace(final)
    for old in sorted(dest.glob("fauche-*.zip"), reverse=True)[max(keep, 1):]:
        old.unlink()
    print(f"Sauvegarde : {final.name}, {sum(counts.values())} ligne(s), {files} fichier(s), {final.stat().st_size // 1024} Ko")
    return final


def _decode(table, row: dict) -> dict:
    from sqlalchemy import Date, DateTime

    out = {}
    for key, value in row.items():
        column = table.columns[key]
        if isinstance(value, dict) and "__b64__" in value:
            value = base64.b64decode(value["__b64__"])
        elif value is not None and isinstance(column.type, DateTime):
            value = datetime.fromisoformat(value)
        elif value is not None and isinstance(column.type, Date):
            value = date.fromisoformat(value)
        out[key] = value
    return out


def restore(path: Path):
    from sqlalchemy import func, select, text

    from app import database, storage

    tables = [t for t in database.Base.metadata.sorted_tables if t.name not in SKIPPED_TABLES]
    with zipfile.ZipFile(path) as archive, database.engine.begin() as conn:
        filled = [t.name for t in tables if conn.execute(select(func.count()).select_from(t)).scalar()]
        if filled:
            raise SystemExit(f"La base cible contient déjà des données, rien n'a été écrit : {', '.join(filled[:6])}")
        manifest = json.loads(archive.read("manifest.json"))
        names = set(archive.namelist())
        for table in tables:
            entry = f"base/{table.name}.json"
            if entry not in names:
                continue
            rows = [_decode(table, r) for r in json.loads(archive.read(entry))]
            if not rows:
                continue
            # Une ligne peut désigner une autre ligne de la même table : le lien est rétabli une fois toutes les lignes écrites.
            own_links = [fk.parent.name for fk in table.foreign_keys if fk.column.table is table]
            links = [(r["id"], {c: r[c] for c in own_links if r.get(c) is not None}) for r in rows] if own_links else []
            conn.execute(table.insert(), [{**r, **{c: None for c in own_links}} for r in rows])
            for row_id, values in links:
                if values:
                    conn.execute(table.update().where(table.c.id == row_id).values(values))
            if conn.dialect.name == "postgresql" and "id" in table.columns:
                conn.execute(text("SELECT setval(pg_get_serial_sequence(:t, 'id'), :v)"), {"t": f"public.{table.name}", "v": max(r["id"] for r in rows)})
        files = [n for n in names if n.startswith("fichiers/")]
        if files and not storage.enabled():
            print("Attention : compartiment non configuré, les fichiers n'ont pas été restaurés.")
        elif files:
            for name in files:
                storage.put(name[len("fichiers/"):], archive.read(name))
    print(f"Restauration terminée : sauvegarde du {manifest['date']}, {sum(manifest['tables'].values())} ligne(s), {len(files)} fichier(s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env")
    parser.add_argument("--dest")
    parser.add_argument("--garder", type=int, default=30)
    parser.add_argument("--restaurer")
    args = parser.parse_args()
    if args.env:
        _load_env(args.env)
    os.environ.setdefault("OUTILLAGE_ENV", "prod")
    os.environ["OUTILLAGE_AUTO_MIGRATE"] = "off"
    os.environ["OUTILLAGE_SCHEDULER"] = "off"
    os.environ.setdefault("OUTILLAGE_UPLOAD_DIR", tempfile.gettempdir())
    os.environ.setdefault("OUTILLAGE_EXCEL_DIR", tempfile.gettempdir())

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from app import main as _app  # noqa: F401  charge tous les modèles

    if args.restaurer:
        restore(Path(args.restaurer))
    elif args.dest:
        backup(Path(args.dest), args.garder)
    else:
        parser.error("indiquez --dest ou --restaurer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
