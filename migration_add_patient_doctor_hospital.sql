-- Migration: Add doctor_id and hospital_id to patients table
-- Patients are now linked to the doctor who created them and their hospital

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
COMMENT ON COLUMN patients.hospital_id IS 'Hospital where the patient was treated/operated';
