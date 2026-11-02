"""Documents PDF : bon de sortie (réservation) et décharge de responsabilité (prêt externe)."""
import json
from datetime import datetime
from typing import Optional

from .pdf import BLUE, GRAY, Pdf

MAX_SIGNATURE_POINTS = 6000


def validate_signature(signature: dict) -> dict:
    """Signature = traits vectoriels : {"w": int, "h": int, "strokes": [[[x, y], ...], ...]}."""
    if not isinstance(signature, dict):
        raise ValueError("Signature invalide")
    width, height, strokes = signature.get("w"), signature.get("h"), signature.get("strokes")
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)) or width <= 0 or height <= 0:
        raise ValueError("Dimensions de signature invalides")
    if not isinstance(strokes, list) or not strokes:
        raise ValueError("Signature vide")
    total = 0
    clean = []
    for stroke in strokes:
        if not isinstance(stroke, list):
            raise ValueError("Signature invalide")
        points = []
        for point in stroke:
            if not (isinstance(point, list) and len(point) == 2 and all(isinstance(v, (int, float)) for v in point)):
                raise ValueError("Signature invalide")
            points.append([round(float(point[0]), 1), round(float(point[1]), 1)])
        total += len(points)
        if total > MAX_SIGNATURE_POINTS:
            raise ValueError("Signature trop détaillée")
        if points:
            clean.append(points)
    if not clean:
        raise ValueError("Signature vide")
    return {"w": float(width), "h": float(height), "strokes": clean}


def draw_signature(pdf: Pdf, signature_json: Optional[str], x: float, y: float, width: float, height: float):
    """Dessine la signature dans le cadre (x, y) = coin bas-gauche."""
    pdf.rect(x, y, width, height, stroke=(0.7, 0.72, 0.78))
    if not signature_json:
        return
    try:
        data = json.loads(signature_json)
    except ValueError:
        return
    sw, sh = data["w"], data["h"]
    scale = min((width - 8) / sw, (height - 8) / sh)
    for stroke in data["strokes"]:
        points = [(x + 4 + px * scale, y + height - 4 - py * scale) for px, py in stroke]
        if len(points) == 1:
            points.append((points[0][0] + 0.5, points[0][1]))
        pdf.polyline(points, width=1.2)


def _fmt(dt: Optional[datetime]) -> str:
    return dt.strftime("%d/%m/%Y %H:%M") if dt else "-"


def voucher_pdf(loan, tool, borrower, issuer_name: Optional[str], agency: Optional[str]) -> bytes:
    pdf = Pdf(f"Bon de sortie n°{loan.id}")
    pdf.heading("Bon de sortie de matériel", 18)
    pdf.paragraph(f"Fauché — Agence {agency or '-'}   |   Bon n°{loan.id}   |   Édité le {_fmt(datetime.utcnow())} (UTC)", color=GRAY)
    pdf.spacer(8)
    pdf.heading("Matériel", 12)
    pdf.key_values([
        ("Désignation", tool.name), ("Code", tool.unique_code), ("Type", tool.type or "-"), ("Marque", tool.brand or "-"),
        ("N° de série", tool.serial_number or "-"),
        ("État au départ", f"{loan.state_before if loan.state_before is not None else tool.state}/5"),
    ])
    pdf.spacer(6)
    pdf.heading("Emprunt", 12)
    pdf.key_values([
        ("Emprunteur", borrower.full_name), ("Chantier", loan.site or "-"),
        ("Du", _fmt(loan.start_datetime)), ("Retour prévu", _fmt(loan.end_datetime_planned)),
        ("Remis par", issuer_name or "-"), ("Commentaire", loan.comment or "-"),
    ])
    pdf.spacer(10)
    pdf.paragraph(
        "L'emprunteur reconnaît avoir reçu le matériel ci-dessus en bon état apparent, s'engage à l'utiliser conformément "
        "à sa destination, à signaler toute anomalie et à le restituer à la date prévue.", size=9.5,
    )
    pdf.spacer(12)
    pdf.ensure(110)
    pdf.text(pdf.margin, pdf.y - 10, f"Signature de l'emprunteur{' : ' + loan.signed_name if loan.signed_name else ''}", size=9, bold=True, color=BLUE)
    draw_signature(pdf, loan.signature_json, pdf.margin, pdf.y - 100, 240, 80)
    pdf.text(pdf.margin + 280, pdf.y - 10, f"Date : {_fmt(loan.signed_at)}", size=9, color=GRAY)
    return pdf.output()


def discharge_pdf(transfer, tool, lender_name: str, is_agency_tool: bool, agency: Optional[str]) -> bytes:
    pdf = Pdf(f"Décharge n°{transfer.id}")
    pdf.heading("Décharge de responsabilité — prêt de matériel", 17)
    pdf.paragraph(f"Fauché — Agence {agency or '-'}   |   Décharge n°{transfer.id}   |   Édité le {_fmt(datetime.utcnow())} (UTC)", color=GRAY)
    pdf.spacer(8)
    value = tool.purchase_price if getattr(tool, "purchase_price", None) is not None else None
    pdf.heading("Matériel prêté", 12)
    pdf.key_values([
        ("Désignation", tool.name), ("Code", tool.unique_code), ("Marque / modèle", " ".join(filter(None, [tool.brand, getattr(tool, "model", None)])) or "-"),
        ("N° de série", getattr(tool, "serial_number", None) or "-"),
        ("Valeur estimée", f"{value:.2f} €" if value is not None else "non renseignée"),
        ("État au départ", f"{transfer.state_before if transfer.state_before is not None else tool.state}/5"),
    ])
    pdf.spacer(6)
    pdf.heading("Bénéficiaire", 12)
    pdf.key_values([
        ("Nom", transfer.to_external_name), ("Catégorie", transfer.to_external_type.value.replace("_", " ")),
        ("Entreprise", transfer.to_external_company or "-"), ("Email", transfer.to_external_email or "-"),
        ("Téléphone", transfer.to_external_phone or "-"), ("Chantier", transfer.site_code or "-"),
        ("Code client", transfer.client_code or "-"),
    ])
    pdf.spacer(6)
    pdf.heading("Prêt", 12)
    pdf.key_values([
        ("Prêté par", lender_name), ("Date du prêt", _fmt(transfer.transfer_date)),
        ("Retour prévu", _fmt(transfer.planned_return_date)), ("Commentaire", transfer.comment or "-"),
    ])
    pdf.spacer(10)
    pdf.paragraph(
        "Le bénéficiaire reconnaît avoir reçu le matériel désigné ci-dessus, en assume la garde et la responsabilité pendant "
        "toute la durée du prêt, s'engage à le restituer à la date convenue dans l'état où il l'a reçu (usure normale exceptée), "
        "et à indemniser Fauché à hauteur de la valeur indiquée en cas de perte, de vol ou de détérioration non justifiée.", size=9.5,
    )
    pdf.spacer(12)
    pdf.ensure(110)
    pdf.text(pdf.margin, pdf.y - 10, f"Signature du bénéficiaire{' : ' + transfer.signed_name if transfer.signed_name else ''}", size=9, bold=True, color=BLUE)
    draw_signature(pdf, transfer.signature_json, pdf.margin, pdf.y - 100, 240, 80)
    pdf.text(pdf.margin + 280, pdf.y - 10, f"Date : {_fmt(transfer.signed_at)}", size=9, color=GRAY)
    return pdf.output()
