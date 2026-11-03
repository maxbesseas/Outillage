-- Rôle limité pour l'application : lit et écrit les données, sans pouvoir modifier le schéma.
-- 1. Remplacer le mot de passe avant de lancer ce script, sans enregistrer le fichier modifié.
-- 2. Sur Vercel, utiliser ce rôle dans OUTILLAGE_DATABASE_URL (pooler : fauche_app.REFERENCE).
-- 3. Garder le compte postgres pour app.db_setup, puis relancer ce script après chaque migration.
do $$
declare t record;
begin
  if not exists (select 1 from pg_roles where rolname = 'fauche_app') then
    create role fauche_app login password 'REMPLACER_PAR_UN_MOT_DE_PASSE_LONG';
  end if;
  grant usage on schema public to fauche_app;
  grant select, insert, update, delete on all tables in schema public to fauche_app;
  grant usage, select on all sequences in schema public to fauche_app;
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('drop policy if exists fauche_app_all on public.%I', t.tablename);
    execute format('create policy fauche_app_all on public.%I to fauche_app using (true) with check (true)', t.tablename);
  end loop;
end $$;
