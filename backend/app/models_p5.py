from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text

from .database import Base


class MaintenanceTicket(Base):
    __tablename__ = "maintenance_tickets"

    id = Column(Integer, primary_key=True)
    tool_kind = Column(String, nullable=False)
    tool_id = Column(Integer, nullable=False)
    agency_number = Column(String, nullable=True, index=True)
    opened_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    opened_at = Column(DateTime, default=datetime.utcnow)
    category = Column(String, nullable=False, default="panne")  # casse | panne | accessoire_manquant | usure | perte | vol | autre
    severity = Column(String, nullable=False, default="moyenne")  # faible | moyenne | haute | critique
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="ouvert")
    assigned_to_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    provider = Column(String, nullable=True)  # interne | fournisseur | sav
    warranty_claim = Column(Boolean, nullable=False, default=False)
    warranty_case_number = Column(String, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    back_at = Column(DateTime, nullable=True)
    estimated_cost = Column(Float, nullable=True)
    actual_cost = Column(Float, nullable=True)
    parts = Column(Text, nullable=True)
    expected_return_date = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    resolution = Column(Text, nullable=True)
    auto_opened = Column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_tickets_tool", "tool_kind", "tool_id"),)


class MaintenanceComment(Base):
    __tablename__ = "maintenance_comments"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("maintenance_tickets.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    body = Column(Text, nullable=False)
    kind = Column(String, nullable=False, default="comment")  # comment | status
    created_at = Column(DateTime, default=datetime.utcnow)


class MaintenanceAttachment(Base):
    __tablename__ = "maintenance_attachments"

    id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("maintenance_tickets.id"), nullable=False, index=True)
    path = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="photo")  # photo | devis | facture | autre
    filename = Column(String, nullable=True)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ToolAccessory(Base):
    __tablename__ = "tool_accessories"

    id = Column(Integer, primary_key=True)
    tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    required = Column(Boolean, nullable=False, default=True)
    note = Column(Text, nullable=True)


class ExitRequest(Base):
    __tablename__ = "exit_requests"

    id = Column(Integer, primary_key=True)
    tool_id = Column(Integer, ForeignKey("agency_tools.id"), nullable=False, index=True)
    requested_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reason = Column(String, nullable=False)  # vendu | rebut | donne | vole | perdu
    exit_date = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)
    residual_value = Column(Float, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending | approved | rejected
    decided_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class StockItem(Base):
    __tablename__ = "stock_items"

    id = Column(Integer, primary_key=True)
    agency_number = Column(String, nullable=True, index=True)
    name = Column(String, nullable=False)
    reference = Column(String, nullable=True)
    unit = Column(String, nullable=False, default="pièce")
    quantity = Column(Float, nullable=False, default=0)
    threshold = Column(Float, nullable=False, default=0)
    location = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("stock_items.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)  # entree | sortie | inventaire
    quantity = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    site = Column(String, nullable=True)
    site_id = Column(Integer, ForeignKey("sites.id"), nullable=True, index=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
