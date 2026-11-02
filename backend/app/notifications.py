import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from .models import Settings

WORN_STATE_THRESHOLD = 2


def get_settings(db: Session) -> Settings:
    settings = db.query(Settings).filter(Settings.id == 1).first()
    if settings is None:
        settings = Settings(id=1)
        db.add(settings)
        db.flush()
    return settings


def send_email(
    db: Session,
    to_address: str,
    subject: str,
    body: str,
    html: Optional[str] = None,
    attachments: Optional[List[Tuple[str, bytes, str]]] = None,
) -> Tuple[bool, str]:
    settings = get_settings(db)

    if not to_address or not settings.smtp_host:
        return False, "Destinataire ou serveur SMTP non configuré"

    try:
        sender = settings.smtp_from_email or settings.smtp_username or settings.magasinier_email or to_address
        if html or attachments:
            msg = MIMEMultipart("mixed")
            alternative = MIMEMultipart("alternative")
            alternative.attach(MIMEText(body, "plain", "utf-8"))
            if html:
                alternative.attach(MIMEText(html, "html", "utf-8"))
            msg.attach(alternative)
            for filename, content, mimetype in attachments or []:
                part = MIMEApplication(content, _subtype=mimetype.split("/")[-1])
                part.add_header("Content-Disposition", "attachment", filename=filename)
                msg.attach(part)
        else:
            msg = MIMEText(body, _charset="utf-8")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_address

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port or 587, timeout=10) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password or "")
            server.sendmail(sender, [to_address], msg.as_string())

        return True, "ok"
    except Exception as exc:
        return False, f"Échec envoi email : {exc}"


def notify_magasinier(db: Session, subject: str, body: str) -> Tuple[bool, str]:
    settings = get_settings(db)
    if not settings.magasinier_email:
        return False, "Destinataire ou serveur SMTP non configuré"
    return send_email(db, settings.magasinier_email, subject, body)
