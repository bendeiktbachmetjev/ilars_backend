-- Keep only patient BENAS; remove all other patients and their data (CASCADE).
-- Does NOT touch doctors, hospitals, or auth.
--
-- Prerequisites: PostgreSQL, same DB as the app (Supabase/Railway/etc.).
--
-- Run (after backup):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f backend/scripts/keep_only_patient_benas.sql
--
-- Or paste into Supabase SQL Editor and execute as one transaction.

BEGIN;

-- 1) Show who will be kept (case-insensitive match on patient_code)
SELECT id, patient_code, created_at
FROM patients
WHERE UPPER(TRIM(patient_code)) = 'BENAS';

-- 2) Abort if there is no such patient or duplicate codes (should not happen)
DO $$
DECLARE
  keeper_count int;
BEGIN
  SELECT COUNT(*) INTO keeper_count
  FROM patients
  WHERE UPPER(TRIM(patient_code)) = 'BENAS';

  IF keeper_count = 0 THEN
    RAISE EXCEPTION 'No patient with code BENAS (case-insensitive). Nothing deleted. Run SELECT * FROM patients; to see codes.';
  END IF;

  IF keeper_count > 1 THEN
    RAISE EXCEPTION 'Multiple rows match BENAS. Resolve duplicates manually before running this script.';
  END IF;
END $$;

-- 3) Delete everyone else (FK tables use ON DELETE CASCADE: weekly/daily/monthly/eq5d5l entries,
--    patient_status_history, daily_steps, etc.)
DELETE FROM patients
WHERE id NOT IN (
  SELECT id
  FROM patients
  WHERE UPPER(TRIM(patient_code)) = 'BENAS'
);

-- 4) Verify
SELECT COUNT(*) AS remaining_patients FROM patients;
SELECT patient_code, id FROM patients;

COMMIT;
