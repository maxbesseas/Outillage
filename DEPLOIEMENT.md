# Mise en ligne : Vercel + Supabase gratuit

Vercel exécute l'application (région Paris, `cdg1`). Supabase, région Paris (`eu-west-3`), conserve la base PostgreSQL et les fichiers. Vercel et Supabase sont des sociétés américaines : les données sont hébergées à Paris, mais confiées à des prestataires américains.

En local, rien ne change : sans `OUTILLAGE_DATABASE_URL`, l'application utilise SQLite et le dossier `uploads/` (`backend/run_dev.ps1`).

## Limites du plan gratuit Supabase

| Sujet | Limite | Conséquence |
| --- | --- | --- |
| Sauvegardes | Aucune sauvegarde automatique | Faire ses propres sauvegardes (section 4) |
| Base | 500 Mo | Largement suffisant au départ (base locale actuelle : moins de 1 Mo) |
| Fichiers | 1 Go | Surveiller le volume des photos et documents |
| Inactivité | Mise en pause possible après une semaine de faible activité | Le cron quotidien devrait l'éviter, sans garantie : surveiller les e-mails de Supabase |

## 1. Supabase

1. Créer un projet en région **West EU (Paris)**, avec un mot de passe de base long, à conserver dans un gestionnaire de mots de passe.
2. Dans **Connect**, relever les deux adresses du **shared pooler** : mode session (port `5432`) et mode transaction (port `6543`). La connexion directe passe par IPv6 : ne pas l'utiliser.
3. Dans **Storage**, créer un compartiment **privé**, activer le protocole S3, puis créer une clé d'accès. Cette clé ouvre tous les fichiers : elle reste côté serveur.

## 2. Préparer la base, depuis votre poste

Utiliser ici le **mode session (port 5432)**. Les valeurs restent dans le terminal, jamais dans un fichier versionné. Encoder les caractères spéciaux du mot de passe dans l'adresse (`@` devient `%40`, par exemple). Depuis `backend/`, en PowerShell :

```powershell
$env:OUTILLAGE_ENV = "prod"
$env:OUTILLAGE_SCHEDULER = "off"
$env:OUTILLAGE_SECRET_KEY = "<clé générée>"
$env:OUTILLAGE_DATABASE_URL = "postgresql://postgres.REFERENCE:motdepasse@aws-INDEX-eu-west-3.pooler.supabase.com:5432/postgres?sslmode=require"
$env:OUTILLAGE_ADMIN_PASSWORD = "<mot de passe long et unique>"
.\venv\Scripts\python.exe -m app.db_setup
.\venv\Scripts\python.exe migrate_to_postgres.py
```

`migrate_to_postgres.py` copie les outils, EPI, agences et réglages, et affiche les volumes. Il ne reprend ni les comptes, ni les jetons, ni les clés d'API, ni les journaux. Il ne modifie pas la base SQLite et refuse une cible déjà remplie.

Relancer `app.db_setup` après chaque nouvelle migration : sur Vercel, le schéma n'est pas modifié au démarrage.

## 3. Vercel

1. Plan **Hobby**, réservé à un usage personnel et non commercial, avec un seul cron par jour. Pour un usage commercial, passer au plan Pro, puis rapprocher le cron dans `vercel.json` (par exemple `*/5 * * * *`).
2. Importer le dépôt, sans framework. La configuration est dans `vercel.json`.
3. Renseigner les variables d'environnement listées dans `.env.example`, sauf `OUTILLAGE_ADMIN_PASSWORD`, inutile une fois le compte créé. `OUTILLAGE_DATABASE_URL` utilise ici le **mode transaction (port 6543)**. Ne pas ajouter `ANTHROPIC_API_KEY` : l'assistant IA reste désactivé et aucune donnée n'est envoyée.
4. Déployer, puis contrôler `/health/ready` et se connecter avec `admin` : le mot de passe doit être changé à la première connexion.

## 4. Sauvegardes

Le plan gratuit n'en fait aucune. Depuis un poste équipé des outils PostgreSQL, dans une version au moins égale à celle du serveur, avec l'adresse en mode session (port 5432) :

```powershell
pg_dump --format=custom --file=outillage.dump "<adresse de la base>"
```

Le fichier obtenu contient toutes les données, comptes compris : le garder hors du dépôt. Copier aussi les fichiers du compartiment.

## Différences avec le mode local

| Sujet | Sur Vercel |
| --- | --- |
| Tâches planifiées | `/cron/tick` une fois par jour, entre 7 h et 8 h UTC, protégé par `CRON_SECRET`. Réservations non retirées, listes d'attente et alertes ne sont traitées qu'à ce moment-là |
| Récapitulatif e-mail | Part seulement si le cron tombe dans l'heure du réglage `alert.digest_hour` : garder `7`, ou changer les deux ensemble |
| Fichiers envoyés | Compartiment Supabase privé (protocole S3) ; `/uploads/...` redirige vers une URL signée valable 5 minutes |
| Taille des envois | 4 Mo maximum par document (limite Vercel : 4,5 Mo par requête) |
| Sauvegardes | À votre charge (section 4) ; l'écran Sauvegardes de l'application reste vide |
| Synchronisation Excel | Désactivée : aucun classeur sur le serveur. Exports et imports par envoi de fichier conservés |
| Adresse IP | Lue dans `X-Forwarded-For` (`OUTILLAGE_TRUST_PROXY`), à n'activer que derrière un proxy qui réécrit cet en-tête |

## Tester sur PostgreSQL

`smoke_test.py` utilise SQLite. La vérification de la mise en ligne l'a aussi exécuté sur PostgreSQL 16, partie sauvegardes SQLite exclue. Différence à garder en tête : PostgreSQL applique les clés étrangères, pas SQLite.
