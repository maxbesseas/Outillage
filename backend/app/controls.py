import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from . import appsettings, notify, utils
from .history import log_state_change
from .hierarchy import visible_user_ids
from .models import (
    AgencyTool,
    AgencyToolStatus,
    Epi,
    PersonalTool,
    ToolKind,
    ToolStateReason,
    User,
    UserRole,
)
from .models_p2 import (
    Calibration,
    Inspection,
    InspectionPolicy,
    InspectionTemplate,
    ToolRequirement,
    UserQualification,
)

KINDS = ("personal", "agency", "epi")
MODELS = {"personal": PersonalTool, "agency": AgencyTool, "epi": Epi}
EXCLUDED_STATUSES = (AgencyToolStatus.hors_service,)
SORTI = "sorti_du_parc"


def get_tool(db: Session, kind: str, tool_id: int):
    model = MODELS.get(kind)
    return db.query(model).filter(model.id == tool_id).first() if model else None


def tool_agency(db: Session, kind: str, tool) -> Optional[str]:
    if kind == "personal":
        owner = db.query(User).filter(User.id == tool.owner_id).first()
        return owner.agency_number if owner else None
    return tool.agency_number


def can_access(db: Session, user: User, kind: str, tool) -> bool:
    if user.role == UserRole.admin:
        return True
    if kind == "personal":
        if tool.owner_id == user.id or tool.current_holder_id == user.id:
            return True
        ids = visible_user_ids(db, user)
        return ids is not None and tool.owner_id in ids
    return tool.agency_number == user.agency_number


# ---------------------------------------------------------------- politiques

def _default_policy(db: Session) -> dict:
    return {
        "periodicity_days": appsettings.get_int(db, "inspection.default_periodicity_days"),
        "warn_before_days": appsettings.get_int(db, "inspection.default_warn_days"),
        "requires_photo": False,
        "requires_report": False,
        "requires_calibration": False,
        "calibration_periodicity_days": None,
        "source": "default",
    }


def load_policies(db: Session) -> Dict[Tuple[str, Optional[str]], InspectionPolicy]:
    return {(p.tool_kind, p.type): p for p in db.query(InspectionPolicy).filter(InspectionPolicy.is_active.is_(True))}


def policy_for(db: Session, kind: str, type_: Optional[str], cache=None) -> dict:
    policies = cache if cache is not None else load_policies(db)
    row = policies.get((kind, type_)) or policies.get((kind, None))
    if row is None:
        return _default_policy(db)
    return {
        "periodicity_days": row.periodicity_days,
        "warn_before_days": row.warn_before_days,
        "requires_photo": row.requires_photo,
        "requires_report": row.requires_report,
        "requires_calibration": row.requires_calibration,
        "calibration_periodicity_days": row.calibration_periodicity_days,
        "source": "policy",
    }


def due_info(db: Session, kind: str, tool, now: Optional[datetime] = None, policies=None) -> dict:
    now = now or utils.now()
    policy = policy_for(db, kind, tool.type, policies)
    last = tool.last_control_date
    if last is None:
        return {"last": None, "due": None, "days_left": None, "status": "never", "periodicity_days": policy["periodicity_days"]}
    due = last + timedelta(days=policy["periodicity_days"])
    days_left = (due.date() - now.date()).days
    if days_left < 0:
        status = "overdue"
    elif days_left <= policy["warn_before_days"]:
        status = "soon"
    else:
        status = "ok"
    return {"last": last, "due": due, "days_left": days_left, "status": status, "periodicity_days": policy["periodicity_days"]}


def _controllable(kind: str, tool) -> bool:
    if kind == "agency":
        return tool.status not in EXCLUDED_STATUSES and getattr(tool.status, "value", tool.status) != SORTI
    return True


def due_items(db: Session, user: User, kind: Optional[str] = None, status: Optional[str] = None,
              agency: Optional[str] = None, now: Optional[datetime] = None) -> List[dict]:
    now = now or utils.now()
    policies = load_policies(db)
    items = []
    for k in KINDS:
        if kind and k != kind:
            continue
        model = MODELS[k]
        query = db.query(model)
        if k == "personal":
            ids = visible_user_ids(db, user)
            if ids is not None:
                query = query.filter((model.owner_id.in_(ids)) | (model.current_holder_id == user.id))
        elif user.role != UserRole.admin:
            query = query.filter(model.agency_number == user.agency_number)
        elif agency:
            query = query.filter(model.agency_number == agency)
        for tool in query.all():
            if not _controllable(k, tool):
                continue
            info = due_info(db, k, tool, now, policies)
            if status and info["status"] != status:
                continue
            if not status and info["status"] == "ok":
                continue
            items.append({
                "kind": k, "id": tool.id, "name": tool.name, "type": tool.type, "code": tool.unique_code,
                **info,
            })
    order = {"overdue": 0, "never": 1, "soon": 2, "ok": 3}
    items.sort(key=lambda i: (order[i["status"]], i["days_left"] if i["days_left"] is not None else -9999))
    return items


def count_due_for_agency(db: Session, agency: str) -> int:
    policies = load_policies(db)
    now = utils.now()
    count = 0
    for kind, model in (("agency", AgencyTool), ("epi", Epi)):
        for tool in db.query(model).filter(model.agency_number == agency):
            if _controllable(kind, tool) and due_info(db, kind, tool, now, policies)["status"] in ("overdue", "never"):
                count += 1
    return count


# ---------------------------------------------------------------- étalonnage

def calibration_info(db: Session, tool: AgencyTool, now: Optional[datetime] = None, policies=None) -> dict:
    now = now or utils.now()
    policy = policy_for(db, "agency", tool.type, policies)
    if not policy["requires_calibration"]:
        return {"required": False, "status": "none"}
    last = (
        db.query(Calibration).filter(Calibration.tool_id == tool.id)
        .order_by(Calibration.calibrated_at.desc(), Calibration.id.desc()).first()
    )
    if last is None:
        return {"required": True, "status": "missing", "due": None, "last": None}
    period = policy["calibration_periodicity_days"] or policy["periodicity_days"]
    due = last.next_due or (last.calibrated_at + timedelta(days=period))
    days_left = (due.date() - now.date()).days
    if last.result == "non_conforme" or days_left < 0:
        status = "expired"
    elif days_left <= policy["warn_before_days"]:
        status = "soon"
    else:
        status = "ok"
    return {"required": True, "status": status, "due": due, "last": last.calibrated_at, "days_left": days_left,
            "certificate_number": last.certificate_number}


# ---------------------------------------------------------------- habilitations

def has_valid_qualification(db: Session, user_id: int, code: str, now: Optional[datetime] = None) -> bool:
    now = now or utils.now()
    rows = db.query(UserQualification).filter(UserQualification.user_id == user_id, UserQualification.code == code).all()
    return any(r.expires_at is None or r.expires_at >= now for r in rows)


def reservation_checks(db: Session, tool: AgencyTool, user: User) -> Tuple[List[str], List[str]]:
    """Retourne (blocages, avertissements) pour la réservation d'un outil par un utilisateur."""
    blocks: List[str] = []
    warns: List[str] = []

    calibration = calibration_info(db, tool)
    if calibration["required"] and calibration["status"] in ("expired", "missing"):
        message = "Étalonnage échu ou absent pour cet instrument"
        (blocks if appsettings.get_bool(db, "calibration.block_reservation") else warns).append(message)

    requirements = db.query(ToolRequirement).filter(
        (ToolRequirement.agency_tool_id == tool.id)
        | ((ToolRequirement.tool_type == tool.type) & (ToolRequirement.tool_type.isnot(None)))
    ).all()
    from .models_p2 import QualificationType

    labels = {q.code: q.label for q in db.query(QualificationType)}
    for requirement in requirements:
        if not has_valid_qualification(db, user.id, requirement.qualification_code):
            label = labels.get(requirement.qualification_code, requirement.qualification_code)
            message = f"Habilitation requise absente ou expirée : {label}"
            if requirement.blocking or appsettings.get_bool(db, "qualification.block"):
                blocks.append(message)
            else:
                warns.append(message)
    return blocks, warns


# ---------------------------------------------------------------- contrôle

def template_items(db: Session, kind: str, type_: Optional[str]) -> List[dict]:
    row = (
        db.query(InspectionTemplate)
        .filter(InspectionTemplate.tool_kind == kind, InspectionTemplate.type == (type_ or ""),
                InspectionTemplate.is_active.is_(True))
        .first()
    )
    return json.loads(row.items_json) if row else []


class InspectionError(Exception):
    pass


def evaluate_checklist(items: List[dict], answers: List[dict]) -> Tuple[str, List[dict]]:
    known = {i["id"]: i for i in items}
    given = {}
    for answer in answers or []:
        if answer.get("id") not in known:
            raise InspectionError(f"Point de contrôle inconnu : {answer.get('id')}")
        given[answer["id"]] = answer
    result = "conforme"
    recorded = []
    for item in items:
        answer = given.get(item["id"])
        if answer is None or answer.get("answer") in (None, ""):
            if item.get("required"):
                raise InspectionError(f"Point obligatoire non renseigné : {item['label']}")
            continue
        recorded.append({"id": item["id"], "label": item["label"], "required": bool(item.get("required")),
                         "answer": answer["answer"], "comment": answer.get("comment")})
        if answer["answer"] == "ko":
            if item.get("required"):
                result = "non_conforme"
            elif result == "conforme":
                result = "conforme_avec_reserves"
    return result, recorded


def record_inspection(
    db: Session,
    kind: str,
    tool,
    user: User,
    state_after: Optional[int] = None,
    comment: Optional[str] = None,
    answers: Optional[List[dict]] = None,
    explicit_result: Optional[str] = None,
    status: Optional[str] = None,
    loss_reason: Optional[str] = None,
    photo_attached: bool = False,
    now: Optional[datetime] = None,
) -> Inspection:
    now = now or utils.now()
    items = template_items(db, kind, tool.type)
    policy = policy_for(db, kind, tool.type)

    if items:
        try:
            result, recorded = evaluate_checklist(items, answers or [])
        except InspectionError as exc:
            raise ValueError(str(exc))
    else:
        result = explicit_result if explicit_result in ("conforme", "conforme_avec_reserves", "non_conforme") else "conforme"
        recorded = []

    if (policy["requires_photo"] or (result == "non_conforme" and appsettings.get_bool(db, "photo.required_on_nonconform"))) \
            and not photo_attached:
        raise ValueError("Une photo est obligatoire pour ce contrôle")

    old_state = tool.state
    new_state = old_state if state_after is None else state_after
    old_status = None
    problem_reason = None

    tool.state = new_state
    tool.last_control_date = now

    if kind == "agency":
        old_status = tool.status.value
        forced = None
        if result == "non_conforme":
            forced = appsettings.get(db, "inspection.nonconform_status")
            forced = forced if forced in ("reparation", "hors_service") else "reparation"
        target = forced or status
        if target in ("disponible", "reparation", "hors_service"):
            tool.status = AgencyToolStatus(target)
            tool.loss_reason = loss_reason if target == "hors_service" and loss_reason else None
        if tool.status.value != old_status and tool.status in (AgencyToolStatus.reparation, AgencyToolStatus.hors_service):
            problem_reason = tool.status.value
        log_state_change(db, ToolKind.agency, tool.id, old_state, new_state, old_status, tool.status.value,
                         user.id, "contrôle", comment=comment)
    elif kind == "epi":
        log_state_change(db, ToolKind.epi, tool.id, old_state, new_state, None, None, user.id, "contrôle", comment=comment)
    else:
        old_reason = tool.state_reason.value
        if result == "non_conforme":
            tool.state_reason = ToolStateReason.en_reparation
            problem_reason = "en_reparation"
        log_state_change(db, ToolKind.personal, tool.id, old_state, new_state, old_reason, tool.state_reason.value,
                         user.id, "contrôle", comment=comment)

    inspection = Inspection(
        tool_kind=kind, tool_id=tool.id, inspector_id=user.id, inspected_at=now, result=result,
        state_after=new_state, comment=comment, next_due=now + timedelta(days=policy["periodicity_days"]),
        checklist_json=json.dumps(recorded, ensure_ascii=False) if recorded else None,
    )
    db.add(inspection)
    db.flush()

    if problem_reason:
        notify.on_tool_problem(db, kind, tool, user.id, problem_reason)
    return inspection


def log_simple_inspection(db: Session, kind: str, tool, user: User, comment: Optional[str] = None) -> Inspection:
    """Trace un contrôle rapide (routes /control historiques) dans le registre des contrôles."""
    now = utils.now()
    policy = policy_for(db, kind, tool.type)
    inspection = Inspection(
        tool_kind=kind, tool_id=tool.id, inspector_id=user.id, inspected_at=now, result="conforme",
        state_after=tool.state, comment=comment, next_due=now + timedelta(days=policy["periodicity_days"]),
    )
    db.add(inspection)
    return inspection


# ---------------------------------------------------------------- alertes

def _week_key(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso[0]}-{iso[1]}"


def generate_control_alerts(db: Session, now: datetime) -> int:
    policies = load_policies(db)
    per_user: Dict[int, List[Tuple[str, str]]] = {}

    def add(user: Optional[User], label: str, status: str):
        if user is not None and user.is_active:
            per_user.setdefault(user.id, []).append((label, status))

    for kind, model in (("agency", AgencyTool), ("epi", Epi), ("personal", PersonalTool)):
        for tool in db.query(model).all():
            if not _controllable(kind, tool):
                continue
            info = due_info(db, kind, tool, now, policies)
            if info["status"] == "ok":
                continue
            label = f"{tool.name} ({tool.unique_code})"
            if kind == "agency":
                for manager in notify.agency_managers(db, tool.agency_number):
                    add(manager, label, info["status"])
                if tool.assigned_to_id:
                    add(db.query(User).filter(User.id == tool.assigned_to_id).first(), label, info["status"])
            elif kind == "epi":
                holder = db.query(User).filter(User.id == tool.assigned_to_id).first() if tool.assigned_to_id else None
                if holder:
                    add(holder, label, info["status"])
                    for manager in notify.chain_managers(db, holder):
                        add(manager, label, info["status"])
                else:
                    for manager in notify.agency_managers(db, tool.agency_number):
                        add(manager, label, info["status"])
            else:
                owner = db.query(User).filter(User.id == tool.owner_id).first()
                add(owner, label, info["status"])

    count = 0
    week = _week_key(now)
    for user_id, entries in per_user.items():
        overdue = [e for e in entries if e[1] in ("overdue", "never")]
        soon = [e for e in entries if e[1] == "soon"]
        sample = ", ".join(label for label, _ in (overdue + soon)[:6])
        more = len(entries) - 6
        body = f"{len(overdue)} en retard ou jamais contrôlé(s), {len(soon)} bientôt à contrôler. {sample}" + (f" et {more} autre(s)." if more > 0 else ".")
        severity = "warning" if overdue else "info"
        if notify.create(db, user_id, "control_due", f"{len(entries)} contrôle(s) à faire", body, severity=severity,
                         link="#/controles", dedup_key=f"control_due:{week}"):
            count += 1
    return count


def generate_calibration_alerts(db: Session, now: datetime) -> int:
    policies = load_policies(db)
    count = 0
    week = _week_key(now)
    for tool in db.query(AgencyTool).all():
        if not _controllable("agency", tool):
            continue
        info = calibration_info(db, tool, now, policies)
        if info["status"] not in ("expired", "soon", "missing"):
            continue
        label = {"expired": "échu", "soon": "bientôt échu", "missing": "jamais réalisé"}[info["status"]]
        count += notify.create_many(
            db, notify.agency_managers(db, tool.agency_number), "calibration_due",
            f"Étalonnage {label} : {tool.name}", f"{tool.name} ({tool.unique_code}) : étalonnage {label}.",
            entity_kind="agency", entity_id=tool.id, link="#/etalonnages",
            dedup_prefix=f"calibration:{tool.id}:{info['status']}:{week}",
        )
    return count


def generate_qualification_alerts(db: Session, now: datetime) -> int:
    count = 0
    limit = now + timedelta(days=30)
    for q in db.query(UserQualification).filter(UserQualification.expires_at.isnot(None), UserQualification.expires_at <= limit).all():
        user = db.query(User).filter(User.id == q.user_id).first()
        if user is None:
            continue
        expired = q.expires_at < now
        title = f"Habilitation {'expirée' if expired else 'bientôt expirée'} : {q.code}"
        body = f"{user.full_name} : {q.code} jusqu'au {q.expires_at:%d/%m/%Y}."
        recipients = [user] + notify.chain_managers(db, user)
        count += notify.create_many(
            db, recipients, "qualification_expiring", title, body, entity_kind="qualification", entity_id=q.id,
            link="#/habilitations", dedup_prefix=f"qualif:{q.id}:{'x' if expired else 'soon'}",
        )
    return count
