import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


class UserRole(str, enum.Enum):
    gars_chantier = "gars_chantier"
    charge_affaires = "charge_affaires"
    directeur_agence = "directeur_agence"
    magasinier = "magasinier"
    admin = "admin"


class AgencyToolStatus(str, enum.Enum):
    disponible = "disponible"
    reserve = "reserve"
    emprunte = "emprunte"
    reparation = "reparation"
    hors_service = "hors_service"
    dotation = "dotation"
    sorti_du_parc = "sorti_du_parc"


class AgencyLossReason(str, enum.Enum):
    vol = "vol"
    casse = "casse"
    perte = "perte"


class LoanStatus(str, enum.Enum):
    reserve = "reserve"
    en_cours = "en_cours"
    termine = "termine"
    annule = "annule"
    attente_validation = "attente_validation"
    refuse = "refuse"


class TransferStatus(str, enum.Enum):
    en_cours = "en_cours"
    termine = "termine"


class ToolStateReason(str, enum.Enum):
    normal = "normal"
    perdu = "perdu"
    endommage = "endommage"
    en_reparation = "en_reparation"


class ExternalRecipientType(str, enum.Enum):
    sous_traitant = "sous_traitant"
    interimaire = "interimaire"
    autre = "autre"


class PeerTransferStatus(str, enum.Enum):
    en_attente = "en_attente"
    confirme = "confirme"
    refuse = "refuse"
    termine = "termine"


class ToolKind(str, enum.Enum):
    personal = "personal"
    agency = "agency"
    epi = "epi"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.gars_chantier, nullable=False)
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    agency_number = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    must_change_password = Column(Boolean, default=False, nullable=False, server_default="0")
    token_version = Column(Integer, default=0, nullable=False, server_default="0")
    calendar_token = Column(String, nullable=True, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    manager = relationship("User", remote_side=[id])
    personal_tools = relationship(
        "PersonalTool",
        back_populates="owner",
        foreign_keys="PersonalTool.owner_id",
        cascade="all, delete-orphan",
    )


class PersonalTool(Base):
    __tablename__ = "personal_tools"

    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    current_holder_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=True)
    brand = Column(String, nullable=True)
    model = Column(String, nullable=True)
    unique_code = Column(String, unique=True, index=True, nullable=False)
    photo_path = Column(String, nullable=True)
    purchase_date = Column(DateTime, nullable=True)
    purchase_price = Column(Float, nullable=True)
    warranty_expiration_date = Column(DateTime, nullable=True)
    last_control_date = Column(DateTime, nullable=True)
    state = Column(Integer, default=5, nullable=False)
    state_reason = Column(Enum(ToolStateReason), default=ToolStateReason.normal, nullable=False)
    state_comment = Column(Text, nullable=True)
    state_photo_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="personal_tools", foreign_keys=[owner_id])
    current_holder = relationship("User", foreign_keys=[current_holder_id])
    transfers = relationship("Transfer", back_populates="tool", cascade="all, delete-orphan")


class AgencyTool(Base):
    __tablename__ = "agency_tools"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=True)
    brand = Column(String, nullable=True)
    unique_code = Column(String, unique=True, index=True, nullable=False)
    photo_path = Column(String, nullable=True)
    state = Column(Integer, default=5, nullable=False)
    status = Column(Enum(AgencyToolStatus), default=AgencyToolStatus.disponible, nullable=False)
    loss_reason = Column(Enum(AgencyLossReason), nullable=True)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    agency_number = Column(String, index=True, nullable=True)
    description = Column(Text, nullable=True)
    serial_number = Column(String, nullable=True)
    purchase_date = Column(DateTime, nullable=True)
    purchase_price = Column(Float, default=0.0, nullable=False)
    warranty_expiration_date = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)
    last_control_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    home_agency = Column(String, nullable=True)
    exit_reason = Column(String, nullable=True)
    exit_date = Column(DateTime, nullable=True)
    exit_note = Column(Text, nullable=True)
    residual_value = Column(Float, nullable=True)
    parent_tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=True)
    daily_rate = Column(Float, nullable=True)

    loans = relationship("Loan", back_populates="tool", cascade="all, delete-orphan")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])

    __table_args__ = (
        Index("ix_agency_tools_status", "status"),
        Index("ix_agency_tools_type", "type"),
    )


class Loan(Base):
    __tablename__ = "loans"

    id = Column(Integer, primary_key=True)
    tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=False)
    borrower_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    site = Column(String, nullable=True)
    comment = Column(Text, nullable=True)
    start_datetime = Column(DateTime, nullable=False)
    end_datetime_planned = Column(DateTime, nullable=False)
    actual_return_datetime = Column(DateTime, nullable=True)
    state_before = Column(Integer, nullable=True)
    state_after = Column(Integer, nullable=True)
    comment_return = Column(Text, nullable=True)
    photo_return_path = Column(String, nullable=True)
    status = Column(Enum(LoanStatus), default=LoanStatus.reserve, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    series_id = Column(String, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    checked_out_at = Column(DateTime, nullable=True)
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approval_comment = Column(Text, nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    signature_json = Column(Text, nullable=True)
    signed_name = Column(String, nullable=True)
    signed_at = Column(DateTime, nullable=True)

    tool = relationship("AgencyTool", back_populates="loans")
    borrower = relationship("User", foreign_keys=[borrower_id])

    __table_args__ = (
        Index("ix_loans_tool_status", "tool_id", "status"),
        Index("ix_loans_borrower", "borrower_id"),
        Index("ix_loans_start", "start_datetime"),
    )


class Transfer(Base):
    __tablename__ = "transfers"

    id = Column(Integer, primary_key=True)
    tool_id = Column(Integer, ForeignKey("personal_tools.id"), nullable=True)
    agency_tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    to_external_name = Column(String, nullable=False)
    to_external_type = Column(Enum(ExternalRecipientType), default=ExternalRecipientType.autre, nullable=False)
    to_external_company = Column(String, nullable=True)
    site_code = Column(String, nullable=True)
    client_code = Column(String, nullable=True)
    attached_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    transfer_date = Column(DateTime, default=datetime.utcnow)
    planned_return_date = Column(DateTime, nullable=True)
    actual_return_date = Column(DateTime, nullable=True)
    state_before = Column(Integer, nullable=True)
    state_after = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    status = Column(Enum(TransferStatus), default=TransferStatus.en_cours, nullable=False)
    to_external_email = Column(String, nullable=True)
    to_external_phone = Column(String, nullable=True)
    signature_json = Column(Text, nullable=True)
    signed_name = Column(String, nullable=True)
    signed_at = Column(DateTime, nullable=True)

    tool = relationship("PersonalTool", back_populates="transfers", foreign_keys=[tool_id])
    agency_tool = relationship("AgencyTool", foreign_keys=[agency_tool_id])
    from_user = relationship("User", foreign_keys=[from_user_id])
    attached_to = relationship("User", foreign_keys=[attached_to_id])


class PeerTransfer(Base):
    __tablename__ = "peer_transfers"

    id = Column(Integer, primary_key=True)
    tool_id = Column(Integer, ForeignKey("personal_tools.id"), nullable=False)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    declared_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(PeerTransferStatus), default=PeerTransferStatus.en_attente, nullable=False)
    transfer_date = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime, nullable=True)
    planned_return_date = Column(DateTime, nullable=True)
    actual_return_date = Column(DateTime, nullable=True)
    state_before = Column(Integer, nullable=True)
    state_after = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)

    tool = relationship("PersonalTool")
    from_user = relationship("User", foreign_keys=[from_user_id])
    to_user = relationship("User", foreign_keys=[to_user_id])
    declared_by = relationship("User", foreign_keys=[declared_by_id])


class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    magasinier_email = Column(String, nullable=True)
    smtp_host = Column(String, nullable=True)
    smtp_port = Column(Integer, default=587)
    smtp_username = Column(String, nullable=True)
    smtp_password = Column(String, nullable=True)
    smtp_use_tls = Column(Boolean, default=True)
    smtp_from_email = Column(String, nullable=True)


class Epi(Base):
    __tablename__ = "epi"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=True)
    brand = Column(String, nullable=True)
    unique_code = Column(String, unique=True, index=True, nullable=False)
    photo_path = Column(String, nullable=True)
    agency_number = Column(String, index=True, nullable=True)
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    state = Column(Integer, default=5, nullable=False)
    expiration_date = Column(DateTime, nullable=True)
    last_control_date = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assigned_to = relationship("User", foreign_keys=[assigned_to_id])

    __table_args__ = (Index("ix_epi_assigned_to", "assigned_to_id"),)


class StateHistory(Base):
    __tablename__ = "state_history"

    id = Column(Integer, primary_key=True)
    tool_kind = Column(Enum(ToolKind), index=True, nullable=False)
    tool_id = Column(Integer, index=True, nullable=False)
    old_state = Column(Integer, nullable=True)
    new_state = Column(Integer, nullable=False)
    old_status = Column(String, nullable=True)
    new_status = Column(String, nullable=True)
    source = Column(String, nullable=False)
    comment = Column(Text, nullable=True)
    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow)

    changed_by = relationship("User", foreign_keys=[changed_by_id])

    __table_args__ = (Index("ix_state_history_tool", "tool_kind", "tool_id"),)


class Agency(Base):
    __tablename__ = "agencies"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    code = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    excel_registry_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True)
    identifier = Column(String, index=True, nullable=False)
    ip = Column(String, index=True, nullable=True)
    success = Column(Boolean, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String, index=True, nullable=False)
    entity_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", foreign_keys=[user_id])


class JobRun(Base):
    __tablename__ = "job_runs"

    id = Column(Integer, primary_key=True)
    name = Column(String, index=True, nullable=False)
    trigger = Column(String, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="running")
    message = Column(Text, nullable=True)
