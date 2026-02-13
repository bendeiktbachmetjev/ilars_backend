-- Migration: Add doctor_id and hospital_id to patients table
-- Patients are now linked to the doctor who created them and their hospital
-- Patient codes will be generated as: {hospital_code}{doctor_code}{random_digits}

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

-- Function to generate patient code: {hospital_code}{doctor_code}{random_6_digits}
CREATE OR REPLACE FUNCTION generate_patient_code(p_hospital_code TEXT, p_doctor_code TEXT) RETURNS TEXT AS $$
DECLARE
  new_code TEXT;
  random_part TEXT;
  exists_check BOOLEAN;
BEGIN
  -- Validate inputs
  IF p_hospital_code IS NULL OR p_doctor_code IS NULL THEN
    RAISE EXCEPTION 'Hospital code and doctor code are required';
  END IF;
  
  LOOP
    -- Generate 6 random digits
    random_part := '';
    FOR i IN 1..6 LOOP
      random_part := random_part || floor(random() * 10)::int;
    END LOOP;
    
    -- Combine: hospital_code (12 chars) + doctor_code (4 chars) + random (6 digits) = 22 chars
    new_code := upper(p_hospital_code) || upper(p_doctor_code) || random_part;
    
    -- Check if code already exists
    SELECT EXISTS(SELECT 1 FROM patients WHERE patients.patient_code = new_code) INTO exists_check;
    
    -- Exit loop if code is unique
    EXIT WHEN NOT exists_check;
  END LOOP;
  
  RETURN new_code;
END;
$$ LANGUAGE plpgsql;
