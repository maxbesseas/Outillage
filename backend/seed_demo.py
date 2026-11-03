"""Données de démonstration, entièrement fictives, pour présenter toutes les fonctions de l'application.

Usage, depuis backend/, base préparée par python -m app.db_setup :
    python seed_demo.py --yes       ajoute les données et affiche une seule fois le mot de passe des comptes de démonstration
    python seed_demo.py --reset     retire uniquement ces données

Les données existantes ne sont pas modifiées. Tout se repère par le préfixe DEMO- des codes, l'identifiant demo.* des comptes
et les types d'outils de TYPES : --reset s'appuie sur ces marques.
"""
import json
import random
import secrets
import sys
from datetime import datetime, timedelta

from sqlalchemy import or_

from app import charter, database, models_ext, models_p3, models_p9, models_security, utils  # noqa: F401
from app.auth import hash_password
from app.models import (
    Agency, AgencyTool, AgencyToolStatus, AuditLog, Epi, ExternalRecipientType, Loan, LoanStatus, LoginAttempt, PeerTransfer,
    PeerTransferStatus, PersonalTool, RefreshToken, StateHistory, ToolKind, ToolStateReason, Transfer, TransferStatus, User, UserRole,
)
from app.models_ext import Notification, NotificationPreference
from app.models_p2 import Calibration, Inspection, InspectionPolicy, InspectionTemplate, QualificationType, ToolRequirement, UserQualification
from app.models_p3 import ToolLabel
from app.models_p4 import AgencyTransfer, LoanEvent, ReservationRule, ToolBlackout, ToolKit, ToolKitItem, WaitlistEntry
from app.models_p5 import ExitRequest, MaintenanceComment, MaintenanceTicket, StockItem, StockMovement, ToolAccessory
from app.models_p6 import Site
from app.models_p7 import Budget, DepreciationPolicy, LossRecord
from app.models_security import CharterAcceptance

AGENCIES = ("Projets", "Lyon", "Nantes")
DEMO_AGENCY_CODE = "DEMO"
MARK_AGENT = "seed-demo"
DEMO_DATE = datetime(2000, 1, 1)

# Types propres à la démonstration : leurs règles de contrôle ne touchent aucun outil existant.
CATALOGUE = [
    ("Perçage", "Perforateur SDS+", "Bosch", 389, 12), ("Perçage", "Perceuse visseuse 18 V", "Makita", 245, 6), ("Perçage", "Carotteuse béton", "Hilti", 1850, 45),
    ("Découpe", "Meuleuse 230 mm", "Metabo", 210, 9), ("Découpe", "Scie sabre", "DeWalt", 279, 10), ("Découpe", "Scie circulaire", "Festool", 620, 18),
    ("Mesure", "Laser rotatif", "Leica", 1490, 35), ("Mesure", "Télémètre laser", "Bosch", 169, 5), ("Mesure", "Détecteur de réseaux", "Radiodetection", 2300, 55),
    ("Mesure", "Multimètre", "Fluke", 340, 8), ("Échafaudage", "Échafaudage roulant 6 m", "Altrex", 2150, 40), ("Échafaudage", "Échelle télescopique", "Hailo", 185, 4),
    ("Nacelle", "Nacelle ciseaux 8 m", "Haulotte", 14500, 130), ("Nacelle", "Nacelle araignée 15 m", "Manitou", 38000, 260), ("Levage", "Palan électrique 500 kg", "Yale", 980, 22),
    ("Levage", "Chariot télescopique", "Merlo", 62000, 340), ("Énergie", "Groupe électrogène 6 kVA", "SDMO", 2650, 38), ("Énergie", "Compresseur 50 L", "Lacmé", 690, 15),
    ("Soudure", "Poste à souder MIG", "Lincoln", 1320, 28), ("Soudure", "Chalumeau oxyacétylénique", "Air Liquide", 420, 11),
]
TYPES = sorted({c[0] for c in CATALOGUE})
EPI_CATALOGUE = [
    ("Casque", "Casque de chantier", "Petzl"), ("Harnais", "Harnais antichute", "Petzl"), ("Harnais", "Longe double absorbeur", "Honeywell"),
    ("Gants", "Gants anti-coupure", "Mapa"), ("Lunettes", "Lunettes de protection", "Uvex"), ("Protection auditive", "Casque antibruit", "3M"),
    ("Chaussures", "Chaussures de sécurité", "Parade"), ("Masque", "Demi-masque FFP3", "3M"), ("Détecteur", "Détecteur de gaz 4 voies", "Dräger"),
]
PEOPLE = {
    "Projets": ("Claire Vautrin", ["Julien Morvan", "Sofia Benali"], ["Kevin Lemoine", "Moussa Traoré", "Paulo Ferreira", "Anthony Guérin", "Nabil Haddad"], "Hélène Roussel"),
    "Lyon": ("Marc Delorme", ["Inès Carpentier", "Thomas Giraud"], ["Lucas Perrin", "Yanis Cherif", "Damien Roche", "Jordan Faure"], "Sandrine Mercier"),
    "Nantes": ("Anne Le Goff", ["Pierre Kerbrat", "Laura Masson"], ["Erwan Tanguy", "Mathis Colin", "Samir Aouadi", "Hugo Bernier"], "Gildas Nedelec"),
}
SITES = {
    "Projets": [("240317", "Réfection toiture groupe scolaire", "Commune de Valmont", "clos"), ("241128", "Extension entrepôt logistique", "Logis Ouest", "clos"),
                ("250214", "Rénovation parking souterrain", "SCI des Tilleuls", "actif"), ("250906", "Pose de façade bureaux Horizon", "Horizon Immobilier", "actif"),
                ("251020", "Mise aux normes atelier", "Mécanique Dubreuil", "actif")],
    "Lyon": [("240502", "Ravalement résidence Les Acacias", "Syndic Rhône Habitat", "clos"), ("250118", "Passerelle piétonne quai Sud", "Métropole fictive", "actif"),
             ("250733", "Réhabilitation lycée technique", "Région fictive", "actif"), ("251102", "Local technique hôpital", "Centre de soins Saint-Luc", "actif")],
    "Nantes": [("240909", "Quai de chargement port sec", "Atlantique Fret", "clos"), ("250305", "Charpente halle des sports", "Commune de Bellevue-sur-Loire", "actif"),
               ("250811", "Réseaux zone d'activités", "Aménagement Estuaire", "actif")],
}
EXTERNAL = [("Atelier Marchand", "Bruno Marchand", ExternalRecipientType.sous_traitant), ("Élec'Sud", "Fatima Zerrouki", ExternalRecipientType.sous_traitant),
            ("Intérim Plus", "Loïc Barbier", ExternalRecipientType.interimaire), ("Peinture Vasseur", "Émilie Vasseur", ExternalRecipientType.sous_traitant),
            ("Client du chantier", "Gérard Pons", ExternalRecipientType.autre)]
LOAN_COMMENTS = ["Pose des réservations niveau -1", "Reprise après intempéries", "Intervention urgente", "Levée de réserves", "Chantier de nuit", None, None, None]
RETURN_COMMENTS = ["RAS", "Rendu propre", "Forets usés à remplacer", "Câble légèrement abîmé", "Batterie faible en fin de journée", None]
PROBLEMS = {"panne": "Ne démarre plus après une coupure", "casse": "Carter fendu après une chute", "usure": "Charbons à remplacer", "accessoire_manquant": "Mallette sans chargeur",
            "autre": "Bruit anormal en charge"}
SIGNATURE = json.dumps({"w": 300.0, "h": 100.0, "strokes": [[[20.0, 60.0], [60.0, 25.0], [95.0, 70.0], [140.0, 30.0], [190.0, 62.0], [270.0, 40.0]]]})
CHECKLIST = [{"id": "etat", "label": "État général satisfaisant", "required": True}, {"id": "securite", "label": "Dispositifs de sécurité fonctionnels", "required": True},
             {"id": "notice", "label": "Notice présente", "required": False}]

rng = random.Random(42)


def days(n, hour=8):
    return (utils.now() + timedelta(days=n)).replace(hour=hour, minute=0, second=0, microsecond=0)


def slug(name):
    table = str.maketrans("éèêëàâïîôöùûç'", "eeeeaaiioouuc-")
    return name.lower().translate(table).replace(" ", ".")


class Seed:
    def __init__(self, db):
        self.db = db
        self.now = utils.now()
        self.teams = {}

    def add(self, obj):
        self.db.add(obj)
        self.db.flush()
        return obj

    def history(self, kind, tool, old_state, new_state, old_status, new_status, source, user_id, at, comment=None):
        self.db.add(StateHistory(tool_kind=kind, tool_id=tool.id, old_state=old_state, new_state=new_state, old_status=old_status, new_status=new_status,
                                 source=source, comment=comment, changed_by_id=user_id, changed_at=at))

    def event(self, loan, kind, user_id, at, detail=None):
        self.db.add(LoanEvent(loan_id=loan.id, kind=kind, user_id=user_id, detail=json.dumps(detail, ensure_ascii=False) if detail else None, created_at=at))

    def notify(self, user_id, type_, severity, title, body, link, age_days=1, read=False):
        at = self.now - timedelta(days=age_days)
        self.db.add(Notification(user_id=user_id, type=type_, severity=severity, title=title, body=body, link=link, created_at=at,
                                 read_at=at + timedelta(hours=3) if read else None, dedup_key=f"demo:{secrets.token_hex(6)}"))

    # ------------------------------------------------------------------ personnes et chantiers

    def people(self, password_hash):
        for agency in AGENCIES:
            if not self.db.query(Agency).filter(Agency.name == agency).first():
                self.db.add(Agency(name=agency, code=DEMO_AGENCY_CODE))
        self.db.flush()
        for agency in AGENCIES:
            director, managers, workers, storekeeper = PEOPLE[agency]

            def mk(name, role, manager=None):
                user = User(username=f"demo.{slug(name)}", full_name=name, hashed_password=password_hash, role=role, manager_id=manager, agency_number=agency,
                            email=f"{slug(name)}@exemple.invalid", phone=f"06 00 {rng.randint(10, 99)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
                            charter_version=charter.VERSION, created_at=days(-430))
                self.add(user)
                self.db.add(CharterAcceptance(user_id=user.id, version=charter.VERSION, accepted_at=days(-rng.randint(1, 60))))
                return user

            boss = mk(director, UserRole.directeur_agence)
            mgrs = [mk(n, UserRole.charge_affaires, boss.id) for n in managers]
            crew = [mk(n, UserRole.gars_chantier, mgrs[i % len(mgrs)].id) for i, n in enumerate(workers)]
            store = mk(storekeeper, UserRole.magasinier, boss.id)
            self.teams[agency] = {"boss": boss, "managers": mgrs, "crew": crew, "store": store, "sites": []}
            for i, (code, label, client, status) in enumerate(SITES[agency]):
                closed = status == "clos"
                site = self.add(Site(agency_number=agency, name=f"{code} – {label}", code=code, client=client, address=f"{rng.randint(1, 90)} zone d'activités, chantier {code}",
                                     start_date=days(-400 + i * 70), end_date=days(-40 if closed else 90 + i * 30), status=status, manager_id=mgrs[i % len(mgrs)].id,
                                     notes="Chantier de démonstration", created_at=days(-405 + i * 70), closed_at=days(-40) if closed else None, closed_by_id=boss.id if closed else None))
                self.teams[agency]["sites"].append(site)
        newcomer = User(username="demo.nouvel.arrivant", full_name="Nouvel Arrivant", hashed_password=password_hash, role=UserRole.gars_chantier, agency_number="Lyon",
                        manager_id=self.teams["Lyon"]["managers"][0].id, charter_version=0, created_at=days(-1))
        self.add(newcomer)

    def rules(self):
        for type_ in TYPES:
            self.db.add(InspectionPolicy(tool_kind="agency", type=type_, periodicity_days=180 if type_ in ("Nacelle", "Levage", "Échafaudage") else 365, warn_before_days=30,
                                         requires_calibration=type_ == "Mesure", calibration_periodicity_days=365 if type_ == "Mesure" else None, description="Règle de démonstration"))
            self.db.add(DepreciationPolicy(type=type_, years=8 if type_ in ("Nacelle", "Levage") else 5, residual_pct=15 if type_ in ("Nacelle", "Levage") else 0, updated_at=DEMO_DATE))
            self.db.add(InspectionTemplate(tool_kind="agency", type=type_, items_json=json.dumps(CHECKLIST, ensure_ascii=False)))
        for code, label in (("DEMO-CACES-R486", "CACES R486 nacelles"), ("DEMO-CACES-R489", "CACES R489 chariots"), ("DEMO-HAB-B1V", "Habilitation électrique B1V"),
                            ("DEMO-HAUTEUR", "Travail en hauteur"), ("DEMO-SST", "Sauveteur secouriste du travail")):
            if not self.db.query(QualificationType).filter(QualificationType.code == code).first():
                self.db.add(QualificationType(code=code, label=label))
        self.db.flush()
        for team in self.teams.values():
            for i, user in enumerate(team["crew"] + team["managers"]):
                for j, code in enumerate(("DEMO-CACES-R486", "DEMO-HAUTEUR", "DEMO-SST")[: 1 + i % 3]):
                    expiry = {0: days(400), 1: days(18), 2: days(-25)}[(i + j) % 3]
                    self.db.add(UserQualification(user_id=user.id, code=code, obtained_at=days(-700), expires_at=expiry))

    # ------------------------------------------------------------------ parc

    def agency_tools(self, agency):
        team = self.teams[agency]
        everyone = team["crew"] + team["managers"]
        prefix = agency[:3].upper()
        tools = []
        plan = (["disponible"] * 14 + ["emprunte"] * 5 + ["reparation"] * 3 + ["hors_service"] * 2 + ["dotation"] * 3 + ["sorti_du_parc"] * 2 + ["reservable"] * 3)
        rng.shuffle(plan)
        for i, status_plan in enumerate(plan):
            type_, name, brand, price, rate = CATALOGUE[i % len(CATALOGUE)]
            bought = days(-rng.randint(60, 1500))
            status = {"reservable": "disponible"}.get(status_plan, status_plan)
            tool = self.add(AgencyTool(
                name=name, type=type_, brand=brand, unique_code=f"DEMO-{prefix}-{i + 1:03d}", agency_number=agency, serial_number=f"SN{rng.randint(100000, 999999)}",
                description=f"{name} {brand}", purchase_date=bought, purchase_price=float(price), daily_rate=float(rate), warranty_expiration_date=bought + timedelta(days=rng.choice((365, 730, 1095))),
                state=rng.choice((5, 5, 4, 4, 3)), status=AgencyToolStatus(status), last_control_date=days(-rng.randint(5, 420)), created_at=bought, comment=None,
            ))
            tool.plan = status_plan
            tools.append(tool)
            self.db.add(ToolLabel(tool_kind="agency", tool_id=tool.id, printed_at=bought, printed_by_id=team["store"].id)) if i % 2 else None
            self.history(ToolKind.agency, tool, None, 5, None, "disponible", "création", team["store"].id, bought)
            if type_ in ("Perçage", "Découpe"):
                self.db.add(ToolAccessory(tool_id=tool.id, name="Mallette de transport", quantity=1, required=True))
                self.db.add(ToolAccessory(tool_id=tool.id, name="Batterie de rechange", quantity=2, required=False))
            if type_ == "Nacelle":
                self.db.add(ToolRequirement(agency_tool_id=tool.id, qualification_code="DEMO-CACES-R486", blocking=i % 2 == 0))
                self.db.add(ReservationRule(agency_tool_id=tool.id, requires_approval=True, max_days=15))
            if type_ == "Levage":
                self.db.add(ReservationRule(agency_tool_id=tool.id, requires_approval=True))
            self.loan_history(tool, team, everyone)
            self.finish_state(tool, team, everyone)
            self.controls(tool, team, everyone)
        self.db.flush()
        return tools

    def loan_history(self, tool, team, everyone):
        cursor = max(days(-420), tool.purchase_date + timedelta(days=3))
        limit = days(-3)
        while cursor < limit:
            start = cursor + timedelta(days=rng.randint(1, 18))
            end = start + timedelta(days=rng.randint(1, 12), hours=9)
            if end >= limit:
                break
            borrower = rng.choice(everyone)
            site = rng.choice(team["sites"])
            outcome = rng.random()
            if outcome < 0.08:
                status = LoanStatus.annule
            elif outcome < 0.13 and tool.type in ("Nacelle", "Levage"):
                status = LoanStatus.refuse
            else:
                status = LoanStatus.termine
            late = timedelta(days=rng.choice((0, 0, 0, 1, 3))) if status == LoanStatus.termine else timedelta()
            before = rng.choice((5, 4, 4, 3))
            after = max(before - rng.choice((0, 0, 0, 1)), 2)
            loan = self.add(Loan(
                tool_id=tool.id, borrower_id=borrower.id, created_by_id=rng.choice((borrower.id, borrower.manager_id or borrower.id)), site=site.name, site_id=site.id,
                comment=rng.choice(LOAN_COMMENTS), start_datetime=start, end_datetime_planned=end, status=status, created_at=start - timedelta(days=rng.randint(1, 7)),
                checked_out_at=start if status == LoanStatus.termine else None, actual_return_datetime=end + late if status == LoanStatus.termine else None,
                state_before=before if status == LoanStatus.termine else None, state_after=after if status == LoanStatus.termine else None,
                comment_return=rng.choice(RETURN_COMMENTS) if status == LoanStatus.termine else None,
                signature_json=SIGNATURE if status == LoanStatus.termine and rng.random() < 0.3 else None,
            ))
            if loan.signature_json:
                loan.signed_name, loan.signed_at = borrower.full_name, start
            self.event(loan, "created", loan.created_by_id, loan.created_at)
            if status == LoanStatus.termine:
                self.event(loan, "checkout", borrower.id, start)
                self.event(loan, "returned", borrower.id, loan.actual_return_datetime, {"state_after": after, "accessories_ok": True})
                self.history(ToolKind.agency, tool, before, before, "disponible", "emprunte", "retrait réservation", borrower.id, start)
                self.history(ToolKind.agency, tool, before, after, "emprunte", "disponible", "retour réservation", borrower.id, loan.actual_return_datetime, loan.comment_return)
            elif status == LoanStatus.annule:
                self.event(loan, "cancelled", borrower.id, start - timedelta(hours=6))
            else:
                loan.approved_by_id, loan.approval_comment = team["boss"].id, "Nacelle déjà prévue sur un autre chantier"
                self.event(loan, "rejected", team["boss"].id, start - timedelta(days=1), {"comment": loan.approval_comment})
            cursor = (loan.actual_return_datetime or end) + timedelta(hours=6)

    def finish_state(self, tool, team, everyone):
        plan = tool.plan
        worker = rng.choice(everyone)
        site = rng.choice([s for s in team["sites"] if s.status == "actif"])
        if plan == "emprunte":
            overdue = rng.random() < 0.5
            start = days(-rng.randint(6, 14) if overdue else -2)
            end = days(-rng.randint(1, 4) if overdue else rng.randint(2, 12), 17)
            loan = self.add(Loan(tool_id=tool.id, borrower_id=worker.id, created_by_id=worker.id, site=site.name, site_id=site.id, comment=rng.choice(LOAN_COMMENTS),
                                 start_datetime=start, end_datetime_planned=end, status=LoanStatus.en_cours, checked_out_at=start, state_before=tool.state, created_at=start - timedelta(days=2)))
            self.event(loan, "created", worker.id, loan.created_at)
            self.event(loan, "checkout", worker.id, start)
            self.history(ToolKind.agency, tool, tool.state, tool.state, "disponible", "emprunte", "retrait réservation", worker.id, start)
            if overdue:
                self.notify(worker.id, "loan_overdue", "warning", f"{tool.name} à rendre", f"Retour prévu le {end:%d/%m/%Y}.", "#/reservations")
                self.notify(worker.manager_id, "loan_overdue", "warning", f"Retard : {tool.name}", f"{worker.full_name} n'a pas encore rendu cet outil.", "#/reservations")
        elif plan == "reservable":
            start = days(rng.randint(2, 25))
            needs_ok = tool.type in ("Nacelle", "Levage")
            loan = self.add(Loan(tool_id=tool.id, borrower_id=worker.id, created_by_id=worker.id, site=site.name, site_id=site.id, comment="Réservation à venir", start_datetime=start,
                                 end_datetime_planned=start + timedelta(days=rng.randint(1, 6), hours=9), status=LoanStatus.attente_validation if needs_ok else LoanStatus.reserve, created_at=days(-1)))
            self.event(loan, "created", worker.id, loan.created_at)
            if needs_ok:
                self.notify(team["boss"].id, "loan_approval", "info", f"Réservation à valider : {tool.name}", f"Demande de {worker.full_name}, chantier {site.code}.", "#/reservations")
        elif plan == "dotation":
            tool.assigned_to_id = worker.id
            self.history(ToolKind.agency, tool, tool.state, tool.state, "disponible", "dotation", "édition", team["boss"].id, days(-90))
        elif plan == "reparation":
            tool.state = 1
            self.ticket(tool, team, worker, rng.choice(("ouvert", "diagnostic", "en_reparation", "attente_piece")), rng.choice(("panne", "casse")))
            self.db.add(ToolBlackout(tool_id=tool.id, start_datetime=days(-3), end_datetime=days(12), reason="maintenance", note="Immobilisé pour réparation", source="manual", created_by_id=team["store"].id))
        elif plan == "hors_service":
            kind = rng.choice(("vol", "casse", "perte"))
            tool.state, tool.loss_reason = 0, kind
            at = days(-rng.randint(10, 150))
            self.db.add(LossRecord(tool_id=tool.id, agency_number=tool.agency_number, kind=kind, occurred_at=at, responsible_id=worker.id, site_id=site.id,
                                   circumstances={"vol": "Fourgon fracturé pendant la nuit", "casse": "Chute depuis l'échafaudage", "perte": "Introuvable après repli du chantier"}[kind],
                                   declared_value=tool.purchase_price, police_report_ref=f"PV-{rng.randint(10000, 99999)}" if kind == "vol" else None,
                                   insurance_status="accepted" if kind == "vol" else "none", insurance_ref=f"SIN-{rng.randint(1000, 9999)}" if kind == "vol" else None,
                                   refunded_amount=round(tool.purchase_price * 0.6, 2) if kind == "vol" else 0, litigation_status="open" if kind == "perte" else "none",
                                   litigation_note="Responsabilité à établir" if kind == "perte" else None, created_by_id=team["boss"].id, created_at=at, updated_at=at))
            self.history(ToolKind.agency, tool, 4, 0, "disponible", "hors_service", "signalement", worker.id, at, kind)
            self.notify(team["boss"].id, "tool_problem", "critical", f"Outil déclaré : {tool.name}", f"Motif : {kind}.", "#/financier", age_days=rng.randint(1, 9), read=True)
        elif plan == "sorti_du_parc":
            at = days(-rng.randint(20, 200))
            reason = rng.choice(("vendu", "rebut", "donne"))
            tool.exit_reason, tool.exit_date, tool.exit_note = reason, at, f"Sortie validée. Ancien code : {tool.unique_code}"
            tool.residual_value = round(tool.purchase_price * 0.2, 2) if reason == "vendu" else 0.0
            self.db.add(ExitRequest(tool_id=tool.id, requested_by_id=team["managers"][0].id, reason=reason, exit_date=at, note="Matériel en fin de vie", residual_value=tool.residual_value,
                                    status="approved", decided_by_id=team["boss"].id, decided_at=at, created_at=at - timedelta(days=4)))
            self.history(ToolKind.agency, tool, tool.state, tool.state, "disponible", "sorti_du_parc", "sortie de parc", team["boss"].id, at, reason)
        elif plan == "disponible":
            roll = rng.random()
            if roll < 0.2:
                self.ticket(tool, team, worker, rng.choice(("repare", "clos", "irreparable")), rng.choice(("usure", "accessoire_manquant", "autre")))
            elif roll < 0.3:
                self.db.add(ExitRequest(tool_id=tool.id, requested_by_id=team["managers"][-1].id, reason="rebut", note="Réparation plus chère que le remplacement", created_at=days(-2)))
            elif roll < 0.45:
                self.db.add(ToolBlackout(tool_id=tool.id, start_datetime=days(rng.randint(3, 20)), end_datetime=days(rng.randint(21, 30)), reason="controle", note="Vérification périodique", source="manual", created_by_id=team["store"].id))

    def ticket(self, tool, team, worker, status, category):
        opened = days(-rng.randint(2, 60))
        closed = status in ("repare", "clos", "irreparable")
        estimate = round(tool.purchase_price * rng.uniform(0.05, 0.25), 2)
        ticket = self.add(MaintenanceTicket(
            tool_kind="agency", tool_id=tool.id, agency_number=tool.agency_number, opened_by_id=worker.id, opened_at=opened, category=category,
            severity=rng.choice(("faible", "moyenne", "haute", "critique")), description=PROBLEMS[category], status=status, assigned_to_id=team["store"].id,
            provider=rng.choice(("interne", "fournisseur", "sav")), warranty_claim=rng.random() < 0.3, estimated_cost=estimate, actual_cost=round(estimate * rng.uniform(0.8, 1.3), 2) if closed else None,
            parts="Charbons, interrupteur" if category == "usure" else None, expected_return_date=days(rng.randint(3, 20)) if not closed else None, sent_at=opened + timedelta(days=1),
            back_at=opened + timedelta(days=12) if closed else None, closed_at=opened + timedelta(days=13) if closed else None,
            resolution={"repare": "Pièce remplacée, essais conformes", "clos": "Réparation validée", "irreparable": "Coût supérieur à la valeur de l'outil"}.get(status),
        ))
        self.db.add(MaintenanceComment(ticket_id=ticket.id, user_id=worker.id, body="Signalement créé", kind="status", created_at=opened))
        self.db.add(MaintenanceComment(ticket_id=ticket.id, user_id=team["store"].id, body="Pris en charge par le magasin, devis demandé.", kind="comment", created_at=opened + timedelta(days=1)))
        self.history(ToolKind.agency, tool, tool.state, tool.state, "disponible", "reparation", "signalement", worker.id, opened, category)

    def controls(self, tool, team, everyone):
        cursor = days(-rng.randint(250, 420))
        while cursor < days(-5):
            result = rng.choices(("conforme", "conforme_avec_reserves", "non_conforme"), (8, 2, 1))[0]
            inspection = Inspection(tool_kind="agency", tool_id=tool.id, inspector_id=rng.choice(everyone + [team["store"]]).id, inspected_at=cursor, result=result, state_after=rng.choice((5, 4, 3)),
                                    comment={"conforme": "RAS", "conforme_avec_reserves": "Usure à surveiller", "non_conforme": "Sécurité défaillante, outil immobilisé"}[result],
                                    next_due=cursor + timedelta(days=180), checklist_json=json.dumps([{**c, "answer": "ok" if result == "conforme" or c["id"] == "notice" else "ko"} for c in CHECKLIST], ensure_ascii=False))
            self.db.add(inspection)
            tool.last_control_date = cursor
            cursor += timedelta(days=rng.randint(120, 260))
        if tool.type == "Mesure":
            at = days(-rng.choice((40, 200, 350, 400)))
            self.db.add(Calibration(tool_id=tool.id, calibrated_at=at, next_due=at + timedelta(days=365), provider="Laboratoire Métrologie Ouest", certificate_number=f"CERT-{rng.randint(1000, 9999)}",
                                    cost=float(rng.randint(90, 260)), result="conforme", created_by_id=team["store"].id, created_at=at))

    def epi(self, agency):
        team = self.teams[agency]
        prefix = agency[:3].upper()
        for i in range(18):
            type_, name, brand = EPI_CATALOGUE[i % len(EPI_CATALOGUE)]
            expiry = days(rng.choice((-30, -5, 7, 25, 55, 200, 500, 900)))
            holder = rng.choice(team["crew"] + team["managers"]) if i % 4 else None
            epi = self.add(Epi(name=name, type=type_, brand=brand, unique_code=f"DEMO-E-{prefix}-{i + 1:03d}", agency_number=agency, assigned_to_id=holder.id if holder else None,
                               state=rng.choice((5, 4, 3, 2)), expiration_date=expiry, last_control_date=days(-rng.randint(10, 300)), comment="Contrôle annuel" if i % 3 == 0 else None))
            self.history(ToolKind.epi, epi, None, 5, None, None, "création", team["store"].id, days(-500))
            self.db.add(Inspection(tool_kind="epi", tool_id=epi.id, inspector_id=team["store"].id, inspected_at=epi.last_control_date, result="conforme", state_after=epi.state, comment="RAS", next_due=epi.last_control_date + timedelta(days=365)))
            if expiry < self.now and holder:
                self.notify(holder.id, "epi_expired", "critical", f"EPI périmé : {name}", f"Péremption le {expiry:%d/%m/%Y}.", "#/epi")

    def personal_tools(self, agency):
        team = self.teams[agency]
        prefix = agency[:3].upper()
        crew = team["crew"]
        tools = []
        for i, (name, type_, brand, price) in enumerate((("Visseuse à chocs", "Perçage", "Makita", 169), ("Niveau 120 cm", "Mesure", "Stabila", 79), ("Pince multiprise", "Découpe", "Knipex", 32),
                                                         ("Coffret de douilles", "Levage", "Facom", 145), ("Scie égoïne", "Découpe", "Bahco", 28), ("Perceuse sans fil", "Perçage", "Bosch", 199),
                                                         ("Mètre laser", "Mesure", "Stanley", 59), ("Marteau de coffreur", "Découpe", "Leborgne", 41))):
            owner = crew[i % len(crew)]
            reason = {3: ToolStateReason.endommage, 6: ToolStateReason.en_reparation}.get(i, ToolStateReason.normal)
            tool = self.add(PersonalTool(owner_id=owner.id, current_holder_id=owner.id, name=name, type=type_, brand=brand, unique_code=f"DEMO-P-{prefix}-{i + 1:03d}", purchase_date=days(-rng.randint(100, 900)),
                                         purchase_price=float(price), state=2 if reason != ToolStateReason.normal else rng.choice((5, 4, 3)), state_reason=reason,
                                         state_comment="Mandrin qui patine" if reason != ToolStateReason.normal else None, last_control_date=days(-rng.randint(10, 200))))
            self.history(ToolKind.personal, tool, None, tool.state, None, reason.value, "création", owner.id, tool.purchase_date)
            tools.append(tool)
        a, b, c = crew[0], crew[1], crew[2]
        # Transferts entre collègues : un de chaque état.
        self.db.add(PeerTransfer(tool_id=tools[0].id, from_user_id=tools[0].owner_id, to_user_id=b.id, declared_by_id=tools[0].owner_id, status=PeerTransferStatus.en_attente, transfer_date=days(-1), state_before=tools[0].state, comment="Pour la semaine prochaine"))
        self.notify(b.id, "peer_pending", "info", f"Transfert à confirmer : {tools[0].name}", "Un collègue vous propose cet outil.", "#/transferts-collegues")
        tools[1].current_holder_id = c.id
        self.db.add(PeerTransfer(tool_id=tools[1].id, from_user_id=tools[1].owner_id, to_user_id=c.id, declared_by_id=c.id, status=PeerTransferStatus.confirme, transfer_date=days(-9), confirmed_at=days(-9), planned_return_date=days(5), state_before=tools[1].state, comment="Prêt pendant le chantier"))
        self.db.add(PeerTransfer(tool_id=tools[2].id, from_user_id=tools[2].owner_id, to_user_id=a.id if tools[2].owner_id != a.id else b.id, declared_by_id=tools[2].owner_id, status=PeerTransferStatus.refuse, transfer_date=days(-30), state_before=tools[2].state))
        self.db.add(PeerTransfer(tool_id=tools[4].id, from_user_id=tools[4].owner_id, to_user_id=c.id, declared_by_id=c.id, status=PeerTransferStatus.termine, transfer_date=days(-70), confirmed_at=days(-70), actual_return_date=days(-55), state_before=5, state_after=4, comment="Rendu en bon état"))
        return tools

    def external(self, tools, personal, agency):
        team = self.teams[agency]
        free = [t for t in tools if t.plan == "disponible"]
        for i, (company, contact, kind) in enumerate(EXTERNAL):
            tool = free[i % len(free)]
            site = team["sites"][i % len(team["sites"])]
            lender = team["managers"][i % len(team["managers"])]
            mail = f"{slug(contact)}@exemple.invalid"
            if i < 2:
                overdue = i == 1
                tool.status = AgencyToolStatus.emprunte
                self.db.add(Transfer(agency_tool_id=tool.id, from_user_id=lender.id, to_external_name=contact, to_external_company=company, to_external_type=kind, to_external_email=mail, to_external_phone="06 11 22 33 44",
                                     site_code=site.code, client_code=f"C-{rng.randint(1000, 1999)}", transfer_date=days(-20 if overdue else -3), planned_return_date=days(-4 if overdue else 10), state_before=tool.state,
                                     status=TransferStatus.en_cours, comment="Prêt pour lot sous-traité", signature_json=SIGNATURE, signed_name=contact, signed_at=days(-3)))
                self.history(ToolKind.agency, tool, tool.state, tool.state, "disponible", "emprunte", "prêt externe", lender.id, days(-3))
                if overdue:
                    self.notify(lender.id, "transfer_overdue", "warning", f"Prêt externe en retard : {tool.name}", f"Prêté à {contact} ({company}).", "#/prets")
            else:
                self.db.add(Transfer(agency_tool_id=tool.id, from_user_id=lender.id, to_external_name=contact, to_external_company=company, to_external_type=kind, to_external_email=mail, site_code=site.code,
                                     transfer_date=days(-120 - i * 20), planned_return_date=days(-100 - i * 20), actual_return_date=days(-101 - i * 20), state_before=5, state_after=rng.choice((5, 4, 3)), status=TransferStatus.termine, comment="Rendu au dépôt"))
        tool = personal[5]
        self.db.add(Transfer(tool_id=tool.id, from_user_id=tool.owner_id, to_external_name="Bruno Marchand", to_external_company="Atelier Marchand", to_external_type=ExternalRecipientType.sous_traitant, transfer_date=days(-6), planned_return_date=days(4), state_before=tool.state, status=TransferStatus.en_cours))
        tool.current_holder_id = None

    def planning(self, tools, agency):
        team = self.teams[agency]
        free = [t for t in tools if t.status == AgencyToolStatus.disponible]
        for name, members in (("Kit carottage", free[:3]), ("Kit topographie", free[3:6]), ("Kit soudure de chantier", free[6:8])):
            kit = self.add(ToolKit(name=f"{name} {agency}", agency_number=agency, description="Lot prêt à partir"))
            for tool in members:
                self.db.add(ToolKitItem(kit_id=kit.id, tool_id=tool.id))
        # Demandes à valider, pour montrer l'écran de validation.
        for tool in [t for t in free if t.type in ("Nacelle", "Levage")][:2] or free[9:10]:
            worker = rng.choice(team["crew"])
            start = days(rng.randint(26, 40))
            loan = self.add(Loan(tool_id=tool.id, borrower_id=worker.id, created_by_id=worker.id, site=team["sites"][-1].name, site_id=team["sites"][-1].id, comment="Levage de charpente",
                                 start_datetime=start, end_datetime_planned=start + timedelta(days=3), status=LoanStatus.attente_validation, created_at=days(-1)))
            self.event(loan, "created", worker.id, days(-1))
            self.notify(team["boss"].id, "loan_approval", "info", f"Réservation à valider : {tool.name}", f"Demande de {worker.full_name}.", "#/reservations")
        # Série hebdomadaire à venir, liste d'attente sur un outil pris.
        tool = free[8]
        worker = team["crew"][0]
        series = f"demo-{secrets.token_hex(6)}"
        for week in range(5):
            start = days(4 + week * 7)
            loan = self.add(Loan(tool_id=tool.id, borrower_id=worker.id, created_by_id=worker.id, site=team["sites"][-1].name, site_id=team["sites"][-1].id, comment="Besoin récurrent chaque semaine",
                                 start_datetime=start, end_datetime_planned=start + timedelta(hours=9), status=LoanStatus.reserve, series_id=series, created_at=days(-1)))
            self.event(loan, "created", worker.id, days(-1), {"series": True})
        taken = [t for t in tools if t.plan == "emprunte"]
        for i, tool in enumerate(taken[:3]):
            user = team["crew"][(i + 1) % len(team["crew"])]
            offered = i == 0
            self.db.add(WaitlistEntry(tool_id=tool.id, user_id=user.id, start_datetime=days(15), end_datetime=days(18), site=team["sites"][-1].name, status="offered" if offered else "waiting",
                                      offered_at=days(0) if offered else None, offer_expires_at=days(1) if offered else None, created_at=days(-2)))
            if offered:
                self.notify(user.id, "waitlist_available", "info", f"Outil disponible : {tool.name}", "Votre offre expire demain.", "#/mes-reservations")

    def agency_transfers(self, pools):
        lyon, nantes = pools["Lyon"], pools["Nantes"]
        for source, target, temporary, state in ((lyon, "Nantes", True, "pending"), (nantes, "Lyon", False, "pending"), (lyon, "Projets", False, "rejected"), (nantes, "Projets", True, "returned")):
            tool = next(t for t in source if t.status == AgencyToolStatus.disponible and not t.home_agency and t.plan == "disponible")
            tool.plan = "transfere"
            team = self.teams[tool.agency_number]
            self.db.add(AgencyTransfer(tool_id=tool.id, from_agency=tool.agency_number, to_agency=target, requested_by_id=team["managers"][0].id, status=state, temporary=temporary, planned_return_date=days(20) if temporary else None,
                                       decided_by_id=self.teams[target]["boss"].id if state != "pending" else None, decided_at=days(-40) if state != "pending" else None, returned_at=days(-10) if state == "returned" else None, comment="Besoin ponctuel d'une autre agence"))
            if state == "pending":
                self.notify(self.teams[target]["boss"].id, "agency_transfer", "info", f"Demande de transfert : {tool.name}", f"Proposé par l'agence {tool.agency_number}.", "#/transferts-agences")
        tool = next(t for t in lyon if t.plan == "disponible")
        tool.home_agency, tool.agency_number = "Lyon", "Nantes"
        tool.plan = "transfere"
        self.db.add(AgencyTransfer(tool_id=tool.id, from_agency="Lyon", to_agency="Nantes", requested_by_id=self.teams["Lyon"]["managers"][0].id, status="accepted", temporary=True, planned_return_date=days(25), decided_by_id=self.teams["Nantes"]["boss"].id, decided_at=days(-8), comment="Prêt temporaire entre agences"))

    def stock(self, agency):
        team = self.teams[agency]
        site = next(s for s in team["sites"] if s.status == "actif")
        for i, (name, unit, qty, threshold, place) in enumerate((("Forets béton 12 mm", "pièce", 42, 10, "Rayon A1"), ("Disques à tronçonner 230", "pièce", 6, 15, "Rayon A2"), ("Gants nitrile", "boîte", 18, 5, "Rayon C1"),
                                                                ("Masques FFP2", "boîte", 3, 8, "Rayon C2"), ("Mèches bois 8 mm", "pièce", 25, 5, "Rayon A3"), ("Cartouches de silicone", "pièce", 60, 20, "Rayon B4"))):
            item = self.add(StockItem(agency_number=agency, name=name, reference=f"DEMO-S-{agency[:3].upper()}-{i + 1:02d}", unit=unit, quantity=float(qty), threshold=float(threshold), location=place))
            balance = float(qty) + 40
            self.db.add(StockMovement(item_id=item.id, kind="entree", quantity=balance, balance_after=balance, user_id=team["store"].id, note="Réception fournisseur", created_at=days(-120)))
            for week in (90, 60, 30, 8):
                used = 10.0
                balance -= used
                self.db.add(StockMovement(item_id=item.id, kind="sortie", quantity=used, balance_after=balance, user_id=team["store"].id, to_user_id=rng.choice(team["crew"]).id, site=site.name, site_id=site.id, note="Sortie pour chantier", created_at=days(-week)))
            if qty <= threshold:
                self.notify(team["store"].id, "stock_low", "warning", f"Stock bas : {name}", f"Il reste {qty} {unit}(s).", "#/stock")

    def finance(self):
        year = self.now.year
        for agency in AGENCIES:
            boss = self.teams[agency]["boss"]
            for y, ratio in ((year - 1, 0.9), (year, 1.0)):
                for category, amount in (("achats", 45000), ("reparations", 9000), ("pertes", 4000)):
                    if not self.db.query(Budget).filter_by(agency_number=agency, year=y, category=category).first():
                        self.db.add(Budget(agency_number=agency, year=y, category=category, amount=amount * ratio, updated_by_id=boss.id, updated_at=DEMO_DATE))

    def journal(self):
        users = [u for team in self.teams.values() for u in team["crew"] + team["managers"] + [team["boss"], team["store"]]]
        actions = (("login_success", "user", None), ("login_success", "user", None), ("export", "export", {"dataset": "tools", "format": "xlsx"}), ("tool_status_changed", "agency_tool", {"from": "disponible", "to": "reparation"}),
                   ("agency_tool_updated", "agency_tool", {"fields": ["comment"]}), ("site_created", "site", {"name": "chantier"}), ("export_registry", "export", {"tool_kind": "agency", "format": "pdf"}), ("login_failed", "user", {"reason": "mot de passe"}))
        for _ in range(180):
            user = rng.choice(users)
            action, entity, details = rng.choice(actions)
            self.db.add(AuditLog(user_id=user.id, action=action, entity_type=entity, entity_id=str(user.id), ip=f"192.0.2.{rng.randint(1, 250)}", user_agent=MARK_AGENT,
                                 details=json.dumps(details, ensure_ascii=False) if details else None, created_at=self.now - timedelta(days=rng.randint(0, 90), hours=rng.randint(0, 23))))
        for admin in self.db.query(User).filter(User.role == UserRole.admin, User.is_active.is_(True)):
            self.notify(admin.id, "generic", "info", "Données de démonstration chargées", "Trois agences, leurs chantiers et 14 mois d'historique sont disponibles.", "#/")


def run_seed(db) -> str:
    if db.query(User).filter(User.username.like("demo.%")).first():
        raise SystemExit("Des données de démonstration existent déjà : lancez d'abord --reset.")
    password = "Demo-" + secrets.token_urlsafe(12) + "7"
    seed = Seed(db)
    seed.people(hash_password(password))
    seed.rules()
    pools = {}
    for agency in AGENCIES:
        pools[agency] = seed.agency_tools(agency)
        seed.epi(agency)
        personal = seed.personal_tools(agency)
        seed.external(pools[agency], personal, agency)
        seed.planning(pools[agency], agency)
        seed.stock(agency)
    seed.agency_transfers(pools)
    seed.finance()
    seed.journal()
    db.commit()
    return password


def run_reset(db):
    users = [u.id for u in db.query(User).filter(User.username.like("demo.%"))]
    tools = [t.id for t in db.query(AgencyTool).filter(AgencyTool.unique_code.like("DEMO-%"))]
    epis = [t.id for t in db.query(Epi).filter(Epi.unique_code.like("DEMO-%"))]
    personal = [t.id for t in db.query(PersonalTool).filter(PersonalTool.unique_code.like("DEMO-%"))]
    loans = [l.id for l in db.query(Loan).filter(Loan.tool_id.in_(tools))]
    tickets = [t.id for t in db.query(MaintenanceTicket).filter(MaintenanceTicket.tool_kind == "agency", MaintenanceTicket.tool_id.in_(tools))]
    items = [i.id for i in db.query(StockItem).filter(StockItem.reference.like("DEMO-%"))]
    sites = [s.id for s in db.query(Site).filter(Site.notes == "Chantier de démonstration")]
    kits = [k.id for k in db.query(ToolKit).join(ToolKitItem, ToolKitItem.kit_id == ToolKit.id).filter(ToolKitItem.tool_id.in_(tools))]

    def drop(query):
        query.delete(synchronize_session=False)

    drop(db.query(LoanEvent).filter(LoanEvent.loan_id.in_(loans)))
    drop(db.query(WaitlistEntry).filter(WaitlistEntry.tool_id.in_(tools)))
    drop(db.query(Loan).filter(Loan.id.in_(loans)))
    drop(db.query(Transfer).filter(or_(Transfer.agency_tool_id.in_(tools), Transfer.tool_id.in_(personal))))
    drop(db.query(PeerTransfer).filter(PeerTransfer.tool_id.in_(personal)))
    drop(db.query(AgencyTransfer).filter(AgencyTransfer.tool_id.in_(tools)))
    drop(db.query(MaintenanceComment).filter(MaintenanceComment.ticket_id.in_(tickets)))
    drop(db.query(MaintenanceTicket).filter(MaintenanceTicket.id.in_(tickets)))
    drop(db.query(LossRecord).filter(LossRecord.tool_id.in_(tools)))
    drop(db.query(ExitRequest).filter(ExitRequest.tool_id.in_(tools)))
    drop(db.query(ToolBlackout).filter(ToolBlackout.tool_id.in_(tools)))
    drop(db.query(ToolKitItem).filter(ToolKitItem.kit_id.in_(kits)))
    drop(db.query(ToolKit).filter(ToolKit.id.in_(kits)))
    drop(db.query(ToolAccessory).filter(ToolAccessory.tool_id.in_(tools)))
    drop(db.query(ToolRequirement).filter(ToolRequirement.agency_tool_id.in_(tools)))
    drop(db.query(ReservationRule).filter(ReservationRule.agency_tool_id.in_(tools)))
    drop(db.query(Calibration).filter(Calibration.tool_id.in_(tools)))
    drop(db.query(ToolLabel).filter(ToolLabel.tool_kind == "agency", ToolLabel.tool_id.in_(tools)))
    for kind, ids in (("agency", tools), ("epi", epis), ("personal", personal)):
        drop(db.query(Inspection).filter(Inspection.tool_kind == kind, Inspection.tool_id.in_(ids)))
        drop(db.query(StateHistory).filter(StateHistory.tool_kind == ToolKind(kind), StateHistory.tool_id.in_(ids)))
    drop(db.query(StockMovement).filter(StockMovement.item_id.in_(items)))
    drop(db.query(StockItem).filter(StockItem.id.in_(items)))
    drop(db.query(Site).filter(Site.id.in_(sites)))
    drop(db.query(Epi).filter(Epi.id.in_(epis)))
    drop(db.query(PersonalTool).filter(PersonalTool.id.in_(personal)))
    drop(db.query(AgencyTool).filter(AgencyTool.parent_tool_id.in_(tools)))
    drop(db.query(AgencyTool).filter(AgencyTool.id.in_(tools)))
    drop(db.query(InspectionPolicy).filter(InspectionPolicy.type.in_(TYPES), InspectionPolicy.tool_kind == "agency"))
    drop(db.query(InspectionTemplate).filter(InspectionTemplate.type.in_(TYPES), InspectionTemplate.tool_kind == "agency"))
    drop(db.query(DepreciationPolicy).filter(DepreciationPolicy.type.in_(TYPES)))
    drop(db.query(UserQualification).filter(UserQualification.code.like("DEMO-%")))
    drop(db.query(QualificationType).filter(QualificationType.code.like("DEMO-%")))
    drop(db.query(Budget).filter(Budget.updated_at == DEMO_DATE))
    drop(db.query(Notification).filter(Notification.dedup_key.like("demo:%")))
    drop(db.query(Notification).filter(Notification.user_id.in_(users)))
    drop(db.query(NotificationPreference).filter(NotificationPreference.user_id.in_(users)))
    drop(db.query(AuditLog).filter(or_(AuditLog.user_agent == MARK_AGENT, AuditLog.user_id.in_(users))))
    drop(db.query(CharterAcceptance).filter(CharterAcceptance.user_id.in_(users)))
    drop(db.query(RefreshToken).filter(RefreshToken.user_id.in_(users)))
    drop(db.query(LoginAttempt).filter(LoginAttempt.identifier.like("demo.%")))
    db.query(User).filter(User.id.in_(users)).update({"manager_id": None}, synchronize_session=False)
    drop(db.query(User).filter(User.id.in_(users)))
    drop(db.query(Agency).filter(Agency.code == DEMO_AGENCY_CODE))
    db.commit()


def main() -> int:
    args = sys.argv[1:]
    url = database.engine.url
    print(f"Base visée : {url.get_backend_name()} {url.host or url.database}")
    db = database.SessionLocal()
    try:
        if "--reset" in args:
            run_reset(db)
            print("Données de démonstration retirées.")
            return 0
        if "--yes" not in args:
            print("Rien n'a été écrit. Ajoutez --yes pour charger les données, ou --reset pour les retirer.")
            return 1
        password = run_seed(db)
    finally:
        db.close()
    print()
    print("Données chargées. Mot de passe commun des comptes de démonstration, affiché une seule fois :")
    print(f"    {password}")
    print("Comptes : demo.claire.vautrin (directrice), demo.julien.morvan (chargé d'affaires), demo.kevin.lemoine (chantier),")
    print("          demo.helene.roussel (magasinière), demo.nouvel.arrivant (charte à accepter). Liste complète : écran Utilisateurs.")
    print("À retirer après la présentation : python seed_demo.py --reset")
    return 0


if __name__ == "__main__":
    sys.exit(main())
