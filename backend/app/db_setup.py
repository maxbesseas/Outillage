"""Prépare une base (tables, migrations, premier compte admin). À lancer une fois, puis après chaque nouvelle migration :
python -m app.db_setup   (depuis backend/, avec les variables de production)
"""
import os

os.environ["OUTILLAGE_AUTO_MIGRATE"] = "on"

from . import config, database, main, migrations  # noqa: E402,F401

if __name__ == "__main__":
    version = migrations.current_version(database.engine)
    print(f"Base prête ({database.engine.dialect.name}), schéma en version {version}.")
    if config.initial_admin_password() is None:
        print("Aucun mot de passe initial fourni (OUTILLAGE_ADMIN_PASSWORD) : aucun compte admin n'a été créé.")
