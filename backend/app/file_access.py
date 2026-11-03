"""Droit de lire un fichier téléversé : le chemin doit être référencé en base et l'objet qui le porte accessible à l'utilisateur."""
from typing import Optional

from sqlalchemy.orm import Session

from . import controls
from .hierarchy import visible_user_ids
from .models import AgencyTool, Epi, Loan, PersonalTool, User, UserRole
from .models_p2 import Calibration, Inspection, UserQualification
from .models_p3 import ToolPhoto
from .models_p5 import MaintenanceAttachment, MaintenanceTicket

MAINTENANCE_ROLES = (UserRole.directeur_agence, UserRole.charge_affaires, UserRole.magasinier)


def _tool(db: Session, user: User, kind: str, tool_id: int) -> bool:
    tool = controls.get_tool(db, kind, tool_id)
    return tool is not None and controls.can_access(db, user, kind, tool)


def _in_team(db: Session, user: User, target_id: Optional[int]) -> bool:
    ids = visible_user_ids(db, user)
    return ids is None or target_id in ids


def can_read(db: Session, user: User, path: str) -> bool:
    if user.role == UserRole.admin:
        return True

    for model, kind in ((AgencyTool, "agency"), (Epi, "epi")):
        row = db.query(model).filter(model.photo_path == path).first()
        if row is not None:
            return controls.can_access(db, user, kind, row)

    row = db.query(PersonalTool).filter((PersonalTool.photo_path == path) | (PersonalTool.state_photo_path == path)).first()
    if row is not None:
        return controls.can_access(db, user, "personal", row)

    row = db.query(ToolPhoto).filter(ToolPhoto.path == path).first()
    if row is not None:
        return _tool(db, user, row.tool_kind, row.tool_id)

    row = db.query(Inspection).filter((Inspection.photo_path == path) | (Inspection.report_path == path)).first()
    if row is not None:
        return _tool(db, user, row.tool_kind, row.tool_id)

    row = db.query(Calibration).filter(Calibration.certificate_path == path).first()
    if row is not None:
        return _tool(db, user, "agency", row.tool_id)

    row = db.query(Loan).filter(Loan.photo_return_path == path).first()
    if row is not None:
        return row.borrower_id == user.id or _tool(db, user, "agency", row.tool_id)

    row = db.query(UserQualification).filter(UserQualification.document_path == path).first()
    if row is not None:
        return row.user_id == user.id or _in_team(db, user, row.user_id)

    row = db.query(MaintenanceAttachment).filter(MaintenanceAttachment.path == path).first()
    if row is not None:
        ticket = db.query(MaintenanceTicket).filter(MaintenanceTicket.id == row.ticket_id).first()
        if ticket is None or ticket.agency_number != user.agency_number:
            return False
        return user.role in MAINTENANCE_ROLES or ticket.opened_by_id == user.id

    return False
