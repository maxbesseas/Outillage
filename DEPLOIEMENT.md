# Mise en ligne : Vercel + PostgreSQL et S3 chez Scaleway

Vercel exécute l'application (région Paris, `cdg1`). Les données au repos restent en France chez Scaleway (`fr-par`) : base PostgreSQL et fichiers. Elles transitent par Vercel, société américaine, pendant le traitement des requêtes.

En local, rien ne change : sans `OUTILLAGE_DATABASE_URL`, l'application utilise SQLite et le dossier `uploads/` (`backend/run_dev.ps1`).

## 1. Scaleway

1. Créer une base **Managed Database for PostgreSQL** en région Paris, puis une base `outillage` et un utilisateur dédié.
2. Restreindre l'accès réseau autant que possible et garder une sauvegarde automatique. Vérifier que la région de stockage des sauvegardes reste dans l'Union européenne.
3. Créer un compartiment **Object Storage** privé en région Paris, puis une clé d'API limitée à ce compartiment. Activer le versionnage : il protège les fichiers, que les sauvegardes de la base ne couvrent pas.

## 2. Préparer la base, depuis votre poste

Les valeurs restent dans le terminal, jamais dans un fichier versionné. Depuis `backend/`, en PowerShell :

```powershell
$env:OUTILLAGE_ENV = "prod"
$env:OUTILLAGE_SCHEDULER = "off"
$env:OUTILLAGE_SECRET_KEY = "<clé générée>"
$env:OUTILLAGE_DATABASE_URL = "postgresql://utilisateur:motdepasse@hote:port/outillage?sslmode=require"
$env:OUTILLAGE_ADMIN_PASSWORD = "<mot de passe long et unique>"
.\venv\Scripts\python.exe -m app.db_setup
.\venv\Scripts\python.exe migrate_to_postgres.py
```

`migrate_to_postgres.py` copie les outils, EPI, agences et réglages, et affiche les volumes. Il ne reprend ni les comptes, ni les jetons, ni les clés d'API, ni les journaux. Il ne modifie pas la base SQLite et refuse une cible déjà remplie.

Relancer `app.db_setup` après chaque nouvelle migration : sur Vercel, le schéma n'est pas modifié au démarrage.

## 3. Vercel

1. Plan **Pro** : le plan Hobby exclut l'usage commercial et limite les crons à un par jour.
2. Importer le dépôt, sans framework. La configuration est dans `vercel.json`.
3. Renseigner les variables d'environnement listées dans `.env.example`, sauf `OUTILLAGE_ADMIN_PASSWORD`, inutile une fois le compte créé. Ne pas ajouter `ANTHROPIC_API_KEY` : l'assistant IA reste désactivé et aucune donnée n'est envoyée.
4. Déployer, puis contrôler `/health/ready` et se connecter avec `admin` : le mot de passe doit être changé à la première connexion.

## Différences avec le mode local

| Sujet | Sur Vercel |
| --- | --- |
| Tâches planifiées | `/cron/tick` toutes les 5 minutes, protégé par `CRON_SECRET` |
| Fichiers envoyés | S3 privé ; `/uploads/...` redirige vers une URL signée valable 5 minutes |
| Taille des envois | 4 Mo maximum par document (limite Vercel : 4,5 Mo par requête) |
| Sauvegardes | Assurées par Scaleway ; l'écran Sauvegardes de l'application reste vide |
| Synchronisation Excel | Désactivée : aucun classeur sur le serveur. Exports et imports par envoi de fichier conservés |
| Adresse IP | Lue dans `X-Forwarded-For` (`OUTILLAGE_TRUST_PROXY`), à n'activer que derrière un proxy qui réécrit cet en-tête |

## Tester sur PostgreSQL

`smoke_test.py` utilise SQLite. La vérification de la mise en ligne l'a aussi exécuté sur PostgreSQL 16, partie sauvegardes SQLite exclue. Différence à garder en tête : PostgreSQL applique les clés étrangères, pas SQLite.
