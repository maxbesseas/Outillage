from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint

from .database import Base


class Site(Base):
    __tablename__ = "sites"

    id = Column(Integer, primary_key=True)
    agency_number = Column(String, nullable=True, index=True)
    name = Column(String, nullable=False)
    code = Column(String, nullable=True)
    client = Column(String, nullable=True)
    address = Column(String, nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    status = Column(String, nullable=False, default="actif")  # actif | clos
    manager_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)
    closed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    __table_args__ = (UniqueConstraint("agency_number", "name", name="uq_site_agency_name"),)
