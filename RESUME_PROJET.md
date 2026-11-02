# FAUCHÉ — Gestion Outillage : résumé complet du projet

## 1. Vue d'ensemble

FAUCHÉ — Gestion Outillage est une application web installable (PWA) de gestion du parc d'outillage et des EPI (équipements de protection individuelle) d'une entreprise du BTP / électricité organisée en agences. Elle est conçue mobile-first pour le terrain : appareil photo, scanner de codes par la caméra, QR codes et codes-barres imprimables, utilisable hors ligne sur chantier. L'interface est entièrement en français.

Architecture : backend Python FastAPI + SQLAlchemy 2 (synchrone) + SQLite, frontend en JavaScript vanilla (modules ES natifs, aucun framework, aucun bundler, aucune dépendance npm) servi statiquement par le backend. Authentification par jeton JWT de 30 minutes renouvelé automatiquement par un jeton de rafraîchissement (30 jours glissants). Lancement en développement : `.\run_dev.ps1` depuis `backend/` (ou `OUTILLAGE_ENV=dev` puis `python -m uvicorn app.main:app --reload`), puis http://127.0.0.1:8000. Par défaut l'application démarre en mode `prod` et exige une clé secrète `OUTILLAGE_SECRET_KEY`.

## 2. Les trois familles de matériel

1. **Outils personnels** : appartiennent à un salarié. Le propriétaire est immuable ; le détenteur actuel peut changer (prêt, transfert).
2. **Outils d'agence** : pool partagé d'une agence, réservables par tous les membres (échelles, disqueuses, échafaudages, multimètres...). Peuvent composer un coffret (outil parent + éléments), avoir un tarif journalier d'usage, être sortis définitivement du parc (vendu, rebut, don, vol, perte).
3. **EPI** : casques, harnais, chaussures de sécurité, gants, lunettes, protections auditives, tapis isolants. Assignés à une personne, avec date de péremption et suivi d'usure.

## 3. Rôles et hiérarchie

Cinq rôles :
- **Administrateur (`admin`)** : voit et gère tout, toutes agences.
- **Directeur d'agence (`directeur_agence`)** : dirige une agence, n'a pas de responsable, fixe les budgets de son agence.
- **Chargé d'affaires (`charge_affaires`)** : rattaché à un directeur d'agence, hérite de son agence.
- **Magasinier (`magasinier`)** : niveau manager pour une agence donnée (outils, maintenance, stock), mais ne gère pas les comptes utilisateurs. Créé par l'administrateur ou par un directeur d'agence de la même agence.
- **Personnel de chantier (`gars_chantier`)** : rattaché à un chargé d'affaires, hérite de son agence. Rôle le plus bas, seul rôle qui n'est pas « manager ».

Règles de création de compte : chaque rôle ne peut créer que le rôle directement en dessous dans la hiérarchie de rattachement (admin → directeur, directeur → chargé d'affaires ou magasinier, chargé d'affaires → personnel de chantier ; le personnel de chantier ne peut créer personne). Un non-admin qui crée un compte en devient automatiquement le responsable et transmet son agence.

Visibilité en cascade : un utilisateur voit ses subordonnés directs ET indirects. L'admin voit tout. Cette cascade filtre les outils personnels visibles, la page « Équipe », les portées « Mon équipe » des réservations/prêts, et les outils de l'assistant IA.

Notion de « manager » : tout rôle sauf personnel de chantier (donc directeur, chargé d'affaires, magasinier et admin). Les managers accèdent aux pages Équipe (sauf magasinier), Finances, Étiquettes, Garanties, Maintenance, Stock, Chantiers, Import, et peuvent créer/modifier les outils d'agence.

Isolation stricte entre agences pour tout ce qui appartient à une agence (outils, EPI, chantiers, tickets, stock, budgets, pertes) : 403 hors périmètre, sauf pour l'administrateur qui voit toutes les agences.

## 4. Les écrans de l'application

**Connexion / Mon profil** : identifiant + mot de passe, session mémorisée. Le profil regroupe coordonnées, changement de mot de passe, préférences de notification (in-app/email/push), agenda externe (lien ICS secret), choix du thème (clair/sombre/automatique), export de ses données personnelles (RGPD).

**Accueil (tableau de bord)** : tuiles de synthèse, bloc « En retard » (réservations et prêts en retard, relance possible), bloc « À contrôler » (calculé via `/inspections/due`), outils à signaler.

**Mes outils / Outils d'un salarié**, **Agence (Outillage & EPI)**, **EPI** : listes filtrables avec recherche serveur et pagination, fiche outil unifiée accessible via `#/outil/:kind/:id` (état, contrôle, garantie, emprunteur, accessoires, tickets ouverts, galerie photo, QR code), accessible aussi en scannant un code (`#/scan`, `#/code/:code`) ou par la recherche globale (bouton « Rechercher » ou touche `/`).

**Réservations / Mes réservations** : calendrier (Jour/Semaine/Mois), réservation immédiate ou future, retrait anticipé, validation par un responsable si la règle l'exige, liste d'attente avec offre à durée limitée, indisponibilités planifiées, réservations récurrentes, réservation d'un coffret complet, retour groupé, signature électronique, bon de sortie/décharge PDF envoyable par email, rattachement à un chantier.

**Prêts externes / Entre collègues** : prêt à un tiers extérieur, transfert d'un outil personnel entre deux salariés avec confirmation obligatoire de la partie qui n'a pas déclaré. Un transfert agence-agence existe aussi pour prêter un outil d'agence à une autre agence.

**Maintenance** (managers) : tickets ouverts automatiquement (signalement d'un problème, retour avec accessoire manquant) ou manuellement, suivi complet (prestataire, coûts, garantie), sorties de parc à valider, statistiques.

**Stock** (managers) : consommables par agence, mouvements entrée/sortie/inventaire avec solde, alerte de stock bas.

**Chantiers** : création, clôture (bloquée si du matériel y est encore sorti), fiche avec coût d'usage du matériel et consommables délivrés.

**Contrôles / Étalonnages / Habilitations** : contrôle périodique avec checklist configurable, étalonnage des instruments de mesure, habilitations personnelles requises pour certains types d'outils (bloquant ou avertissant selon les paramètres).

**Équipe / Utilisateurs** (managers sauf magasinier) : cascade, création, réinitialisation de mot de passe, réaffectation du matériel avant désactivation, anonymisation RGPD (admin), assistant de départ guidé.

**Finances** (managers) : vue d'ensemble, actifs et amortissement, coût total de possession, pertes et litiges, budgets par catégorie et par année.

**Import** (managers) : import Excel/CSV d'outils, d'EPI ou d'utilisateurs, avec aperçu, association de colonnes, simulation avant validation, relecture du classeur Excel de l'agence.

**Exports** (managers) : téléchargement CSV/Excel de tous les jeux de données ; gestion des clés d'API en lecture seule pour un outil de reporting externe (admin).

**Étiquettes** (managers) : impression en QR code et/ou code-barres, trois gabarits.

**Sauvegardes** (admin) : création, vérification d'intégrité, téléchargement, suppression, reprise de la synchronisation Excel en attente.

**Paramètres** (admin) : agences, email/SMTP, tous les seuils et périodicités de l'application, journal d'audit, tâches planifiées, suivi de l'assistant IA (questions sans réponse, retours d'utilité).

**Assistant** : bulle de chat flottante sur toutes les pages (voir section 9).

## 5. Historique d'état

Toute modification de l'état (0-5), du statut ou du motif d'un outil personnel, d'agence ou d'un EPI est journalisée (état avant/après, statut avant/après, source, auteur, date, commentaire). Accessible via le bouton « Historique » de chaque carte ou de la fiche outil.

## 6. Intégrations « best effort »

- **Synchronisation Excel** : la création d'un outil d'agence ajoute toujours une ligne au registre Excel de l'agence (`Source/Inventaire matériel <agence>.xlsx`). En mode complet (réglable dans les paramètres), les modifications et les sorties de parc sont aussi répercutées. Si le fichier est verrouillé (ouvert dans Excel) ou absent, l'action réussit quand même côté application, un avertissement s'affiche, et la mise à jour est automatiquement rejouée plus tard. L'application peut aussi relire un classeur Excel déposé sur le serveur pour remettre la base à jour (import, avec simulation).
- **Email au magasinier / aux responsables** : signalements, statuts problématiques, stock bas, digest quotidien de notifications. Jamais bloquant.
- **Notifications push** (navigateur, avec abonnement explicite) en complément des notifications en application et par email.
- **Assistant IA** : si une clé Anthropic est configurée côté serveur, les réponses et les outils de consultation sont fournis par Claude ; sinon un mode local hors ligne répond par recherche de mots-clés dans ce document.

## 7. Règles métier importantes

- Un outil personnel signalé perdu/endommagé/en réparation ne peut être ni prêté à l'extérieur ni transféré à un collègue.
- Une réservation d'outil d'agence qui commence maintenant (ou presque) vaut prise en charge immédiate ; pas de chevauchement de créneaux sur un même outil ; fin toujours après le début.
- Retour d'un outil : état 0 → hors service (casse), état 1 → réparation, sinon disponible ; un accessoire manquant au retour ouvre un ticket de maintenance.
- Un transfert entre collègues ne peut être confirmé/refusé que par la partie qui n'a pas déclaré.
- Un coffret et ses éléments ne peuvent pas être réservés séparément en même temps.
- Une sortie de parc définitive libère (en option) le code unique de l'outil et l'exclut des listes actives, sans effacer son historique ni ses statistiques financières.
- Codes uniques globaux entre outils personnels, outils d'agence et EPI.
- Tout paramètre chiffré (périodicité de contrôle, seuils d'alerte, jours avant péremption, durée d'amortissement…) est réglable par l'administrateur et n'est jamais une obligation réglementaire imposée par défaut ; les valeurs de départ sont explicitement marquées comme étant à valider par le responsable concerné.

## 8. Aspects techniques

**Backend** (`backend/app/`) : modèles répartis en plusieurs fichiers (`models.py` pour le cœur, `models_ext.py`, `models_p2.py` à `models_p9.py` pour les phases suivantes), une trentaine de routers, migrations légères numérotées avec sauvegarde automatique de la base avant chaque nouvelle migration, tâches planifiées (alertes, digests, purge, sauvegardes, synchronisation Excel, nettoyage des fichiers orphelins), file d'idempotence pour les écritures rejouées depuis le mode hors ligne du client.

**Frontend** (`frontend/`) : `service-worker.js` (API jamais mise en cache, code source réseau-prioritaire), file d'attente hors ligne (IndexedDB) pour les signalements faits sans réseau, générateurs maison de code-barres et de QR code (aucune dépendance externe), thème clair/sombre par jetons de couleur CSS, recherche globale, modales de confirmation (aucun `window.confirm`/`window.prompt`).

**Sécurité** : mots de passe hachés bcrypt, JWT avec rotation des jetons de rafraîchissement, contrôles de rôle ET de périmètre d'agence côté serveur sur chaque route, échappement HTML systématique côté client, secrets jamais renvoyés par l'API ni journalisés, clés d'API en lecture seule pour l'intégration externe, RGPD (export et anonymisation).

**Mise en ligne** : Vercel (Paris) avec PostgreSQL et stockage privé chez Supabase (Paris, plan gratuit, sans sauvegarde automatique) ; le mode local reste en SQLite. Procédure et différences : `DEPLOIEMENT.md`. En production, l'assistant IA reste désactivé tant qu'aucune clé API n'est fournie.

## 9. Assistant IA (chatbot)

Bulle flottante disponible sur toutes les pages une fois connecté, adaptée au rôle de la personne connectée. Deux modes : si une clé API Anthropic est configurée côté serveur (`ANTHROPIC_API_KEY`), les réponses sont générées par Claude (modèle configurable via `OUTILLAGE_ASSISTANT_MODEL`) ; sinon un mode local hors ligne renvoie les passages les plus pertinents de ce document.

En mode Claude, l'assistant peut aussi :
- **consulter les données** de l'application (outils, réservations, contrôles, tickets…) via des outils en lecture seule qui appliquent exactement les mêmes règles de périmètre que le reste de l'application — il ne peut jamais montrer à quelqu'un des données auxquelles cette personne n'aurait pas accès autrement ;
- **proposer une action** (réserver un outil, signaler un problème, annuler une réservation) sous forme d'une carte à confirmer explicitement : rien n'est jamais exécuté automatiquement, le serveur revalide entièrement la proposition et rédige lui-même le résumé affiché ;
- **extraire des informations depuis une photo** d'un outil ou de sa plaque signalétique pour pré-remplir (jamais enregistrer directement) le formulaire de création.

Toute donnée que l'assistant lit en base est traitée comme non fiable et ne peut jamais être interprétée comme une instruction, pour se prémunir d'une tentative d'injection via un nom d'outil ou un commentaire.

## 10. État d'avancement

- Backend et frontend complets pour les phases 0 à 9, plus les items les plus importants des phases 10 (recherche globale, thème sombre, remplacement des boîtes de dialogue natives) et 11 (health/readiness, versionnage, purge des fichiers orphelins, suite de bout en bout en navigateur réel versionnée dans le projet).
- **856 vérifications d'intégration** (`backend/smoke_test.py`) toutes vertes, et **61 vérifications en navigateur réel** (`tools/e2e/`) toutes vertes.
- Points restants, honnêtement : intégration continue non branchée sur une plateforme (scripts prêts), logs structurés JSON absents, pas de Dockerfile, pas de notes PostgreSQL, guides opérationnels/utilisateurs à rédiger séparément, Web Push jamais testé en conditions réelles de production, uploads accessibles par URL non devinable mais sans contrôle d'accès applicatif.

Pour tout le détail (modèle de données, API, règles par flux, chaque phase en profondeur), voir `DOCUMENTATION_COMPLETE.md`.
