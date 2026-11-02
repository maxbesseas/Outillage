"""Phase 8 : import Excel/CSV (aperçu, correspondance de colonnes, simulation, validation, rapports)."""
import io
import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session

from .. import audit, excel_export, importer, utils
from ..auth import get_current_manager
from ..database import get_db
from ..models import User, UserRole
from ..models_p8 import ImportReport

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_DETAIL_ROWS = 1000


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read(importer.MAX_BYTES + 1)
    if len(content) > importer.MAX_BYTES:
        _fail(f"Fichier trop volumineux (maximum {importer.MAX_BYTES // (1024 * 1024)} Mo)")
    return content


@router.get("/fields")
def import_fields(current_user: User = Depends(get_current_manager)):
    return {
        target: {"required": importer.REQUIRED[target], "fields": [{"key": k, "label": v[0]} for k, v in fields.items()]}
        for target, fields in importer.TARGETS.items()
        if target != "users" or current_user.role in (UserRole.admin, UserRole.directeur_agence)
    }


@router.get("/template/{target}")
def template(target: str, current_user: User = Depends(get_current_manager)):
    if target not in importer.TARGETS:
        _fail("Type d'import inconnu", status.HTTP_404_NOT_FOUND)
    wb = Workbook()
    ws = wb.active
    ws.title = "Import"
    ws.append([label for label, _ in importer.TARGETS[target].values()])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="modele-import-{target}.xlsx"'},
    )


@router.post("/preview")
async def preview(file: UploadFile = File(...), sheet: Optional[str] = Form(default=None), current_user: User = Depends(get_current_manager)):
    content = await _read_upload(file)
    try:
        headers, rows, sheets, used = importer.read_table(content, file.filename or "", sheet)
    except importer.ImportFileError as exc:
        _fail(str(exc))
    return {
        "filename": file.filename, "sheets": sheets, "sheet": used, "headers": headers, "total_rows": len(rows),
        "sample": [[("" if c is None else str(c)) for c in r[: len(headers)]] for r in rows[:5]],
        "suggestions": {t: importer.suggest_mapping(headers, t) for t in importer.TARGETS},
    }


def _store_report(db: Session, user: User, result: dict, filename: str) -> ImportReport:
    problems = [r for r in result["rows"] if r["errors"] or r["warnings"] or r["action"] in ("error", "skip")]
    report = ImportReport(
        user_id=user.id, agency_number=result["agency_number"], target=result["target"], filename=(filename or "")[:200],
        mode=result["mode"], created_count=result["counts"]["create"], updated_count=result["counts"]["update"],
        skipped_count=result["counts"]["skip"], error_count=result["counts"]["error"],
        details=json.dumps(problems[:MAX_DETAIL_ROWS], ensure_ascii=False), created_at=utils.now(),
    )
    db.add(report)
    db.flush()
    return report


@router.post("/run")
async def run(
    request: Request,
    file: UploadFile = File(...),
    target: str = Form(...),
    mapping: str = Form(...),
    mode: str = Form(default="simulate"),
    sheet: Optional[str] = Form(default=None),
    update_existing: bool = Form(default=False),
    skip_errors: bool = Form(default=False),
    agency_number: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_manager),
):
    content = await _read_upload(file)
    try:
        raw_mapping = json.loads(mapping)
        if not isinstance(raw_mapping, dict):
            raise ValueError
    except ValueError:
        _fail("Correspondance de colonnes invalide")
    try:
        result = importer.run_import(
            db, current_user, target, content, file.filename or "", raw_mapping, mode=mode, sheet=sheet,
            update_existing=update_existing, skip_errors=skip_errors, agency_number=agency_number,
        )
    except importer.ImportFileError as exc:
        _fail(str(exc))
    except PermissionError as exc:
        _fail(str(exc), status.HTTP_403_FORBIDDEN)

    report = _store_report(db, current_user, result, file.filename or "")
    if mode == "commit":
        audit.record(db, "import_committed", current_user.id, "import", report.id, request,
                     {"target": target, "file": file.filename, "counts": result["counts"]})
    db.commit()
    out = dict(result)
    out["report_id"] = report.id
    out["rows"] = [r for r in result["rows"] if r["action"] != "skip" or r["warnings"]][:MAX_DETAIL_ROWS]
    return out


def _report_view(r: ImportReport, detail: bool = False) -> dict:
    data = {
        "id": r.id, "target": r.target, "filename": r.filename, "mode": r.mode, "agency_number": r.agency_number,
        "created": r.created_count, "updated": r.updated_count, "skipped": r.skipped_count, "errors": r.error_count,
        "created_at": r.created_at, "user_id": r.user_id,
    }
    if detail:
        data["rows"] = json.loads(r.details or "[]")
    return data


@router.get("")
def list_reports(db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    query = db.query(ImportReport)
    if current_user.role != UserRole.admin:
        query = query.filter(ImportReport.agency_number == current_user.agency_number)
    return [_report_view(r) for r in query.order_by(ImportReport.id.desc()).limit(100)]


@router.get("/from-excel/status")
def excel_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    agency = current_user.agency_number
    return {"agency_number": agency, "file": excel_export.workbook_name(agency) if agency else None}


@router.post("/from-excel")
def import_from_excel_file(request: Request, mode: str = "simulate", agency_number: Optional[str] = None, db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_manager)):
    """Relit le classeur Excel de l'agence posé sur le serveur (Source/) et met la base à jour (codes déjà connus inclus)."""
    agency = agency_number if current_user.role == UserRole.admin and agency_number else current_user.agency_number
    if not agency:
        _fail("Agence inconnue")
    path = excel_export.find_workbook(agency)
    if path is None:
        _fail(f"Fichier Excel introuvable pour l'agence {agency}", status.HTTP_404_NOT_FOUND)
    try:
        content = path.read_bytes()
    except OSError as exc:
        _fail(f"Fichier illisible (est-il ouvert dans Excel ?) : {exc.__class__.__name__}")
    try:
        headers, _, _, _ = importer.read_table(content, path.name)
        result = importer.run_import(
            db, current_user, "agency_tools", content, path.name, importer.suggest_mapping(headers, "agency_tools"), mode=mode,
            update_existing=True, skip_errors=True, agency_number=agency,
        )
    except importer.ImportFileError as exc:
        _fail(str(exc))
    except PermissionError as exc:
        _fail(str(exc), status.HTTP_403_FORBIDDEN)
    report = _store_report(db, current_user, result, path.name)
    if mode == "commit":
        audit.record(db, "excel_reimport", current_user.id, "import", report.id, request, {"agency": agency, "counts": result["counts"]})
    db.commit()
    result["rows"] = [r for r in result["rows"] if r["action"] in ("create", "update", "error")][:MAX_DETAIL_ROWS]
    result["report_id"] = report.id
    return result


@router.get("/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    report = db.query(ImportReport).filter(ImportReport.id == report_id).first()
    if report is None:
        _fail("Rapport introuvable", status.HTTP_404_NOT_FOUND)
    if current_user.role != UserRole.admin and report.agency_number != current_user.agency_number:
        _fail("Ce rapport appartient à une autre agence", status.HTTP_403_FORBIDDEN)
    return _report_view(report, detail=True)
