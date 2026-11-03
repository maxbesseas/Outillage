"""Phase 7 : exports CSV / Excel (multi-feuilles) et API de rapports par clé d'accès."""
import csv
import io
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, datasets, limits, utils
from ..agencies import agency_scope
from ..auth import get_current_admin, get_current_manager, hash_token
from ..database import get_db
from ..models import User, UserRole
from ..models_p7 import ApiKey
from ..utils import safe_text

router = APIRouter(prefix="/exports", tags=["exports"])
keys_router = APIRouter(prefix="/api-keys", tags=["api-keys"])
reports_router = APIRouter(prefix="/reports", tags=["rapports"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
RATE_LIMIT_PER_MINUTE = 60


def _fail(message: str, code: int = status.HTTP_400_BAD_REQUEST):
    raise HTTPException(status_code=code, detail=message)


def _scope(user: User, requested: Optional[str]) -> Optional[str]:
    return agency_scope(user, requested)


def _csv_cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, float):
        return f"{value:.2f}".replace(".", ",")
    return safe_text(str(value))


def _csv_response(name: str, cols, rows) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(list(cols.values()))
    for row in rows:
        writer.writerow([_csv_cell(row.get(k)) for k in cols])
    body = "﻿" + buf.getvalue()
    return Response(content=body.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


def _write_sheet(ws, cols, rows):
    ws.append(list(cols.values()))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        values = []
        for k in cols:
            v = row.get(k)
            values.append(safe_text(v) if isinstance(v, str) else v)
        ws.append(values)
    for i, col in enumerate(ws.columns, 1):
        width = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 50)
    ws.freeze_panes = "A2"


def _xlsx_response(name: str, wb: Workbook) -> StreamingResponse:
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


@router.get("/workbook")
def export_workbook(request: Request, agency: Optional[str] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    scope = _scope(current_user, agency)
    wb = Workbook()
    wb.remove(wb.active)
    for key in datasets.WORKBOOK_ORDER:
        label, fn = datasets.DATASETS[key]
        cols, rows = fn(db, scope)
        _write_sheet(wb.create_sheet(label), cols, rows)
    audit.record(db, "export", current_user.id, "export", None, request, {"dataset": "workbook", "agency": scope})
    db.commit()
    return _xlsx_response(f"fauche-export-{utils.now():%Y%m%d}", wb)


@router.get("/{name}")
def export_dataset(name: str, request: Request, format: str = "csv", agency: Optional[str] = None, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_manager)):
    if name not in datasets.DATASETS:
        _fail("Jeu de données inconnu", status.HTTP_404_NOT_FOUND)
    if format not in ("csv", "xlsx"):
        _fail("Format invalide (csv ou xlsx)")
    scope = _scope(current_user, agency)
    label, fn = datasets.DATASETS[name]
    cols, rows = fn(db, scope)
    audit.record(db, "export", current_user.id, "export", None, request, {"dataset": name, "format": format, "agency": scope, "rows": len(rows)})
    db.commit()
    filename = f"fauche-{name}-{utils.now():%Y%m%d}"
    if format == "csv":
        return _csv_response(filename, cols, rows)
    wb = Workbook()
    ws = wb.active
    ws.title = label
    _write_sheet(ws, cols, rows)
    return _xlsx_response(filename, wb)


# ------------------------------------------------------------------ clés d'API

class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    agency_number: Optional[str] = None
    expires_days: Optional[int] = Field(default=None, ge=1, le=3650)


def _key_view(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "agency_number": k.agency_number, "created_at": k.created_at,
            "expires_at": k.expires_at, "last_used_at": k.last_used_at, "revoked_at": k.revoked_at, "is_active": k.is_active}


@keys_router.get("")
def list_keys(db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    return [_key_view(k) for k in db.query(ApiKey).order_by(ApiKey.id.desc())]


@keys_router.post("", status_code=status.HTTP_201_CREATED)
def create_key(payload: KeyIn, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    secret = "fk_" + secrets.token_urlsafe(32)
    now = utils.now()
    row = ApiKey(name=payload.name.strip(), prefix=secret[:8], key_hash=hash_token(secret), agency_number=payload.agency_number or None,
                 created_by_id=current_user.id, created_at=now,
                 expires_at=now + timedelta(days=payload.expires_days) if payload.expires_days else None)
    db.add(row)
    db.flush()
    audit.record(db, "api_key_created", current_user.id, "api_key", row.id, request,
                 {"name": row.name, "agency": row.agency_number, "prefix": row.prefix})
    db.commit()
    return {**_key_view(row), "key": secret, "warning": "Cette clé n'est affichée qu'une seule fois : copiez-la maintenant."}


@keys_router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_key(key_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    row = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if row is None:
        _fail("Clé introuvable", status.HTTP_404_NOT_FOUND)
    row.is_active = False
    row.revoked_at = utils.now()
    audit.record(db, "api_key_revoked", current_user.id, "api_key", row.id, request, {"prefix": row.prefix})
    db.commit()


# ------------------------------------------------------------------ rapports (lecture seule, clé d'API)

def get_api_key(x_api_key: Optional[str] = Header(default=None), db: Session = Depends(get_db)) -> ApiKey:
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Clé d'API invalide ou expirée")
    if not x_api_key or len(x_api_key) > 200:
        raise invalid
    row = db.query(ApiKey).filter(ApiKey.key_hash == hash_token(x_api_key)).first()
    if row is None or not row.is_active or row.revoked_at is not None or (row.expires_at and row.expires_at < utils.now()):
        raise invalid
    if not limits.allow(db, f"apikey:{row.id}", RATE_LIMIT_PER_MINUTE, 60):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Trop de requêtes, réessayez dans une minute",
                            headers={"Retry-After": "60"})
    row.last_used_at = utils.now()
    db.commit()
    return row


@reports_router.get("")
def list_reports(key: ApiKey = Depends(get_api_key)):
    return {"datasets": [{"name": k, "label": v[0]} for k, v in datasets.DATASETS.items()]}


@reports_router.get("/{name}")
def read_report(name: str, request: Request, response: Response, limit: int = 1000, offset: int = 0, key: ApiKey = Depends(get_api_key),
                db: Session = Depends(get_db)):
    if name not in datasets.DATASETS:
        _fail("Jeu de données inconnu", status.HTTP_404_NOT_FOUND)
    _, fn = datasets.DATASETS[name]
    _, rows = fn(db, key.agency_number)
    audit.record(db, "report_read", key.created_by_id, "api_key", key.id, request, {"dataset": name, "rows": len(rows)})
    db.commit()
    response.headers["X-Total-Count"] = str(len(rows))
    offset, limit = max(offset, 0), max(1, min(limit, 5000))
    return rows[offset: offset + limit]
