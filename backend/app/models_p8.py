from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from .database import Base


class ImportReport(Base):
    __tablename__ = "import_reports"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    agency_number = Column(String, nullable=True, index=True)
    target = Column(String, nullable=False)  # agency_tools | epi | users
    filename = Column(String, nullable=True)
    mode = Column(String, nullable=False)  # simulate | commit
    created_count = Column(Integer, nullable=False, default=0)
    updated_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    details = Column(Text, nullable=True)  # JSON : lignes en erreur / avertissements
    created_at = Column(DateTime, default=datetime.utcnow)


class ExcelSyncTask(Base):
    """Mises à jour du fichier Excel d'agence à rejouer (fichier ouvert/verrouillé, absent…)."""

    __tablename__ = "excel_sync_tasks"

    id = Column(Integer, primary_key=True)
    agency_number = Column(String, nullable=True, index=True)
    tool_id = Column(Integer, nullable=False)
    action = Column(String, nullable=False)  # append | update | exit
    payload = Column(Text, nullable=True)  # JSON (ancien code pour une sortie de parc)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending | done | failed
    created_at = Column(DateTime, default=datetime.utcnow)
    done_at = Column(DateTime, nullable=True)
