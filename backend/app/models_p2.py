from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from .database import Base


class InspectionPolicy(Base):
    __tablename__ = "inspection_policies"

    id = Column(Integer, primary_key=True)
    tool_kind = Column(String, nullable=False)  # personal | agency | epi
    type = Column(String, nullable=True)  # NULL = tous les types de ce genre
    periodicity_days = Column(Integer, nullable=False, default=365)
    warn_before_days = Column(Integer, nullable=False, default=30)
    requires_photo = Column(Boolean, nullable=False, default=False)
    requires_report = Column(Boolean, nullable=False, default=False)
    requires_calibration = Column(Boolean, nullable=False, default=False)
    calibration_periodicity_days = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tool_kind", "type", name="uq_inspection_policy"),)


class InspectionTemplate(Base):
    __tablename__ = "inspection_templates"

    id = Column(Integer, primary_key=True)
    tool_kind = Column(String, nullable=False)
    type = Column(String, nullable=False)
    items_json = Column(Text, nullable=False, default="[]")
    is_active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("tool_kind", "type", name="uq_inspection_template"),)


class Inspection(Base):
    __tablename__ = "inspections"

    id = Column(Integer, primary_key=True)
    tool_kind = Column(String, nullable=False)
    tool_id = Column(Integer, nullable=False)
    inspector_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    inspected_at = Column(DateTime, default=datetime.utcnow)
    result = Column(String, nullable=False, default="conforme")  # conforme | conforme_avec_reserves | non_conforme
    state_after = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    photo_path = Column(String, nullable=True)
    report_path = Column(String, nullable=True)
    next_due = Column(DateTime, nullable=True)
    checklist_json = Column(Text, nullable=True)

    __table_args__ = (Index("ix_inspections_tool", "tool_kind", "tool_id"),)


class Calibration(Base):
    __tablename__ = "calibrations"

    id = Column(Integer, primary_key=True)
    tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=False, index=True)
    calibrated_at = Column(DateTime, nullable=False)
    next_due = Column(DateTime, nullable=True)
    provider = Column(String, nullable=True)
    certificate_number = Column(String, nullable=True)
    certificate_path = Column(String, nullable=True)
    cost = Column(Float, nullable=True)
    result = Column(String, nullable=False, default="conforme")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class QualificationType(Base):
    __tablename__ = "qualification_types"

    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    label = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)


class UserQualification(Base):
    __tablename__ = "user_qualifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    code = Column(String, nullable=False)
    obtained_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    document_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ToolRequirement(Base):
    __tablename__ = "tool_requirements"

    id = Column(Integer, primary_key=True)
    tool_type = Column(String, nullable=True)
    agency_tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=True)
    qualification_code = Column(String, nullable=False)
    blocking = Column(Boolean, nullable=False, default=False)
