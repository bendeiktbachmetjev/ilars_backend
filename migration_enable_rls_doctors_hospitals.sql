-- Migration: Enable Row Level Security on doctors and hospitals tables
--
-- Closes Supabase security advisor `rls_disabled_in_public` (CRITICAL) for the only two
-- public tables that still had RLS disabled: public.doctors and public.hospitals.
--
-- Safety notes (why this does not change any application behavior):
--   * The backend connects as role `postgres` (table owner, rolbypassrls=true) and therefore
--     bypasses RLS entirely, so its full read/write access to these tables is unchanged.
--   * The doctor web portal and the mobile app reach these tables ONLY through the backend
--     REST API. No application code uses the Supabase anon/service keys, so enabling RLS only
--     revokes direct anon/authenticated access via /rest/v1 -- exactly the exposure flagged.
--   * No policies are added: no non-bypass role legitimately accesses these tables, so there is
--     nothing to allow. (Supabase will report this as info-level `rls_enabled_no_policy`, which
--     is expected and intentional.)
--   * No FORCE ROW LEVEL SECURITY: it would change nothing for a BYPASSRLS owner.
--
-- Idempotent: re-running is a no-op.

ALTER TABLE public.doctors ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.hospitals ENABLE ROW LEVEL SECURITY;
