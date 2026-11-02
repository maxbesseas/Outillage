from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from .database import Base


class DepreciationPolicy(Base):
    """Durée d'amortissement linéaire par type d'outil (type NULL = règle par défaut)."""

    __tablename__ = "depreciation_policies"

    id = Column(Integer, primary_key=True)
    type = Column(String, nullable=True, unique=True)
    years = Column(Float, nullable=False)
    residual_pct = Column(Float, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class LossRecord(Base):
    __tablename__ = "loss_records"

    id = Column(Integer, primary_key=True)
    tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=False, index=True)
    agency_number = Column(String, nullable=True, index=True)
    kind = Column(String, nullable=False)  # vol | perte | casse | litige
    occurred_at = Column(DateTime, nullable=False)
    responsible_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True)
    circumstances = Column(Text, nullable=True)
    declared_value = Column(Float, nullable=False, default=0)
    police_report_ref = Column(String, nullable=True)
    insurance_status = Column(String, nullable=False, default="none")  # none | declared | accepted | refused
    insurance_ref = Column(String, nullable=True)
    refunded_amount = Column(Float, nullable=False, default=0)
    litigation_status = Column(String, nullable=False, default="none")  # none | open | closed
    litigation_note = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Budget(Base):
    __tablename__ = "budgets"

    id = Column(Integer, primary_key=True)
    agency_number = Column(String, nullable=True, index=True)
    year = Column(Integer, nullable=False)
    category = Column(String, nullable=False)  # achats | reparations | pertes
    amount = Column(Float, nullable=False, default=0)
    updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("agency_number", "year", "category", name="uq_budget_line"),)


class ApiKey(Base):
    """Clé d'accès en lecture seule aux rapports (seul le hachage est conservé)."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    prefix = Column(String, nullable=False)
    key_hash = Column(String, nullable=False, unique=True)
    agency_number = Column(String, nullable=True)  # NULL = toutes les agences
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
