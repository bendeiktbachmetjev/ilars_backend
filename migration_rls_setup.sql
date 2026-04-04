-- Migration: Enable Row Level Security (RLS) on all patient data tables

-- 1. Enable RLS and FORCE RLS on all relevant tables
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE patients FORCE ROW LEVEL SECURITY;

ALTER TABLE patient_status_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE patient_status_history FORCE ROW LEVEL SECURITY;

ALTER TABLE weekly_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_entries FORCE ROW LEVEL SECURITY;

ALTER TABLE daily_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE daily_entries FORCE ROW LEVEL SECURITY;

ALTER TABLE monthly_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE monthly_entries FORCE ROW LEVEL SECURITY;

ALTER TABLE eq5d5l_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE eq5d5l_entries FORCE ROW LEVEL SECURITY;

ALTER TABLE IF EXISTS daily_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS daily_steps FORCE ROW LEVEL SECURITY;

-- 2. Create System Bypass Policies (for internal server tasks, if any)
CREATE POLICY system_bypass_patients ON patients FOR ALL USING (current_setting('app.current_role', true) = 'system');
CREATE POLICY system_bypass_history ON patient_status_history FOR ALL USING (current_setting('app.current_role', true) = 'system');
CREATE POLICY system_bypass_weekly ON weekly_entries FOR ALL USING (current_setting('app.current_role', true) = 'system');
CREATE POLICY system_bypass_daily ON daily_entries FOR ALL USING (current_setting('app.current_role', true) = 'system');
CREATE POLICY system_bypass_monthly ON monthly_entries FOR ALL USING (current_setting('app.current_role', true) = 'system');
CREATE POLICY system_bypass_eq5d5l ON eq5d5l_entries FOR ALL USING (current_setting('app.current_role', true) = 'system');
CREATE POLICY system_bypass_steps ON daily_steps FOR ALL USING (current_setting('app.current_role', true) = 'system');

-- 3. Create Doctor Policies
-- Doctors can access patients from their hospital or directly assigned to them
CREATE POLICY doctor_access_patients ON patients FOR ALL
    USING (
        current_setting('app.current_role', true) = 'doctor' 
        AND (
            hospital_id = NULLIF(current_setting('app.hospital_id', true), '')::uuid
            OR
            doctor_id = NULLIF(current_setting('app.doctor_id', true), '')::uuid
        )
    );

-- Helper function to check if doctor has access to a specific patient
-- This avoids repeating the subquery in every table policy
CREATE OR REPLACE FUNCTION doctor_has_patient_access(p_id uuid) RETURNS boolean AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM patients
        WHERE id = p_id
        AND (
            hospital_id = NULLIF(current_setting('app.hospital_id', true), '')::uuid
            OR
            doctor_id = NULLIF(current_setting('app.doctor_id', true), '')::uuid
        )
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
-- Notice SECURITY DEFINER: it runs with privileges of the creator to read the patients table without infinite recursion

CREATE POLICY doctor_access_history ON patient_status_history FOR ALL
    USING (current_setting('app.current_role', true) = 'doctor' AND doctor_has_patient_access(patient_id));

CREATE POLICY doctor_access_weekly ON weekly_entries FOR ALL
    USING (current_setting('app.current_role', true) = 'doctor' AND doctor_has_patient_access(patient_id));

CREATE POLICY doctor_access_daily ON daily_entries FOR ALL
    USING (current_setting('app.current_role', true) = 'doctor' AND doctor_has_patient_access(patient_id));

CREATE POLICY doctor_access_monthly ON monthly_entries FOR ALL
    USING (current_setting('app.current_role', true) = 'doctor' AND doctor_has_patient_access(patient_id));

CREATE POLICY doctor_access_eq5d5l ON eq5d5l_entries FOR ALL
    USING (current_setting('app.current_role', true) = 'doctor' AND doctor_has_patient_access(patient_id));

CREATE POLICY doctor_access_steps ON daily_steps FOR ALL
    USING (current_setting('app.current_role', true) = 'doctor' AND doctor_has_patient_access(patient_id));

-- 4. Create Patient Policies
-- Patients can only access their own records
CREATE POLICY patient_access_patients ON patients FOR ALL
    USING (
        current_setting('app.current_role', true) = 'patient' 
        AND id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
    );

CREATE POLICY patient_access_history ON patient_status_history FOR ALL
    USING (current_setting('app.current_role', true) = 'patient' AND patient_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

CREATE POLICY patient_access_weekly ON weekly_entries FOR ALL
    USING (current_setting('app.current_role', true) = 'patient' AND patient_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

CREATE POLICY patient_access_daily ON daily_entries FOR ALL
    USING (current_setting('app.current_role', true) = 'patient' AND patient_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

CREATE POLICY patient_access_monthly ON monthly_entries FOR ALL
    USING (current_setting('app.current_role', true) = 'patient' AND patient_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

CREATE POLICY patient_access_eq5d5l ON eq5d5l_entries FOR ALL
    USING (current_setting('app.current_role', true) = 'patient' AND patient_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

CREATE POLICY patient_access_steps ON daily_steps FOR ALL
    USING (current_setting('app.current_role', true) = 'patient' AND patient_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

-- 5. Doctors table (Doctors should only see themselves, but for now we won't put strict RLS on doctors/hospitals 
-- since they don't contain patient PHI and are managed by firebase limits.
-- If required, you can add it here.)
