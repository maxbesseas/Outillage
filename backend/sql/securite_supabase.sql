-- À lancer dans Supabase > SQL Editor, après chaque nouvelle migration qui crée des tables.
-- 1. Ferme l'API publique de Supabase : sans règle, ses rôles anon et authenticated ne lisent plus aucune ligne.
--    L'application n'est pas touchée : elle se connecte avec le propriétaire des tables ou avec le rôle ci-dessous.
do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'public' loop
    execute format('alter table public.%I enable row level security', t.tablename);
    if exists (select 1 from pg_roles where rolname = 'anon') then
      execute format('revoke all on public.%I from anon', t.tablename);
    end if;
    if exists (select 1 from pg_roles where rolname = 'authenticated') then
      execute format('revoke all on public.%I from authenticated', t.tablename);
    end if;
  end loop;
end $$;
