-- Migration: Add doctor_id and hospital_id to patients table
-- Patients are now linked to the doctor who created them and their hospital
-- Patient codes are completely random (not based on hospital/doctor codes) for security
-- But patient records store doctor_id and hospital_id for filtering

-- Add columns to patients table
ALTER TABLE patients 
ADD COLUMN IF NOT EXISTS doctor_id UUID REFERENCES doctors(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS hospital_id UUID REFERENCES hospitals(id) ON DELETE SET NULL;

-- Create indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_patients_doctor_id ON patients(doctor_id);
CREATE INDEX IF NOT EXISTS idx_patients_hospital_id ON patients(hospital_id);
CREATE INDEX IF NOT EXISTS idx_patients_doctor_hospital ON patients(doctor_id, hospital_id);

-- Add comments
COMMENT ON COLUMN patients.doctor_id IS 'Doctor who created/registered this patient';
COMMENT ON COLUMN patients.hospital_id IS 'Hospital where the patient was treated/operated (same as doctor hospital)';

-- Function to generate completely random patient code (12 characters: letters + numbers)
-- Code is NOT based on hospital or doctor codes for security
CREATE OR REPLACE FUNCTION generate_patient_code() RETURNS TEXT AS $$
DECLARE
  new_code TEXT;
  chars TEXT := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; -- Excludes confusing chars (0, O, I, 1)
  exists_check BOOLEAN;
BEGIN
  LOOP
    -- Generate 12-character random code
    new_code := '';
    FOR i IN 1..12 LOOP
      new_code := new_code || substr(chars, floor(random() * length(chars))::int + 1, 1);
    END LOOP;
    
    -- Check if code already exists
    SELECT EXISTS(SELECT 1 FROM patients WHERE patients.patient_code = new_code) INTO exists_check;
    
    -- Exit loop if code is unique
    EXIT WHEN NOT exists_check;
  END LOOP;
  
  RETURN new_code;
END;
$$ LANGUAGE plpgsql;
