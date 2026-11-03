import io
import json
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import appsettings, audit, controls, utils
from ..auth import get_current_admin, get_current_manager, get_current_user
from ..database import get_db
from ..hierarchy import visible_user_ids
from ..models import AgencyTool, Epi, PersonalTool, User, UserRole
from ..models_p2 import (
    Calibration,
    Inspection,
    InspectionPolicy,
    InspectionTemplate,
    QualificationType,
    ToolRequirement,
    UserQualification,
)
from ..pdf import Pdf
from ..utils import save_document, save_upload_file

policies_router = APIRouter(prefix="/inspection-policies", tags=["controles"])
templates_router = APIRouter(prefix="/inspection-templates", tags=["controles"])
router = APIRouter(prefix="/inspections", tags=["controles"])
calibrations_router = APIRouter(prefix="/calibrations", tags=["etalonnage"])
qualification_types_router = APIRouter(prefix="/qualification-types", tags=["habilitations"])
qualifications_router = APIRouter(prefix="/qualifications", tags=["habilitations"])
requirements_router = APIRouter(prefix="/tool-requirements", tags=["habilitations"])

RESULTS = ("conforme", "conforme_avec_reserves", "non_conforme")


# ------------------------------------------------------------------ schémas

class PolicyIn(BaseModel):
    tool_kind: str
    type: Optional[str] = None
    periodicity_days: int = Field(ge=1, le=3650)
    warn_before_days: int = Field(default=30, ge=0, le=365)
    requires_photo: bool = False
    requires_report: bool = False
    requires_calibration: bool = False
    calibration_periodicity_days: Optional[int] = Field(default=None, ge=1, le=3650)
    description: Optional[str] = None
    is_active: bool = True


class PolicyPatch(BaseModel):
    periodicity_days: Optional[int] = Field(default=None, ge=1, le=3650)
    warn_before_days: Optional[int] = Field(default=None, ge=0, le=365)
    requires_photo: Optional[bool] = None
    requires_report: Optional[bool] = None
    requires_calibration: Optional[bool] = None
    calibration_periodicity_days: Optional[int] = Field(default=None, ge=1, le=3650)
    description: Optional[str] = None
    is_active: Optional[bool] = None


class PolicyOut(PolicyIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class TemplateItem(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=200)
    required: bool = False


class TemplateIn(BaseModel):
    tool_kind: str
    type: str = Field(min_length=1)
    items: List[TemplateItem]
    is_active: bool = True


class ChecklistAnswer(BaseModel):
    id: str
    answer: Optional[str] = None
    comment: Optional[str] = None


class InspectionIn(BaseModel):
    tool_kind: str
    tool_id: int
    state_after: Optional[int] = Field(default=None, ge=0, le=5)
    result: Optional[str] = None
    comment: Optional[str] = None
    checklist: List[ChecklistAnswer] = []
    status: Optional[str] = None
    loss_reason: Optional[str] = None
    photo_attached: bool = False


class InspectionOut(BaseModel):
    id: int
    tool_kind: str
    tool_id: int
    inspector_id: Optional[int]
    inspector_name: Optional[str] = None
    inspected_at: datetime
    result: str
    state_after: Optional[int]
    comment: Optional[str]
    photo_path: Optional[str]
    report_path: Optional[str]
    next_due: Optional[datetime]
    checklist: list = []
    photo_required: bool = False


class CalibrationIn(BaseModel):
    tool_id: int
    calibrated_at: datetime
    next_due: Optional[datetime] = None
    provider: Optional[str] = None
    certificate_number: Optional[str] = None
    cost: Optional[float] = Field(default=None, ge=0)
    result: str = "conforme"


class QualificationTypeIn(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=120)
    is_active: bool = True


class QualificationIn(BaseModel):
    user_id: int
    code: str
    obtained_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class RequirementIn(BaseModel):
    tool_type: Optional[str] = None
    agency_tool_id: Optional[int] = None
    qualification_code: str
    blocking: bool = False


def _inspection_out(db: Session, row: Inspection, names: dict) -> dict:
    tool = controls.get_tool(db, row.tool_kind, row.tool_id)
    policy = controls.policy_for(db, row.tool_kind, tool.type if tool else None)
    return {
        "id": row.id, "tool_kind": row.tool_kind, "tool_id": row.tool_id, "inspector_id": row.inspector_id,
        "inspector_name": names.get(row.inspector_id), "inspected_at": row.inspected_at, "result": row.result,
        "state_after": row.state_after, "comment": row.comment, "photo_path": row.photo_path,
        "report_path": row.report_path, "next_due": row.next_due,
        "checklist": json.loads(row.checklist_json) if row.checklist_json else [],
        "photo_required": policy["requires_photo"],
    }


def _names(db: Session) -> dict:
    return {u.id: u.full_name for u in db.query(User).all()}


def _valid_kind(kind: str):
    if kind not in controls.KINDS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Type d'outil invalide")


def _tool_or_error(db: Session, user: User, kind: str, tool_id: int):
    _valid_kind(kind)
    tool = controls.get_tool(db, kind, tool_id)
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Outil introuvable")
    if not controls.can_access(db, user, kind, tool):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à cet outil")
    return tool


# ------------------------------------------------------------------ politiques

@policies_router.get("", response_model=List[PolicyOut])
def list_policies(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(InspectionPolicy).order_by(InspectionPolicy.tool_kind, InspectionPolicy.type).all()


@policies_router.post("", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
def create_policy(payload: PolicyIn, request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_admin)):
    _valid_kind(payload.tool_kind)
    if db.query(InspectionPolicy).filter(InspectionPolicy.tool_kind == payload.tool_kind,
                                         InspectionPolicy.type == payload.type).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Une politique existe déjà pour ce type")
    row = InspectionPolicy(**payload.model_dump())
    db.add(row)
    db.flush()
    audit.record(db, "inspection_policy_created", current_user.id, "inspection_policy", row.id, request, payload.model_dump())
    db.commit()
    db.refresh(row)
    return row


@policies_router.patch("/{policy_id}", response_model=PolicyOut)
def update_policy(policy_id: int, payload: PolicyPatch, request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_admin)):
    row = db.query(InspectionPolicy).filter(InspectionPolicy.id == policy_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Politique introuvable")
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value)
    audit.record(db, "inspection_policy_updated", current_user.id, "inspection_policy", row.id, request, data)
    db.commit()
    db.refresh(row)
    return row


@policies_router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(policy_id: int, request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_admin)):
    row = db.query(InspectionPolicy).filter(InspectionPolicy.id == policy_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Politique introuvable")
    audit.record(db, "inspection_policy_deleted", current_user.id, "inspection_policy", row.id, request)
    db.delete(row)
    db.commit()
    return None


# ------------------------------------------------------------------ modèles de checklist

@templates_router.get("")
def list_templates(tool_kind: Optional[str] = None, type: Optional[str] = None, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    query = db.query(InspectionTemplate)
    if tool_kind:
        query = query.filter(InspectionTemplate.tool_kind == tool_kind)
    if type:
        query = query.filter(InspectionTemplate.type == type)
    return [
        {"id": t.id, "tool_kind": t.tool_kind, "type": t.type, "items": json.loads(t.items_json), "is_active": t.is_active}
        for t in query.order_by(InspectionTemplate.tool_kind, InspectionTemplate.type).all()
    ]


@templates_router.put("")
def upsert_template(payload: TemplateIn, request: Request, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_admin)):
    _valid_kind(payload.tool_kind)
    ids = [i.id for i in payload.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Les identifiants de points doivent être uniques")
    row = db.query(InspectionTemplate).filter(InspectionTemplate.tool_kind == payload.tool_kind,
                                              InspectionTemplate.type == payload.type).first()
    if row is None:
        row = InspectionTemplate(tool_kind=payload.tool_kind, type=payload.type)
        db.add(row)
    row.items_json = json.dumps([i.model_dump() for i in payload.items], ensure_ascii=False)
    row.is_active = payload.is_active
    db.flush()
    audit.record(db, "inspection_template_saved", current_user.id, "inspection_template", row.id, request,
                 {"type": payload.type, "items": len(payload.items)})
    db.commit()
    return {"id": row.id, "tool_kind": row.tool_kind, "type": row.type, "items": json.loads(row.items_json), "is_active": row.is_active}


@templates_router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_admin)):
    row = db.query(InspectionTemplate).filter(InspectionTemplate.id == template_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Modèle introuvable")
    db.delete(row)
    db.commit()
    return None


# ------------------------------------------------------------------ contrôles

@router.get("/due")
def list_due(kind: Optional[str] = None, status_filter: Optional[str] = None, agency: Optional[str] = None,
             db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if kind:
        _valid_kind(kind)
    items = controls.due_items(db, current_user, kind, status_filter, agency)
    return {
        "items": items,
        "counts": {s: sum(1 for i in items if i["status"] == s) for s in ("overdue", "never", "soon")},
    }


@router.get("/template")
def checklist_for(kind: str, type: Optional[str] = None, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    _valid_kind(kind)
    return {"items": controls.template_items(db, kind, type), "policy": controls.policy_for(db, kind, type)}


@router.post("", response_model=InspectionOut, status_code=status.HTTP_201_CREATED)
def create_inspection(payload: InspectionIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    tool = _tool_or_error(db, current_user, payload.tool_kind, payload.tool_id)
    if payload.result is not None and payload.result not in RESULTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Résultat invalide")
    if payload.tool_kind == "agency" and payload.status:
        refusal = controls.status_change_error(current_user, tool.status.value, payload.status)
        if refusal:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)
    try:
        inspection = controls.record_inspection(
            db, payload.tool_kind, tool, current_user, payload.state_after, payload.comment,
            [c.model_dump() for c in payload.checklist], payload.result, payload.status, payload.loss_reason,
            payload.photo_attached,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    db.commit()
    db.refresh(inspection)
    return _inspection_out(db, inspection, _names(db))


@router.get("", response_model=List[InspectionOut])
def list_inspections(tool_kind: str, tool_id: int, response: Response, limit: int = 100, offset: int = 0,
                     db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _tool_or_error(db, current_user, tool_kind, tool_id)
    query = db.query(Inspection).filter(Inspection.tool_kind == tool_kind, Inspection.tool_id == tool_id)
    response.headers["X-Total-Count"] = str(query.count())
    rows = query.order_by(Inspection.inspected_at.desc(), Inspection.id.desc()).offset(max(offset, 0)).limit(max(1, min(limit, 500))).all()
    names = _names(db)
    return [_inspection_out(db, r, names) for r in rows]


def _inspection_for_write(db: Session, user: User, inspection_id: int) -> Inspection:
    row = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrôle introuvable")
    _tool_or_error(db, user, row.tool_kind, row.tool_id)
    return row


@router.post("/{inspection_id}/photo", response_model=InspectionOut)
def upload_inspection_photo(inspection_id: int, file: UploadFile, db: Session = Depends(get_db),
                            current_user: User = Depends(get_current_user)):
    row = _inspection_for_write(db, current_user, inspection_id)
    row.photo_path = save_upload_file(file, "inspections")
    db.commit()
    return _inspection_out(db, row, _names(db))


@router.post("/{inspection_id}/report", response_model=InspectionOut)
def upload_inspection_report(inspection_id: int, file: UploadFile, db: Session = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    row = _inspection_for_write(db, current_user, inspection_id)
    row.report_path = save_document(file, "inspection_reports")
    db.commit()
    return _inspection_out(db, row, _names(db))


@router.get("/registry")
def export_registry(tool_kind: str, request: Request, tool_id: Optional[int] = None, type: Optional[str] = None,
                    format: str = "xlsx", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _valid_kind(tool_kind)
    model = controls.MODELS[tool_kind]
    if tool_id is not None:
        tools = [_tool_or_error(db, current_user, tool_kind, tool_id)]
    else:
        query = db.query(model)
        if type:
            query = query.filter(model.type == type)
        tools = [t for t in query.order_by(model.name).all() if controls.can_access(db, current_user, tool_kind, t)]
    names = _names(db)

    rows = []
    for tool in tools:
        inspections = (
            db.query(Inspection).filter(Inspection.tool_kind == tool_kind, Inspection.tool_id == tool.id)
            .order_by(Inspection.inspected_at).all()
        )
        for i in inspections:
            rows.append((tool, i))
    audit.record(db, "export_registry", current_user.id, "export", None, request, {"tool_kind": tool_kind, "tool_id": tool_id, "format": format, "rows": len(rows)})
    db.commit()
    if format == "pdf":
        pdf = Pdf("Registre de vérification")
        pdf.heading("Registre de vérification")
        pdf.paragraph(f"Édité le {utils.now():%d/%m/%Y %H:%M} par {current_user.full_name} - {len(tools)} élément(s), {len(rows)} contrôle(s).", color=(0.4, 0.45, 0.5))
        pdf.spacer(6)
        table_rows = [
            [t.unique_code, t.name, f"{i.inspected_at:%d/%m/%Y}", i.result.replace("_", " "),
             names.get(i.inspector_id, "-"), i.state_after if i.state_after is not None else "-",
             f"{i.next_due:%d/%m/%Y}" if i.next_due else "-", i.comment or ""]
            for t, i in rows
        ]
        pdf.table(["Code", "Élément", "Date", "Résultat", "Contrôleur", "État", "Prochain", "Commentaire"],
                  table_rows or [["-", "Aucun contrôle enregistré", "", "", "", "", "", ""]], [1.3, 2.2, 1.1, 1.5, 1.6, 0.6, 1.1, 2.4])
        return Response(pdf.output(), media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="registre-verification.pdf"'})

    wb = Workbook()
    ws = wb.active
    ws.title = "Contrôles"
    ws.append(["Code", "Élément", "Type", "Date du contrôle", "Résultat", "Contrôleur", "État constaté", "Prochain contrôle", "Commentaire", "Points de contrôle"])
    for tool, i in rows:
        points = "; ".join(f"{c['label']}: {c['answer']}" for c in (json.loads(i.checklist_json) if i.checklist_json else []))
        ws.append([utils.safe_text(v) for v in (tool.unique_code, tool.name, tool.type, i.inspected_at, i.result, names.get(i.inspector_id), i.state_after, i.next_due, i.comment, points)])
    if tool_kind == "agency":
        cal = wb.create_sheet("Étalonnages")
        cal.append(["Code", "Instrument", "Date", "Prochaine échéance", "Prestataire", "N° certificat", "Résultat", "Coût"])
        for tool in tools:
            for c in db.query(Calibration).filter(Calibration.tool_id == tool.id).order_by(Calibration.calibrated_at):
                cal.append([utils.safe_text(v) for v in (tool.unique_code, tool.name, c.calibrated_at, c.next_due, c.provider, c.certificate_number, c.result, c.cost)])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="registre-verification.xlsx"'})


# ------------------------------------------------------------------ étalonnages

def _agency_tool_or_error(db: Session, user: User, tool_id: int) -> AgencyTool:
    return _tool_or_error(db, user, "agency", tool_id)


@calibrations_router.get("")
def list_calibrations(tool_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _agency_tool_or_error(db, current_user, tool_id)
    rows = db.query(Calibration).filter(Calibration.tool_id == tool_id).order_by(Calibration.calibrated_at.desc()).all()
    return [{"id": c.id, "tool_id": c.tool_id, "calibrated_at": c.calibrated_at, "next_due": c.next_due, "provider": c.provider,
             "certificate_number": c.certificate_number, "certificate_path": c.certificate_path, "cost": c.cost, "result": c.result}
            for c in rows]


@calibrations_router.post("", status_code=status.HTTP_201_CREATED)
def create_calibration(payload: CalibrationIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    tool = _agency_tool_or_error(db, current_user, payload.tool_id)
    if payload.result not in ("conforme", "non_conforme"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Résultat invalide")
    policy = controls.policy_for(db, "agency", tool.type)
    next_due = payload.next_due
    if next_due is None and payload.result == "conforme":
        next_due = payload.calibrated_at + timedelta(days=policy["calibration_periodicity_days"] or policy["periodicity_days"])
    row = Calibration(tool_id=tool.id, calibrated_at=payload.calibrated_at, next_due=next_due, provider=payload.provider,
                      certificate_number=payload.certificate_number, cost=payload.cost, result=payload.result,
                      created_by_id=current_user.id)
    db.add(row)
    db.commit()
    return {"id": row.id, "next_due": row.next_due}


@calibrations_router.post("/{calibration_id}/certificate")
def upload_certificate(calibration_id: int, file: UploadFile, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_manager)):
    row = db.query(Calibration).filter(Calibration.id == calibration_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Étalonnage introuvable")
    _agency_tool_or_error(db, current_user, row.tool_id)
    row.certificate_path = save_document(file, "calibration_certificates")
    db.commit()
    return {"certificate_path": row.certificate_path}


@calibrations_router.get("/overview")
def calibration_overview(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(AgencyTool)
    if current_user.role != UserRole.admin:
        query = query.filter(AgencyTool.agency_number == current_user.agency_number)
    policies = controls.load_policies(db)
    result = {"expired": [], "soon": [], "ok": [], "missing": []}
    for tool in query.order_by(AgencyTool.name).all():
        info = controls.calibration_info(db, tool, policies=policies)
        if not info["required"]:
            continue
        result[info["status"]].append({"id": tool.id, "name": tool.name, "code": tool.unique_code, "type": tool.type,
                                       "due": info.get("due"), "last": info.get("last"),
                                       "certificate_number": info.get("certificate_number")})
    return result


# ------------------------------------------------------------------ habilitations

@qualification_types_router.get("")
def list_qualification_types(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [{"id": q.id, "code": q.code, "label": q.label, "is_active": q.is_active}
            for q in db.query(QualificationType).order_by(QualificationType.label)]


@qualification_types_router.post("", status_code=status.HTTP_201_CREATED)
def create_qualification_type(payload: QualificationTypeIn, db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_admin)):
    if db.query(QualificationType).filter(QualificationType.code == payload.code).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce code existe déjà")
    row = QualificationType(**payload.model_dump())
    db.add(row)
    db.commit()
    return {"id": row.id, "code": row.code, "label": row.label, "is_active": row.is_active}


@qualification_types_router.patch("/{type_id}")
def update_qualification_type(type_id: int, payload: QualificationTypeIn, db: Session = Depends(get_db),
                              current_user: User = Depends(get_current_admin)):
    row = db.query(QualificationType).filter(QualificationType.id == type_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Type introuvable")
    row.label, row.is_active = payload.label, payload.is_active
    db.commit()
    return {"id": row.id, "code": row.code, "label": row.label, "is_active": row.is_active}


def _qualification_rows(db: Session, rows) -> list:
    names = _names(db)
    now = utils.now()
    labels = {q.code: q.label for q in db.query(QualificationType)}
    out = []
    for q in rows:
        expired = q.expires_at is not None and q.expires_at < now
        soon = q.expires_at is not None and not expired and q.expires_at <= now + timedelta(days=30)
        out.append({"id": q.id, "user_id": q.user_id, "user_name": names.get(q.user_id), "code": q.code,
                    "label": labels.get(q.code, q.code), "obtained_at": q.obtained_at, "expires_at": q.expires_at,
                    "document_path": q.document_path, "status": "expired" if expired else "soon" if soon else "ok"})
    return out


def _can_manage_user(db: Session, actor: User, target_id: int) -> bool:
    if actor.role == UserRole.admin:
        return True
    if actor.role == UserRole.gars_chantier:
        return False
    ids = visible_user_ids(db, actor)
    return ids is not None and target_id in ids


@qualifications_router.get("")
def list_qualifications(user_id: Optional[int] = None, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    query = db.query(UserQualification)
    if user_id is not None:
        if user_id != current_user.id and not _can_manage_user(db, current_user, user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé à ce salarié")
        query = query.filter(UserQualification.user_id == user_id)
    elif current_user.role == UserRole.gars_chantier:
        query = query.filter(UserQualification.user_id == current_user.id)
    else:
        ids = visible_user_ids(db, current_user)
        if ids is not None:
            query = query.filter(UserQualification.user_id.in_(ids))
    return _qualification_rows(db, query.order_by(UserQualification.expires_at).all())


@qualifications_router.post("", status_code=status.HTTP_201_CREATED)
def create_qualification(payload: QualificationIn, request: Request, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_manager)):
    if not _can_manage_user(db, current_user, payload.user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ce salarié n'est pas dans votre équipe")
    if db.query(User).filter(User.id == payload.user_id).first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Salarié introuvable")
    if db.query(QualificationType).filter(QualificationType.code == payload.code,
                                          QualificationType.is_active.is_(True)).first() is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Habilitation inconnue")
    row = UserQualification(**payload.model_dump())
    db.add(row)
    db.flush()
    audit.record(db, "qualification_added", current_user.id, "qualification", row.id, request,
                 {"user_id": payload.user_id, "code": payload.code})
    db.commit()
    return _qualification_rows(db, [row])[0]


@qualifications_router.post("/{qualification_id}/document")
def upload_qualification_document(qualification_id: int, file: UploadFile, db: Session = Depends(get_db),
                                  current_user: User = Depends(get_current_manager)):
    row = db.query(UserQualification).filter(UserQualification.id == qualification_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Habilitation introuvable")
    if not _can_manage_user(db, current_user, row.user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ce salarié n'est pas dans votre équipe")
    row.document_path = save_document(file, "qualifications")
    db.commit()
    return {"document_path": row.document_path}


@qualifications_router.delete("/{qualification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_qualification(qualification_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    row = db.query(UserQualification).filter(UserQualification.id == qualification_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Habilitation introuvable")
    if not _can_manage_user(db, current_user, row.user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ce salarié n'est pas dans votre équipe")
    db.delete(row)
    db.commit()
    return None


@requirements_router.get("")
def list_requirements(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return [{"id": r.id, "tool_type": r.tool_type, "agency_tool_id": r.agency_tool_id,
             "qualification_code": r.qualification_code, "blocking": r.blocking}
            for r in db.query(ToolRequirement).all()]


@requirements_router.post("", status_code=status.HTTP_201_CREATED)
def create_requirement(payload: RequirementIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    if bool(payload.tool_type) == bool(payload.agency_tool_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Indiquer un type d'outil ou un outil précis")
    if payload.tool_type and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Une exigence par type est réservée à l'administrateur")
    if payload.agency_tool_id:
        _agency_tool_or_error(db, current_user, payload.agency_tool_id)
    if db.query(QualificationType).filter(QualificationType.code == payload.qualification_code).first() is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Habilitation inconnue")
    row = ToolRequirement(**payload.model_dump())
    db.add(row)
    db.commit()
    return {"id": row.id}


@requirements_router.delete("/{requirement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_requirement(requirement_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_manager)):
    row = db.query(ToolRequirement).filter(ToolRequirement.id == requirement_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exigence introuvable")
    if row.tool_type and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé à l'administrateur")
    if row.agency_tool_id:
        _agency_tool_or_error(db, current_user, row.agency_tool_id)
    db.delete(row)
    db.commit()
    return None
