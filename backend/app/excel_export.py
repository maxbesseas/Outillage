import json
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional, Tuple

from openpyxl import Workbook, load_workbook

from .config import EXCEL_SOURCE_DIR, EXCEL_SYNC_ENABLED
from .models import AgencyTool, AgencyToolStatus
from .utils import safe_text

COLUMNS = [
    "ID MATERIEL ",
    "REFERENCE",
    "NOM",
    "DESCRIPTION",
    "MODELE",
    "TYPE",
    "N° DE SERIE",
    "DATE D'ACHAT",
    "PRIX D'ACHAT",
    "DATE D'EXPIRATION DE LA GARANTIE",
    "STATUT GARANTIE",
    "ETAT DU MATERIEL",
    "COMMENTAIRE",
]

DATE_FORMAT = "DD/MM/YYYY"


def _state_label(status, state) -> str:
    if status == AgencyToolStatus.hors_service:
        return "Défectueux 5"
    if status == AgencyToolStatus.reparation:
        return "A vérifier 4"
    mapping = {5: "Neuf 1", 4: "Bon 2", 3: "Bon 2", 2: "Mauvais 3", 1: "Défectueux 5"}
    return mapping.get(state, "A vérifier 4")


def _warranty_status(warranty_expiration_date) -> str:
    if not warranty_expiration_date:
        return ""
    if warranty_expiration_date < datetime.utcnow():
        return "Garantie expirée"
    return "Sous garantie"


def _find_workbook_path(agency_number: str, registry_name=None):
    for key in (registry_name, agency_number):
        if not key:
            continue
        for candidate in EXCEL_SOURCE_DIR.glob(f"*{key}*.xlsx"):
            if candidate.name.startswith("~$"):
                continue
            return candidate
    return None


def sync_new_agency_tool(tool: AgencyTool, registry_name=None) -> Tuple[bool, str]:
    path = _find_workbook_path(tool.agency_number, registry_name)
    if path is None:
        return False, f"Fichier Excel introuvable pour l'agence {tool.agency_number}"

    try:
        wb = load_workbook(path)
        ws = wb.active

        row_number = ws.max_row + 1
        mat_id = f"MAT{row_number - 1:03d}"

        ws.cell(row=row_number, column=1, value=mat_id)
        ws.cell(row=row_number, column=2, value=tool.unique_code)
        ws.cell(row=row_number, column=3, value=tool.name)
        ws.cell(row=row_number, column=4, value=tool.description)
        ws.cell(row=row_number, column=5, value=tool.brand)
        ws.cell(row=row_number, column=6, value=tool.type)
        ws.cell(row=row_number, column=7, value=tool.serial_number)

        purchase_cell = ws.cell(row=row_number, column=8, value=tool.purchase_date)
        if tool.purchase_date:
            purchase_cell.number_format = DATE_FORMAT

        ws.cell(row=row_number, column=9, value=tool.purchase_price)

        warranty_cell = ws.cell(row=row_number, column=10, value=tool.warranty_expiration_date)
        if tool.warranty_expiration_date:
            warranty_cell.number_format = DATE_FORMAT

        ws.cell(row=row_number, column=11, value=_warranty_status(tool.warranty_expiration_date))
        ws.cell(row=row_number, column=12, value=_state_label(tool.status, tool.state))
        ws.cell(row=row_number, column=13, value=tool.comment)

        wb.save(path)
        return True, "ok"
    except Exception as exc:
        return False, f"Échec synchro Excel : {exc}"


def export_agency_tools_workbook(tools: Iterable[AgencyTool]) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.append(COLUMNS)

    for idx, tool in enumerate(tools, start=1):
        mat_id = f"MAT{idx:03d}"
        row = [
            mat_id,
            tool.unique_code,
            tool.name,
            tool.description,
            tool.brand,
            tool.type,
            tool.serial_number,
            tool.purchase_date,
            tool.purchase_price,
            tool.warranty_expiration_date,
            _warranty_status(tool.warranty_expiration_date),
            _state_label(tool.status, tool.state),
            tool.comment,
        ]
        ws.append([safe_text(v) for v in row])
        row_number = idx + 1
        if tool.purchase_date:
            ws.cell(row=row_number, column=8).number_format = DATE_FORMAT
        if tool.warranty_expiration_date:
            ws.cell(row=row_number, column=10).number_format = DATE_FORMAT

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------- Phase 8 : mises à jour, reprise sur fichier verrouillé

MAX_ATTEMPTS = 20
EXIT_LABEL = "Sorti du parc"


def find_workbook(agency_number: Optional[str], registry_name: Optional[str] = None) -> Optional[Path]:
    return _find_workbook_path(agency_number, registry_name) if agency_number else None


def workbook_name(agency_number: Optional[str], registry_name: Optional[str] = None) -> Optional[str]:
    path = find_workbook(agency_number, registry_name)
    return path.name if path else None


def _is_locked(path: Path) -> bool:
    return (path.parent / f"~${path.name}").exists()


def _write_row(ws, row_number: int, tool: AgencyTool, keep_id: bool = True):
    if not keep_id or ws.cell(row=row_number, column=1).value in (None, ""):
        ws.cell(row=row_number, column=1, value=f"MAT{row_number - 1:03d}")
    values = [
        tool.unique_code, tool.name, tool.description, tool.brand, tool.type, tool.serial_number,
        tool.purchase_date, tool.purchase_price, tool.warranty_expiration_date,
        _warranty_status(tool.warranty_expiration_date), _state_label(tool.status, tool.state), tool.comment,
    ]
    for offset, value in enumerate(values):
        ws.cell(row=row_number, column=2 + offset, value=value)
    if tool.purchase_date:
        ws.cell(row=row_number, column=8).number_format = DATE_FORMAT
    if tool.warranty_expiration_date:
        ws.cell(row=row_number, column=10).number_format = DATE_FORMAT


def sync_tool_change(tool: AgencyTool, action: str, registry_name: Optional[str] = None, old_code: Optional[str] = None) -> Tuple[bool, str]:
    """Répercute une modification ('update') ou une sortie de parc ('exit') dans le classeur d'agence."""
    path = _find_workbook_path(tool.agency_number, registry_name)
    if path is None:
        return False, f"Fichier Excel introuvable pour l'agence {tool.agency_number}"
    if _is_locked(path):
        return False, "Fichier Excel ouvert par quelqu'un : mise à jour reportée"
    try:
        wb = load_workbook(path)
        ws = wb.active
        code = old_code or tool.unique_code
        row_number = next((r for r in range(2, ws.max_row + 1) if str(ws.cell(row=r, column=2).value or "").strip() == code), None)
        if row_number is None:
            if action == "exit":
                return True, "ok"
            row_number = ws.max_row + 1
        if action == "exit":
            ws.cell(row=row_number, column=12, value=EXIT_LABEL)
            reason = f"Sortie de parc : {tool.exit_reason or '-'}"
            ws.cell(row=row_number, column=13, value=reason)
        else:
            _write_row(ws, row_number, tool)
        wb.save(path)
        return True, "ok"
    except PermissionError:
        return False, "Fichier Excel verrouillé : mise à jour reportée"
    except Exception as exc:
        return False, f"Échec synchro Excel : {exc.__class__.__name__}"


def enqueue_sync(db, tool: AgencyTool, action: str, registry_name: Optional[str] = None, old_code: Optional[str] = None) -> Tuple[bool, str]:
    """Tente la synchronisation tout de suite ; en cas d'échec, la mémorise pour la tâche de reprise."""
    from . import appsettings, utils
    from .models_p8 import ExcelSyncTask

    if not EXCEL_SYNC_ENABLED or (action != "append" and appsettings.get(db, "excel.sync_mode") != "full"):
        return True, "ok"
    if action == "append":
        ok, message = sync_new_agency_tool(tool, registry_name)
    else:
        ok, message = sync_tool_change(tool, action, registry_name, old_code)
    if not ok and not message.startswith("Fichier Excel introuvable"):
        db.add(ExcelSyncTask(agency_number=tool.agency_number, tool_id=tool.id, action=action, attempts=1, last_error=message,
                             payload=json.dumps({"old_code": old_code, "registry": registry_name}), created_at=utils.now()))
    return ok, message


def retry_pending(db) -> Tuple[int, int]:
    from . import utils
    from .agencies import registry_name_for
    from .models_p8 import ExcelSyncTask

    done = failed = 0
    for task in db.query(ExcelSyncTask).filter(ExcelSyncTask.status == "pending").order_by(ExcelSyncTask.id).limit(200):
        tool = db.query(AgencyTool).filter(AgencyTool.id == task.tool_id).first()
        if tool is None:
            task.status, task.done_at, task.last_error = "failed", utils.now(), "Outil supprimé"
            failed += 1
            continue
        info = json.loads(task.payload or "{}")
        registry = registry_name_for(db, tool.agency_number)
        if task.action == "append":
            ok, message = sync_tool_change(tool, "update", registry)  # ajoute la ligne si elle manque
        else:
            ok, message = sync_tool_change(tool, task.action, registry, info.get("old_code"))
        task.attempts += 1
        task.last_error = None if ok else message
        if ok:
            task.status, task.done_at = "done", utils.now()
            done += 1
        elif task.attempts >= MAX_ATTEMPTS:
            task.status, task.done_at = "failed", utils.now()
            failed += 1
    db.commit()
    return done, failed
