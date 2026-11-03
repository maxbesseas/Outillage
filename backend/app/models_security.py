from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from .database import Base


class RateEvent(Base):
    """Compteur partagé des limites anti-abus (voir limits.py), purgé chaque jour."""

    __tablename__ = "rate_events"
    __table_args__ = (Index("ix_rate_events_key_created", "key", "created_at"),)

    id = Column(Integer, primary_key=True)
    key = Column(String(200), nullable=False)
    amount = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CharterAcceptance(Base):
    """Preuve d'acceptation de la charte : qui, quelle version, quand."""

    __tablename__ = "charter_acceptances"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    accepted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ip = Column(String, nullable=True)
