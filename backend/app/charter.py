"""Charte que chaque utilisateur accepte avant d'utiliser l'application. Toute modification du texte doit augmenter VERSION."""
from sqlalchemy.orm import Session

from . import appsettings

VERSION = 1


def content(db: Session) -> dict:
    creator = appsettings.get(db, "charter.creator")
    controller = appsettings.get(db, "charter.controller")
    contact = appsettings.get(db, "charter.contact") or "votre responsable ou l'administrateur de l'application"
    audit_days = appsettings.get_int(db, "retention.audit_days")
    return {
        "version": VERSION,
        "title": "Charte d'utilisation et de protection des données",
        "sections": [
            {"title": "1. Objet", "items": [
                "Cette charte fixe les règles d'utilisation de l'application de gestion d'outillage. Votre accord est enregistré avec sa date et le numéro de version de la charte.",
            ]},
            {"title": "2. Protection du travail du créateur", "items": [
                f"L'application, son code, sa conception, ses textes et ses visuels restent la propriété de {creator}.",
                "Vous vous engagez à ne pas les copier, les revendre, les distribuer ni les réutiliser hors de l'usage prévu, et à ne pas en extraire le fonctionnement pour reproduire l'application.",
                "L'accès à l'application ne vous transfère aucun droit sur celle-ci.",
            ]},
            {"title": "3. Matériel confié", "items": [
                "Vous utilisez les outils et les EPI pour l'activité de l'entreprise, avec soin, et vous les rendez aux dates prévues.",
                "Vous déclarez sans délai dans l'application tout vol, perte, casse ou anomalie.",
                "Vous n'enregistrez aucune information fausse pour masquer un vol, une perte ou un prêt. Le vol de matériel et la fausse déclaration peuvent entraîner des sanctions disciplinaires et des poursuites.",
            ]},
            {"title": "4. Bon usage du compte", "items": [
                "Votre compte est personnel : ne communiquez jamais votre mot de passe et déconnectez-vous sur un appareil partagé.",
                "Vous n'essayez pas d'accéder à des données qui ne vous sont pas destinées et vous signalez tout problème de sécurité à l'administrateur.",
            ]},
            {"title": "5. Respect des données des autres", "items": [
                "Vous ne consultez et n'exportez les données des collègues, clients et tiers que pour les besoins de votre mission, et vous ne les transmettez pas à l'extérieur sans autorisation.",
                "Vous ne photographiez que le matériel : évitez les personnes, les visages et les documents sans rapport.",
                "Dans les commentaires, vous n'écrivez que des informations utiles et factuelles.",
            ]},
            {"title": "6. Vos données personnelles", "items": [
                f"Responsable du traitement : {controller}. Finalité : gérer le parc d'outillage, les prêts, les contrôles, les habilitations et la sécurité de l'application.",
                "Données traitées : identité, rôle, agence, coordonnées, emprunts et retours, signatures, habilitations, photos déposées, adresses IP et traces de connexion.",
                f"Accès : vous-même, votre hiérarchie selon son périmètre, et l'administrateur. Les traces de sécurité sont conservées {audit_days} jours.",
                "Hébergement : les données sont stockées à Paris chez Vercel et Supabase, des sociétés américaines qui interviennent comme prestataires.",
                f"Vos droits : vous pouvez exporter vos données depuis « Mon profil » et demander leur rectification, leur effacement ou la limitation de leur traitement auprès de {contact}. Vous pouvez aussi saisir la CNIL.",
            ]},
            {"title": "7. Suivi", "items": [
                "Les actions sensibles (connexions, exports, changements de statut) sont journalisées pour la sécurité de l'application. Le non-respect de cette charte peut entraîner la suspension de l'accès.",
            ]},
        ],
    }
