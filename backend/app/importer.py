"""Phase 8 : moteur d'import (Excel/CSV) avec correspondance de colonnes, simulation et rapport.

La simulation exécute exactement le même code que la validation réelle, puis annule la transaction : ce que l'on voit
en simulation est ce que l'on obtient à la validation.
"""
import csv
import io
import re
import secrets
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy.orm import Session

from . import utils
from .agencies import require_agency
from .auth import generate_temporary_password
from .history import log_state_change
from .models import AgencyTool, AgencyToolStatus, Epi, ToolKind, User, UserRole

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000
STATE_LABELS = {"neuf": 5, "bon": 4, "a verifier": 3, "mauvais": 2, "defectueux": 1, "hors service": 0}

# cible -> champ -> (libellé, alias d'en-têtes normalisés)
TARGETS: Dict[str, Dict[str, Tuple[str, List[str]]]] = {
    "agency_tools": {
        "unique_code": ("Code unique", ["reference", "code", "code unique", "id materiel", "n inventaire", "code outil"]),
        "name": ("Désignation", ["nom", "designation", "libelle", "materiel", "outil"]),
        "type": ("Type", ["type", "categorie", "famille"]),
        "brand": ("Marque / modèle", ["modele", "marque", "brand"]),
        "description": ("Description", ["description"]),
        "serial_number": ("N° de série", ["n de serie", "numero de serie", "serie", "serial"]),
        "purchase_date": ("Date d'achat", ["date d achat", "achat", "date achat"]),
        "purchase_price": ("Prix d'achat", ["prix d achat", "prix", "montant", "valeur"]),
        "warranty_expiration_date": ("Fin de garantie", ["date d expiration de la garantie", "fin de garantie", "garantie"]),
        "state": ("État (0-5 ou libellé)", ["etat du materiel", "etat"]),
        "comment": ("Commentaire", ["commentaire", "remarque", "observations"]),
        "daily_rate": ("Tarif journalier", ["tarif journalier", "tarif"]),
    },
    "epi": {
        "unique_code": ("Code unique", ["reference", "code", "code unique", "id materiel", "code epi"]),
        "name": ("Désignation", ["nom", "designation", "libelle", "epi"]),
        "type": ("Type", ["type", "categorie", "famille"]),
        "brand": ("Marque / modèle", ["modele", "marque"]),
        "expiration_date": ("Date de péremption", ["peremption", "date de peremption", "date d expiration", "expiration", "validite"]),
        "state": ("État (0-5 ou libellé)", ["etat du materiel", "etat"]),
        "comment": ("Commentaire", ["commentaire", "remarque", "observations"]),
    },
    "users": {
        "username": ("Identifiant", ["identifiant", "login", "username", "utilisateur"]),
        "full_name": ("Nom complet", ["nom complet", "nom", "salarie", "collaborateur"]),
        "role": ("Rôle", ["role", "fonction", "poste"]),
        "email": ("Email", ["email", "mail", "courriel"]),
        "phone": ("Téléphone", ["telephone", "tel", "mobile", "portable"]),
        "agency_number": ("Agence", ["agence"]),
        "password": ("Mot de passe (vide = temporaire généré)", ["mot de passe", "password"]),
    },
}
REQUIRED = {"agency_tools": ["unique_code", "name"], "epi": ["unique_code", "name"], "users": ["username", "full_name"]}
ROLE_ALIASES = {
    "gars_chantier": ["gars chantier", "gars_chantier", "personnel de chantier", "chantier", "ouvrier"],
    "charge_affaires": ["charge affaires", "charge_affaires", "charge d affaires", "chef de chantier"],
    "directeur_agence": ["directeur agence", "directeur_agence", "directeur d agence", "directeur"],
    "magasinier": ["magasinier", "magasin"],
}


def normalize(text: Any) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip()


class ImportFileError(Exception):
    pass


# ------------------------------------------------------------------ lecture des fichiers

def read_table(content: bytes, filename: str, sheet: Optional[str] = None) -> Tuple[List[str], List[List[Any]], List[str], str]:
    """Renvoie (en-têtes, lignes, feuilles disponibles, feuille utilisée)."""
    if len(content) > MAX_BYTES:
        raise ImportFileError(f"Fichier trop volumineux (maximum {MAX_BYTES // (1024 * 1024)} Mo)")
    name = (filename or "").lower()
    if name.endswith(".csv") or name.endswith(".txt"):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("cp1252", errors="replace")
        sample = text[:4096]
        delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        rows = [list(r) for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
        sheets, used = ["CSV"], "CSV"
    elif name.endswith(".xlsx") or name.endswith(".xlsm"):
        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except Exception:
            raise ImportFileError("Fichier Excel illisible (format .xlsx attendu)")
        sheets = list(wb.sheetnames)
        used = sheet if sheet in sheets else sheets[0]
        rows = [list(r) for r in wb[used].iter_rows(values_only=True)]
    else:
        raise ImportFileError("Format non pris en charge (.xlsx ou .csv)")
    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        raise ImportFileError("Le fichier est vide")
    if len(rows) - 1 > MAX_ROWS:
        raise ImportFileError(f"Trop de lignes (maximum {MAX_ROWS})")
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    return headers, rows[1:], sheets, used


def suggest_mapping(headers: List[str], target: str) -> Dict[str, Optional[int]]:
    norm = [normalize(h) for h in headers]
    mapping: Dict[str, Optional[int]] = {}
    taken = set()
    for field, (_, aliases) in TARGETS[target].items():
        found = None
        for alias in aliases:  # égalité exacte d'abord, puis inclusion
            for i, h in enumerate(norm):
                if i not in taken and h == alias:
                    found = i
                    break
            if found is not None:
                break
        if found is None:
            for alias in aliases:
                for i, h in enumerate(norm):
                    if i not in taken and h and (alias in h.split() or (len(alias) > 4 and alias in h)):
                        found = i
                        break
                if found is not None:
                    break
        mapping[field] = found
        if found is not None:
            taken.add(found)
    return mapping


# ------------------------------------------------------------------ conversion des valeurs

def parse_date(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"date illisible « {text} »")


def parse_number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d,.\-]", "", str(value).replace(" ", "").replace(" ", "")).replace(",", ".")
    if text.count(".") > 1:
        text = text.replace(".", "", text.count(".") - 1)
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"nombre illisible « {value} »")


def parse_state(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = int(value)
    else:
        text = normalize(value)
        label = re.sub(r"\s*\d+$", "", text).strip()
        if label in STATE_LABELS:
            return STATE_LABELS[label]
        try:
            n = int(float(text.replace(",", ".")))
        except ValueError:
            raise ValueError(f"état illisible « {value} » (0 à 5 ou Neuf, Bon, Mauvais…)")
    if not 0 <= n <= 5:
        raise ValueError("l'état doit être compris entre 0 et 5")
    return n


def parse_role(value: Any) -> Optional[UserRole]:
    if value in (None, ""):
        return None
    text = normalize(value)
    for role, aliases in ROLE_ALIASES.items():
        if text in [normalize(a) for a in aliases] or text == normalize(role):
            return UserRole(role)
    raise ValueError(f"rôle inconnu « {value} »")


def _text(value: Any, limit: int = 250) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()[:limit] or None


def cell(row: List[Any], mapping: Dict[str, Optional[int]], field: str) -> Any:
    idx = mapping.get(field)
    if idx is None or idx >= len(row):
        return None
    return row[idx]


# ------------------------------------------------------------------ traitement

class RowResult(dict):
    pass


def _row_result(n: int, action: str, label: str, errors=None, warnings=None) -> RowResult:
    return RowResult(row=n, action=action, label=label, errors=errors or [], warnings=warnings or [])


def _tool_values(target: str, row, mapping) -> Tuple[dict, List[str]]:
    errors, data = [], {}
    getters = {
        "unique_code": lambda v: _text(v, 60), "name": lambda v: _text(v, 160), "type": lambda v: _text(v, 80),
        "brand": lambda v: _text(v, 80), "description": lambda v: _text(v, 500), "serial_number": lambda v: _text(v, 80),
        "comment": lambda v: _text(v, 500), "state": parse_state, "purchase_date": parse_date,
        "warranty_expiration_date": parse_date, "expiration_date": parse_date, "purchase_price": parse_number, "daily_rate": parse_number,
    }
    for field in TARGETS[target]:
        if mapping.get(field) is None:
            continue
        raw = cell(row, mapping, field)
        try:
            value = getters[field](raw)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if field in ("purchase_price", "daily_rate") and value is not None and value < 0:
            errors.append(f"{TARGETS[target][field][0]} : la valeur ne peut pas être négative")
            continue
        if raw not in (None, ""):
            data[field] = value
    return data, errors


def _import_tools(db: Session, user: User, target: str, rows, mapping, agency: Optional[str], update_existing: bool) -> List[RowResult]:
    model = AgencyTool if target == "agency_tools" else Epi
    kind = ToolKind.agency if target == "agency_tools" else ToolKind.epi
    seen: Dict[str, int] = {}
    results: List[RowResult] = []
    for offset, row in enumerate(rows):
        n = offset + 2
        data, errors = _tool_values(target, row, mapping)
        code, name = data.get("unique_code"), data.get("name")
        label = f"{code or '?'} — {name or '?'}"
        if not code:
            errors.append("code unique manquant")
        elif "~SORTI" in code:
            errors.append("code réservé (sortie de parc)")
        if not name and not (code and update_existing and db.query(model).filter(model.unique_code == code).first()):
            errors.append("désignation manquante")
        if code and code in seen:
            errors.append(f"doublon dans le fichier (déjà en ligne {seen[code]})")
        elif code:
            seen[code] = n
        if errors:
            results.append(_row_result(n, "error", label, errors))
            continue

        existing = db.query(model).filter(model.unique_code == code).first()
        if existing is not None:
            if existing.agency_number != agency:
                results.append(_row_result(n, "error", label, ["ce code appartient à une autre agence"]))
                continue
            if not update_existing:
                results.append(_row_result(n, "skip", label, warnings=["code déjà présent : ligne ignorée"]))
                continue
            changed = {k: v for k, v in data.items() if k != "unique_code" and getattr(existing, k, None) != v}
            if "state" in changed and model is AgencyTool:
                from .excel_export import _state_label

                raw_state = cell(row, mapping, "state")
                if isinstance(raw_state, str) and normalize(raw_state) == normalize(_state_label(existing.status, existing.state)):
                    changed.pop("state")  # le libellé Excel est plus grossier que l'état 0-5 : ne pas l'écraser
            if not changed:
                results.append(_row_result(n, "skip", label, warnings=["aucune modification"]))
                continue
            old_state = existing.state
            for k, v in changed.items():
                setattr(existing, k, v)
            if "state" in changed:
                status_val = getattr(getattr(existing, "status", None), "value", None)
                log_state_change(db, kind, existing.id, old_state, existing.state, status_val, status_val, user.id, "import")
            results.append(_row_result(n, "update", label, warnings=[f"modifié : {', '.join(sorted(changed))}"]))
            continue

        values = dict(data)
        values.setdefault("state", 5)
        if model is AgencyTool:
            values.setdefault("purchase_price", 0.0)
        else:
            values.pop("purchase_price", None)
            values.pop("daily_rate", None)
        obj = model(agency_number=agency, **{k: v for k, v in values.items() if hasattr(model, k)})
        db.add(obj)
        db.flush()
        status_val = obj.status.value if hasattr(obj, "status") and obj.status is not None else None
        log_state_change(db, kind, obj.id, None, obj.state, None, status_val, user.id, "import")
        results.append(_row_result(n, "create", label))
    return results


def _import_users(db: Session, user: User, rows, mapping, agency: Optional[str], credentials: List[dict]) -> List[RowResult]:
    from .routers.users import build_user  # import tardif : évite une dépendance circulaire
    from . import schemas

    results: List[RowResult] = []
    seen: Dict[str, int] = {}
    for offset, row in enumerate(rows):
        n = offset + 2
        errors: List[str] = []
        username = _text(cell(row, mapping, "username"), 60)
        full_name = _text(cell(row, mapping, "full_name"), 120)
        label = f"{username or '?'} — {full_name or '?'}"
        role = None
        try:
            role = parse_role(cell(row, mapping, "role"))
        except ValueError as exc:
            errors.append(str(exc))
        if not username:
            errors.append("identifiant manquant")
        if not full_name:
            errors.append("nom complet manquant")
        if username and username.lower() in seen:
            errors.append(f"doublon dans le fichier (déjà en ligne {seen[username.lower()]})")
        elif username:
            seen[username.lower()] = n
        if errors:
            results.append(_row_result(n, "error", label, errors))
            continue

        password = _text(cell(row, mapping, "password"), 100)
        generated = password is None
        password = password or generate_temporary_password()
        if role is None:
            from .hierarchy import CHILD_ROLE

            role = CHILD_ROLE.get(user.role)
            if role is None:
                results.append(_row_result(n, "error", label, ["rôle à préciser"]))
                continue
        try:
            payload = schemas.UserCreate(
                username=username, full_name=full_name, role=role, password=password,
                email=_text(cell(row, mapping, "email"), 120), phone=_text(cell(row, mapping, "phone"), 30),
                agency_number=(_text(cell(row, mapping, "agency_number"), 60) or agency) if user.role == UserRole.admin else None,
            )
        except Exception:
            results.append(_row_result(n, "error", label, ["email ou données invalides"]))
            continue
        try:
            build_user(db, user, payload, None, must_change_password=True)  # valide avant d'écrire : aucune écriture partielle
        except HTTPException as exc:
            results.append(_row_result(n, "error", label, [str(exc.detail)]))
            continue
        if generated:
            credentials.append({"username": username, "temporary_password": password})
        results.append(_row_result(n, "create", label, warnings=["mot de passe temporaire généré"] if generated else []))
    return results


def run_import(db: Session, user: User, target: str, content: bytes, filename: str, mapping: Dict[str, Optional[int]], *,
               mode: str, sheet: Optional[str] = None, update_existing: bool = False, skip_errors: bool = False,
               agency_number: Optional[str] = None) -> dict:
    if target not in TARGETS:
        raise ImportFileError("Type d'import inconnu")
    if mode not in ("simulate", "commit"):
        raise ImportFileError("Mode invalide")
    if target == "users" and user.role not in (UserRole.admin, UserRole.directeur_agence):
        raise PermissionError("L'import d'utilisateurs est réservé à l'administrateur et aux directeurs d'agence")
    if user.role == UserRole.gars_chantier:
        raise PermissionError("Réservé aux gestionnaires")

    headers, rows, _, _ = read_table(content, filename, sheet)
    mapping = {k: v for k, v in mapping.items() if k in TARGETS[target] and isinstance(v, int) and 0 <= v < len(headers)}
    missing = [TARGETS[target][f][0] for f in REQUIRED[target] if f not in mapping]
    if missing:
        raise ImportFileError("Colonnes obligatoires non associées : " + ", ".join(missing))

    agency = user.agency_number if user.role != UserRole.admin else (require_agency(db, agency_number) if agency_number else None)
    if target != "users" and agency is None:
        raise ImportFileError("Choisissez l'agence de destination")

    credentials: List[dict] = []
    try:
        if target == "users":
            results = _import_users(db, user, rows, mapping, agency, credentials)
        else:
            results = _import_tools(db, user, target, rows, mapping, agency, update_existing)
        counts = {a: sum(1 for r in results if r["action"] == a) for a in ("create", "update", "skip", "error")}
        if mode == "commit" and counts["error"] and not skip_errors:
            db.rollback()
            raise ImportFileError(f"{counts['error']} ligne(s) en erreur : corrigez le fichier ou choisissez d'ignorer les lignes en erreur")
        if mode == "commit":
            db.flush()
        else:
            db.rollback()
            credentials = []
    except Exception:
        db.rollback()
        raise
    return {"target": target, "mode": mode, "agency_number": agency, "total": len(results), "counts": counts, "rows": results,
            "credentials": credentials if mode == "commit" else []}
