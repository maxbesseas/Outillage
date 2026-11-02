from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from .database import Base


class AssistantMessage(Base):
    """Journal des échanges avec l'assistant (retours d'utilité et questions sans réponse)."""

    __tablename__ = "assistant_messages"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    source = Column(String, nullable=False, default="local")  # claude | local
    tools_used = Column(String, nullable=True)  # JSON : noms des outils appelés
    unanswered = Column(Boolean, nullable=False, default=False)
    feedback = Column(String, nullable=True)  # up | down
    feedback_comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AssistantAction(Base):
    """Action proposée par l'assistant : n'est exécutée qu'après confirmation explicite de l'utilisateur."""

    __tablename__ = "assistant_actions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("assistant_messages.id"), nullable=True)
    action = Column(String, nullable=False)
    params = Column(Text, nullable=False)  # JSON validé côté serveur
    summary = Column(Text, nullable=False)  # rédigé par le serveur, pas par le modèle
    status = Column(String, nullable=False, default="pending")  # pending | confirmed | cancelled | failed
    result = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)


class AssistantUsage(Base):
    __tablename__ = "assistant_usage"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    day = Column(String, nullable=False)  # AAAA-MM-JJ (UTC)
    tokens = Column(Integer, nullable=False, default=0)
    messages = Column(Integer, nullable=False, default=0)

    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_assistant_usage"),)
