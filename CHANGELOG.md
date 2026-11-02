# Changelog — FAUCHÉ Gestion Outillage

Ce journal suit les évolutions notables de l'application. Format libre, en français, un point par changement significatif. La version applicative vit dans `backend/app/config.py` (`VERSION`).

## À venir — mise en ligne

- Prise en charge de PostgreSQL (`OUTILLAGE_DATABASE_URL`, connexion chiffrée obligatoire en production) et d'un stockage de fichiers S3 privé, en plus du mode local SQLite. Procédure : `DEPLOIEMENT.md`.
- En production, le premier compte admin n'est créé qu'avec `OUTILLAGE_ADMIN_PASSWORD` : `admin123` ne sert plus qu'en développement.
- Déploiement Vercel : entrée `api/index.py`, cron `/cron/tick`, IP lue derrière le proxy, script `migrate_to_postgres.py`.
- Sécurité : `python-jose` remplacé par PyJWT, dépendances mises à jour (aucune vulnérabilité connue selon pip-audit au 2026-11-02), taille des photos limitée, durée de réponse identique à la connexion pour un compte inconnu.
- La suppression d'un compte retire ses données propres et vide les références facultatives. Elle est refusée s'il reste un historique à conserver (prêts, transferts...) : anonymiser le compte à la place.

## 1.0.0 — reconstruction complète et feuille de route phases 0-11

Reconstruction intégrale de l'application (FastAPI + SQLAlchemy 2 + SQLite, frontend JS vanilla en modules ES, PWA), puis exécution de la feuille de route d'évolution :

- **Phase 0** — fondations et sécurité : migrations légères avec sauvegarde automatique, durcissement (CORS, en-têtes de sécurité, limitation de débit du login), sessions avec jeton de rafraîchissement à rotation, mot de passe oublié, journal d'audit, tâches planifiées, pagination serveur.
- **Phase 1** — notifications et paramètres centralisés (`app_settings`, digest email, préférences par type).
- **Phase 2** — contrôles, étalonnages, habilitations (politiques par type, checklists, blocage/avertissement configurable).
- **Phase 4** — réservations avancées (retrait anticipé, validation, liste d'attente, indisponibilités, récurrence, coffrets, retour groupé, signature, ICS, notifications push, transferts agence-agence, assistant de départ).
- **Phase 5** — maintenance et magasinier (rôle dédié, tickets, sortie de parc, accessoires, stock de consommables).
- **Phase 3** — terrain (fiche outil unifiée, scan et recherche par code, QR code et étiquettes, galerie photo, mode hors ligne avec file d'attente et idempotence serveur).
- **Phase 6** — chantiers (création/clôture, coût d'usage, statistiques d'utilisation du parc).
- **Phase 7** — finances avancées (amortissement, coût total de possession, pertes et litiges, budgets, exports CSV/Excel, clés d'API en lecture seule).
- **Phase 8** — import Excel/CSV avec simulation, synchronisation Excel étendue et reprise sur fichier verrouillé, sauvegardes complètes avec rotation et vérification, export et anonymisation RGPD.
- **Phase 9** — assistant IA avancé (outils en lecture seule scopés par périmètre, propositions d'action à confirmer explicitement, extraction depuis une photo, quotas, retours d'utilité).
- **Phases 10-11 (partielles)** — recherche globale, thème sombre, remplacement de `window.confirm`/`window.prompt` par des modales ; readiness/health, versionnage, purge des fichiers orphelins, suite de bout en bout en navigateur réel versionnée dans le projet (`tools/e2e/`).

Détail complet de chaque phase : `DOCUMENTATION_COMPLETE.md` (sections 22 à 32). Limites connues et travail restant : `DOCUMENTATION_COMPLETE.md` sections 20 et 21.
