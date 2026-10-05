-- Migration: study coordinators can VIEW the patients of every Lithuanian hospital
--
-- DEPLOY ORDER: run this on production BEFORE merging feature/coordinator-view to main.
-- Railway deploys main; the new /doctors/me, /getPatients, /getPatientDetail and /getPatientStatusHistory
-- queries read doctors.is_coordinator, so without the column they return 500 for every doctor.
--
-- 1) doctors.is_coordinator: the study organisers. A coordinator sees, read-only, the patients of every
--    Lithuanian hospital (hospitals.code starts with 'LT'): list, detail, status history.
--    It never grants a change: status changes, deleting a status change, creating patients and registry
--    linking still need the patient's own hospital (the hospital checks in src/routes/patients.py and
--    src/routes/registry.py are unchanged). The flag is set only here, by hand; no API can set it.
-- 2) patient_access_log: one row each time a coordinator reads data outside their own hospital
--    (who, which patient, what, when). Doctors' reads of their own hospital are not logged.
--
-- Safety:
--   * Additive. ADD COLUMN ... NOT NULL DEFAULT false is metadata-only on Postgres 11+ (no table rewrite).
--     Every existing doctor gets is_coordinator = false, so nothing changes until a doctor is flagged.
--     Old backend code ignores the column and the table.
--   * Row-level security (RLS): the backend connects as `postgres` (rolbypassrls = true), so policies never
--     filter its queries; the WHERE clauses and hospital checks in the routes are the real gate.
--     patient_access_log gets RLS with no policy, so the public Supabase API cannot read or write it.
--
-- Known limit: the patient code is also the patient's only credential in the patient app (X-Patient-Code).
-- A coordinator sees every Lithuanian patient's code, as a doctor sees their own hospital's codes;
-- patient-app calls made with a code are not hospital-checked or logged. Flag only people allowed that access.
--
-- Flag the coordinators (run by hand):
--   UPDATE doctors SET is_coordinator = true WHERE email IN ('<email 1>', '<email 2>');
-- Read the log:
--   SELECT l.accessed_at, d.email, p.patient_code, l.action
--   FROM patient_access_log l JOIN doctors d ON d.id = l.doctor_id LEFT JOIN patients p ON p.id = l.patient_id
--   ORDER BY l.accessed_at DESC;
--
-- Idempotent: re-running is a no-op.

ALTER TABLE doctors ADD COLUMN IF NOT EXISTS is_coordinator boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN doctors.is_coordinator IS
  'Study coordinator: may view (never change) the patients of every Lithuanian hospital. Set by hand only.';

-- No foreign keys: an audit row must outlive the doctor or patient it names.
CREATE TABLE IF NOT EXISTS patient_access_log (
  id bigserial PRIMARY KEY,
  doctor_id uuid NOT NULL,
  patient_id uuid,                 -- NULL for the patient list
  action text NOT NULL CHECK (action IN ('list', 'detail', 'status_history')),
  accessed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_patient_access_log_accessed_at ON patient_access_log (accessed_at);

ALTER TABLE patient_access_log ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE patient_access_log IS
  'Coordinator reads outside their own hospital: who (doctor_id), which patient (NULL = the list), what, when.';
