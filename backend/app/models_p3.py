from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint

from .database import Base


class IdempotencyKey(Base):
    """Réponse mémorisée d'une écriture rejouée par la file hors ligne (évite les doublons)."""

    __tablename__ = "idempotency_keys"

    id = Column(Integer, primary_key=True)
    key = Column(String, nullable=False)
    username = Column(String, nullable=False)
    method = Column(String, nullable=False)
    path = Column(String, nullable=False)
    status_code = Column(Integer, nullable=False)
    content_type = Column(String, nullable=True)
    body = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (UniqueConstraint("username", "key", name="uq_idem_user_key"),)


class ToolPhoto(Base):
    __tablename__ = "tool_photos"

    id = Column(Integer, primary_key=True)
    tool_kind = Column(String, nullable=False)
    tool_id = Column(Integer, nullable=False)
    path = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="etat")  # reference | etat | dommage | autre
    caption = Column(Text, nullable=True)
    taken_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_tool_photos_tool", "tool_kind", "tool_id"),)


class ToolLabel(Base):
    """Suivi d'impression des étiquettes (permet de ne réimprimer que les manquantes)."""

    __tablename__ = "tool_labels"

    id = Column(Integer, primary_key=True)
    tool_kind = Column(String, nullable=False)
    tool_id = Column(Integer, nullable=False)
    printed_at = Column(DateTime, default=datetime.utcnow)
    printed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    __table_args__ = (UniqueConstraint("tool_kind", "tool_id", name="uq_label_tool"),)
