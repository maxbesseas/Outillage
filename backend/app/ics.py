"""Génération iCalendar (RFC 5545) minimale : événements simples en UTC."""
from datetime import datetime
from typing import Iterable, Optional

PRODID = "-//Fauche//Gestion Outillage//FR"


def escape(text: Optional[str]) -> str:
    if not text:
        return ""
    return (
        str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Plie les lignes à 75 octets (RFC 5545 §3.1) sans couper un caractère UTF-8."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current = [], b""
    limit = 75
    for char in line:
        encoded = char.encode("utf-8")
        if len(current) + len(encoded) > limit:
            parts.append(current.decode("utf-8"))
            current, limit = b"", 74
        current += encoded
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def event(uid: str, start: datetime, end: datetime, summary: str, description: str = "", location: str = "",
          status: str = "CONFIRMED", now: Optional[datetime] = None) -> Iterable[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp(now or datetime.utcnow())}",
        f"DTSTART:{stamp(start)}",
        f"DTEND:{stamp(end)}",
        f"SUMMARY:{escape(summary)}",
        f"STATUS:{status}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{escape(description)}")
    if location:
        lines.append(f"LOCATION:{escape(location)}")
    lines.append("END:VEVENT")
    return lines


def calendar(events: Iterable[Iterable[str]], name: str = "Fauché — Réservations") -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{escape(name)}"]
    for ev in events:
        lines.extend(ev)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"
