-- ============================================================================
-- MIGRATION 2026-09-04 -- tenant_registry.tenants: refuse reserved slugs.
--
-- Adds the CONSTRAINT tenants_slug_not_reserved that
-- postgres/init/sql/40-tenant-registry.sql now declares inline, to a database
-- that already has the table.
--
-- WHY A SEPARATE FILE, given that control-plane-apply.sh DOES re-run the init
-- file against the live admin database on every `make control-plane`:
-- everything in that file is CREATE ... IF NOT EXISTS, and IF NOT EXISTS does
-- not reach inside an existing table to add a constraint to it. Against a
-- cluster whose tenant_registry.tenants already exists, the init file is a
-- no-op for this change. It lands on fresh clusters only, and a rule that
-- only protects machines nobody has is not a rule.
--
-- WHY THIS DIRECTORY. Before this file the repo had no SQL migration path at
-- all. postgres/init/sql/ is the FIRST BOOT path -- docker-entrypoint-initdb.d
-- runs it once, on an empty pgdata volume -- and every Odoo-side migration
-- lives inside its own addon's migrations/ folder, keyed to that module's
-- version. Neither fits control-plane DDL aimed at a database that already
-- exists. postgres/migrations/ is the sibling of postgres/init/, so the two
-- halves of one schema's history sit next to each other, and the ISO date
-- prefix sorts the directory in the order it would be replayed.
--
-- Nothing mounts this directory into a container, deliberately. A migration
-- that alters a live table is a decision someone makes, not a side effect of
-- starting the stack.
--
-- HOW TO RUN IT -- once, by hand, from the repo root:
--
--     docker compose -p "$COMPOSE_PROJECT_NAME" --env-file .env \
--         -f compose/odoo.yml -f compose/odoo.dev.yml \
--         exec -T postgres psql -v ON_ERROR_STOP=1 --no-psqlrc \
--         -U "$POSTGRES_USER" -d "$ATHERA_ADMIN_DB" \
--         < postgres/migrations/2026-09-04-tenants-slug-not-reserved.sql
--
-- IDEMPOTENT. Postgres has no ADD CONSTRAINT ... IF NOT EXISTS, so the guard
-- is an explicit pg_constraint lookup. Running it a second time is a no-op,
-- and so is running it against a fresh cluster that already received the
-- constraint from the init file.
--
-- LOCKING. ALTER TABLE ... ADD CONSTRAINT takes ACCESS EXCLUSIVE on
-- tenant_registry.tenants and validates every existing row. The table holds a
-- handful of rows and -- checked against the live control plane on 2026-09-04
-- -- none of them carries a reserved slug, so the lock is milliseconds and the
-- validation cannot fail. If that ever stops being true, the ADD raises
-- rather than corrupting anything: fix the offending row first.
-- ============================================================================

DO $mig$
BEGIN
  -- A cluster where the control plane was never applied has nothing to alter.
  -- Say so and stop, rather than failing with "relation does not exist" and
  -- looking like a broken migration.
  IF to_regclass('tenant_registry.tenants') IS NULL THEN
    RAISE NOTICE 'tenant_registry.tenants does not exist here -- run `make control-plane` first; nothing done';
    RETURN;
  END IF;

  IF EXISTS (
    SELECT 1
      FROM pg_constraint c
      JOIN pg_class t ON t.oid = c.conrelid
      JOIN pg_namespace n ON n.oid = t.relnamespace
     WHERE n.nspname = 'tenant_registry'
       AND t.relname = 'tenants'
       AND c.conname = 'tenants_slug_not_reserved'
  ) THEN
    RAISE NOTICE 'tenants_slug_not_reserved is already present; nothing done';
    RETURN;
  END IF;

  -- Kept identical, character for character, to the constraint declared in
  -- postgres/init/sql/40-tenant-registry.sql. Two spellings of one rule is how
  -- a fresh cluster and a migrated one end up refusing different names.
  ALTER TABLE tenant_registry.tenants
    ADD CONSTRAINT tenants_slug_not_reserved CHECK (
      slug NOT IN ('admin', 'app', 'auth', 'insight', 'mail', 'odoo', 'www')
    );

  RAISE NOTICE 'added tenants_slug_not_reserved';
END
$mig$;
