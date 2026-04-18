-- Keep only patient BENAS and D99KA9JYS8PJ; remove all other patients and their data (CASCADE).
-- Does NOT touch doctors, hospitals, or auth.
--
-- Prerequisites: PostgreSQL, same DB as the app (Supabase/Railway/etc.).
--
-- Run (after backup):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/scripts/keep_only_patient_benas.sql
--
-- Or paste into Supabase SQL Editor and execute as one transaction.

BEGIN;

-- 1) Show who will be kept
SELECT id, patient_code, created_at
FROM patients
WHERE UPPER(TRIM(patient_code)) IN ('BENAS', 'D99KA9JYS8PJ');

-- 2) Abort if we have duplicates for the same code
DO $$
DECLARE
  keeper_count int;
BEGIN
  SELECT COUNT(*) INTO keeper_count
  FROM patients
  WHERE UPPER(TRIM(patient_code)) IN ('BENAS', 'D99KA9JYS8PJ');

  IF keeper_count = 0 THEN
    RAISE EXCEPTION 'No patients with codes BENAS or D99KA9JYS8PJ found. Nothing deleted. Run SELECT * FROM patients; to see codes.';
  END IF;

  IF keeper_count > 2 THEN
    RAISE EXCEPTION 'More than 2 rows match BENAS and D99KA9JYS8PJ. Resolve duplicates manually before running this script.';
  END IF;
END $$;

-- 3) Delete everyone else (FK tables use ON DELETE CASCADE: weekly/daily/monthly/eq5d5l entries,
--    patient_status_history, daily_steps, etc.)
DELETE FROM patients
WHERE id NOT IN (
  SELECT id
  FROM patients
  WHERE UPPER(TRIM(patient_code)) IN ('BENAS', 'D99KA9JYS8PJ')
);

-- 4) Verify
SELECT COUNT(*) AS remaining_patients FROM patients;
SELECT patient_code, id FROM patients;

COMMIT;
