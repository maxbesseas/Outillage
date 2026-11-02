from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint

from .database import Base


class LoanEvent(Base):
    __tablename__ = "loan_events"

    id = Column(Integer, primary_key=True)
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)  # created | modified | extended | checkout | returned | cancelled | approved | rejected | no_show
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ToolBlackout(Base):
    __tablename__ = "tool_blackouts"

    id = Column(Integer, primary_key=True)
    tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=False, index=True)
    start_datetime = Column(DateTime, nullable=False)
    end_datetime = Column(DateTime, nullable=False)
    reason = Column(String, nullable=False, default="autre")  # maintenance | etalonnage | controle | autre
    note = Column(Text, nullable=True)
    source = Column(String, nullable=False, default="manual")  # manual | auto
    ref = Column(String, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ToolKit(Base):
    __tablename__ = "tool_kits"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    agency_number = Column(String, nullable=True, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ToolKitItem(Base):
    __tablename__ = "tool_kit_items"

    id = Column(Integer, primary_key=True)
    kit_id = Column(Integer, ForeignKey("tool_kits.id"), nullable=False, index=True)
    tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=False)

    __table_args__ = (UniqueConstraint("kit_id", "tool_id", name="uq_kit_tool"),)


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id = Column(Integer, primary_key=True)
    tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    start_datetime = Column(DateTime, nullable=False)
    end_datetime = Column(DateTime, nullable=False)
    site = Column(String, nullable=True)
    status = Column(String, nullable=False, default="waiting")  # waiting | offered | fulfilled | cancelled | expired
    created_at = Column(DateTime, default=datetime.utcnow)
    offered_at = Column(DateTime, nullable=True)
    offer_expires_at = Column(DateTime, nullable=True)
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=True)


class ReservationRule(Base):
    __tablename__ = "reservation_rules"

    id = Column(Integer, primary_key=True)
    tool_type = Column(String, nullable=True)
    agency_tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=True)
    requires_approval = Column(Boolean, nullable=False, default=False)
    max_days = Column(Integer, nullable=True)


class AgencyTransfer(Base):
    __tablename__ = "agency_transfers"

    id = Column(Integer, primary_key=True)
    tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=False, index=True)
    from_agency = Column(String, nullable=False)
    to_agency = Column(String, nullable=False)
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending | accepted | rejected | returned | cancelled
    temporary = Column(Boolean, nullable=False, default=False)
    planned_return_date = Column(DateTime, nullable=True)
    decided_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    returned_at = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
