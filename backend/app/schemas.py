from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    AgencyLossReason,
    AgencyToolStatus,
    ExternalRecipientType,
    LoanStatus,
    PeerTransferStatus,
    ToolStateReason,
    TransferStatus,
    UserRole,
)


EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


# ---------- Auth ----------

class Token(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str
    user: "UserOut"


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=200)


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ProfileUpdate(BaseModel):
    email: Optional[str] = Field(default=None, pattern=EMAIL_PATTERN)
    phone: Optional[str] = Field(default=None, max_length=30)


class LoginRequest(BaseModel):
    username: str
    password: str


# ---------- Users ----------

class UserBase(BaseModel):
    username: str
    full_name: str
    role: UserRole = UserRole.gars_chantier
    manager_id: Optional[int] = None
    agency_number: Optional[str] = None
    email: Optional[str] = Field(default=None, pattern=EMAIL_PATTERN)
    phone: Optional[str] = Field(default=None, max_length=30)


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    password: Optional[str] = None
    role: Optional[UserRole] = None
    manager_id: Optional[int] = None
    agency_number: Optional[str] = None
    is_active: Optional[bool] = None
    email: Optional[str] = Field(default=None, pattern=EMAIL_PATTERN)
    phone: Optional[str] = Field(default=None, max_length=30)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    role: UserRole
    manager_id: Optional[int] = None
    agency_number: Optional[str] = None
    is_active: bool
    email: Optional[str] = None
    phone: Optional[str] = None
    must_change_password: bool = False
    created_at: datetime


Token.model_rebuild()


class TemporaryPasswordOut(BaseModel):
    temporary_password: str


class ReassignRequest(BaseModel):
    to_user_id: int


# ---------- Agencies ----------

class AgencyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    code: Optional[str] = Field(default=None, max_length=30)
    excel_registry_name: Optional[str] = Field(default=None, max_length=120)


class AgencyUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    code: Optional[str] = Field(default=None, max_length=30)
    is_active: Optional[bool] = None
    excel_registry_name: Optional[str] = Field(default=None, max_length=120)


class AgencyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: Optional[str] = None
    is_active: bool
    excel_registry_name: Optional[str] = None


# ---------- Audit / jobs ----------

class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    ip: Optional[str] = None
    details: Optional[str] = None
    created_at: datetime


class JobOut(BaseModel):
    name: str
    description: str
    interval_seconds: int
    last_started_at: Optional[datetime] = None
    last_finished_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_message: Optional[str] = None


# ---------- Personal tools ----------

class PersonalToolBase(BaseModel):
    name: str
    type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    unique_code: str
    purchase_date: Optional[datetime] = None
    purchase_price: Optional[float] = Field(default=None, ge=0)
    warranty_expiration_date: Optional[datetime] = None
    last_control_date: Optional[datetime] = None
    state: int = Field(default=5, ge=0, le=5)


class PersonalToolCreate(PersonalToolBase):
    pass


class PersonalToolUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    unique_code: Optional[str] = None
    purchase_date: Optional[datetime] = None
    purchase_price: Optional[float] = Field(default=None, ge=0)
    warranty_expiration_date: Optional[datetime] = None
    last_control_date: Optional[datetime] = None
    state: Optional[int] = Field(default=None, ge=0, le=5)


class PersonalToolStateUpdate(BaseModel):
    state: int = Field(ge=0, le=5)
    state_reason: ToolStateReason = ToolStateReason.normal
    state_comment: Optional[str] = None


class PersonalToolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    current_holder_id: Optional[int] = None
    name: str
    type: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    unique_code: str
    photo_path: Optional[str] = None
    purchase_date: Optional[datetime] = None
    purchase_price: Optional[float] = None
    warranty_expiration_date: Optional[datetime] = None
    last_control_date: Optional[datetime] = None
    state: int
    state_reason: ToolStateReason
    state_comment: Optional[str] = None
    state_photo_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PersonalToolLookup(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    unique_code: str
    owner_id: int
    owner_name: str
    current_holder_id: Optional[int] = None


# ---------- Agency tools ----------

class AgencyToolBase(BaseModel):
    name: str
    type: Optional[str] = None
    brand: Optional[str] = None
    unique_code: str
    description: Optional[str] = None
    serial_number: Optional[str] = None
    purchase_date: Optional[datetime] = None
    purchase_price: float = Field(default=0.0, ge=0)
    daily_rate: Optional[float] = Field(default=None, ge=0)
    warranty_expiration_date: Optional[datetime] = None
    comment: Optional[str] = None
    state: int = Field(default=5, ge=0, le=5)
    agency_number: Optional[str] = None


class AgencyToolCreate(AgencyToolBase):
    pass


class AgencyToolUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    brand: Optional[str] = None
    unique_code: Optional[str] = None
    description: Optional[str] = None
    serial_number: Optional[str] = None
    purchase_date: Optional[datetime] = None
    purchase_price: Optional[float] = Field(default=None, ge=0)
    warranty_expiration_date: Optional[datetime] = None
    comment: Optional[str] = None
    state: Optional[int] = Field(default=None, ge=0, le=5)
    status: Optional[AgencyToolStatus] = None
    loss_reason: Optional[AgencyLossReason] = None
    assigned_to_id: Optional[int] = None
    last_control_date: Optional[datetime] = None
    parent_tool_id: Optional[int] = None
    daily_rate: Optional[float] = Field(default=None, ge=0)


class AgencyToolControlUpdate(BaseModel):
    state: int = Field(ge=0, le=5)
    status: AgencyToolStatus
    loss_reason: Optional[AgencyLossReason] = None
    comment: Optional[str] = None
    serial_number: Optional[str] = None
    description: Optional[str] = None


class AgencyToolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: Optional[str] = None
    brand: Optional[str] = None
    unique_code: str
    photo_path: Optional[str] = None
    state: int
    status: AgencyToolStatus
    loss_reason: Optional[AgencyLossReason] = None
    assigned_to_id: Optional[int] = None
    agency_number: Optional[str] = None
    description: Optional[str] = None
    serial_number: Optional[str] = None
    purchase_date: Optional[datetime] = None
    purchase_price: float
    warranty_expiration_date: Optional[datetime] = None
    comment: Optional[str] = None
    last_control_date: Optional[datetime] = None
    home_agency: Optional[str] = None
    exit_reason: Optional[str] = None
    exit_date: Optional[datetime] = None
    exit_note: Optional[str] = None
    residual_value: Optional[float] = None
    parent_tool_id: Optional[int] = None
    daily_rate: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class FinancialTypeSummary(BaseModel):
    label: str
    count: int
    total_value: float


class RecentPurchase(BaseModel):
    name: str
    type: Optional[str] = None
    purchase_price: Optional[float] = None
    purchase_date: Optional[datetime] = None


class FinancialSummary(BaseModel):
    total_value: float
    total_count: int
    by_type: List[FinancialTypeSummary]
    by_agency: Optional[List[FinancialTypeSummary]] = None
    recent_purchases: List[RecentPurchase]


# ---------- Loans ----------

class LoanCreate(BaseModel):
    tool_id: int
    site: Optional[str] = None
    comment: Optional[str] = None
    start_datetime: datetime
    end_datetime_planned: datetime
    state_before: Optional[int] = Field(default=None, ge=0, le=5)


class LoanReturn(BaseModel):
    state_after: int = Field(ge=0, le=5)
    comment_return: Optional[str] = None


class LoanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tool_id: int
    borrower_id: int
    site: Optional[str] = None
    comment: Optional[str] = None
    start_datetime: datetime
    end_datetime_planned: datetime
    actual_return_datetime: Optional[datetime] = None
    state_before: Optional[int] = None
    state_after: Optional[int] = None
    comment_return: Optional[str] = None
    photo_return_path: Optional[str] = None
    status: LoanStatus
    created_at: datetime


# ---------- Transfers ----------

class TransferCreate(BaseModel):
    tool_id: Optional[int] = None
    agency_tool_id: Optional[int] = None
    to_external_name: str
    to_external_type: ExternalRecipientType = ExternalRecipientType.autre
    to_external_company: Optional[str] = None
    site_code: Optional[str] = None
    client_code: Optional[str] = None
    attached_to_id: Optional[int] = None
    planned_return_date: Optional[datetime] = None
    comment: Optional[str] = None
    to_external_email: Optional[str] = None
    to_external_phone: Optional[str] = None


class TransferReturn(BaseModel):
    state_after: int = Field(ge=0, le=5)
    comment: Optional[str] = None


class TransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tool_id: Optional[int] = None
    agency_tool_id: Optional[int] = None
    from_user_id: int
    to_external_name: str
    to_external_type: ExternalRecipientType
    to_external_company: Optional[str] = None
    site_code: Optional[str] = None
    client_code: Optional[str] = None
    attached_to_id: Optional[int] = None
    transfer_date: datetime
    planned_return_date: Optional[datetime] = None
    actual_return_date: Optional[datetime] = None
    state_before: Optional[int] = None
    state_after: Optional[int] = None
    comment: Optional[str] = None
    status: TransferStatus
    to_external_email: Optional[str] = None
    to_external_phone: Optional[str] = None
    signed_at: Optional[datetime] = None


# ---------- Peer transfers ----------

class PeerTransferCreate(BaseModel):
    direction: Literal["je_donne", "je_recois"]
    tool_code: str
    counterpart_id: int
    planned_return_date: Optional[datetime] = None
    comment: Optional[str] = None


class PeerTransferReturn(BaseModel):
    state_after: int = Field(ge=0, le=5)
    comment: Optional[str] = None


class PeerTransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tool_id: int
    from_user_id: int
    to_user_id: int
    declared_by_id: int
    status: PeerTransferStatus
    transfer_date: datetime
    confirmed_at: Optional[datetime] = None
    planned_return_date: Optional[datetime] = None
    actual_return_date: Optional[datetime] = None
    state_before: Optional[int] = None
    state_after: Optional[int] = None
    comment: Optional[str] = None


# ---------- Settings ----------

class SettingsUpdate(BaseModel):
    magasinier_email: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: Optional[bool] = None
    smtp_from_email: Optional[str] = None


class SettingsOut(BaseModel):
    magasinier_email: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_username: Optional[str] = None
    smtp_password_set: bool
    smtp_use_tls: Optional[bool] = None
    smtp_from_email: Optional[str] = None


# ---------- Epi ----------

class EpiBase(BaseModel):
    name: str
    type: Optional[str] = None
    brand: Optional[str] = None
    unique_code: str
    expiration_date: Optional[datetime] = None
    state: int = Field(default=5, ge=0, le=5)
    comment: Optional[str] = None
    assigned_to_id: Optional[int] = None
    agency_number: Optional[str] = None


class EpiCreate(EpiBase):
    pass


class EpiUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    brand: Optional[str] = None
    unique_code: Optional[str] = None
    expiration_date: Optional[datetime] = None
    state: Optional[int] = Field(default=None, ge=0, le=5)
    comment: Optional[str] = None
    assigned_to_id: Optional[int] = None
    last_control_date: Optional[datetime] = None


class EpiControlUpdate(BaseModel):
    state: int = Field(ge=0, le=5)
    comment: Optional[str] = None


class EpiOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: Optional[str] = None
    brand: Optional[str] = None
    unique_code: str
    photo_path: Optional[str] = None
    agency_number: Optional[str] = None
    assigned_to_id: Optional[int] = None
    state: int
    expiration_date: Optional[datetime] = None
    last_control_date: Optional[datetime] = None
    comment: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ---------- State history ----------

class StateHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tool_kind: str
    tool_id: int
    old_state: Optional[int] = None
    new_state: int
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    source: str
    comment: Optional[str] = None
    changed_by_id: Optional[int] = None
    changed_at: datetime
