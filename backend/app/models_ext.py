from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


# ---------------------------------------------------------------- réglages

class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)


# ---------------------------------------------------------------- phase 1

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="info")
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    entity_kind = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    link = Column(String, nullable=True)
    dedup_key = Column(String, nullable=True)
    in_app = Column(Boolean, nullable=False, default=True)
    email_wanted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    read_at = Column(DateTime, nullable=True)
    emailed_at = Column(DateTime, nullable=True)
    pushed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "dedup_key", name="uq_notification_dedup"),
        Index("ix_notifications_user_read", "user_id", "read_at"),
    )


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String, nullable=False)
    in_app = Column(Boolean, nullable=False, default=True)
    email = Column(Boolean, nullable=False, default=False)
    push = Column(Boolean, nullable=False, default=True)

    __table_args__ = (UniqueConstraint("user_id", "type", name="uq_notification_pref"),)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    endpoint = Column(String, unique=True, nullable=False)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
