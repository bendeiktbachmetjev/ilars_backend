-- Migration: Add hospital codes system and doctor codes
-- Hospital codes are complex 12-character codes for doctor registration
-- Only way to assign hospital to doctor is through code entry
-- Codes can be updated directly in database if needed

-- Add doctor_code to doctors table
ALTER TABLE doctors 
ADD COLUMN IF NOT EXISTS doctor_code TEXT UNIQUE;

-- Create hospital_codes table for managing hospital access codes
CREATE TABLE IF NOT EXISTS hospital_codes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  hospital_id UUID NOT NULL REFERENCES hospitals(id) ON DELETE CASCADE,
  code TEXT NOT NULL UNIQUE,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deactivated_at TIMESTAMPTZ,
  notes TEXT
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_hospitals_code ON hospital_codes (code) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_hospital_codes_hospital ON hospital_codes (hospital_id);
CREATE INDEX IF NOT EXISTS idx_doctors_code ON doctors (doctor_code);

-- Function to generate complex hospital code (12 characters: letters + numbers)
CREATE OR REPLACE FUNCTION generate_hospital_code() RETURNS TEXT AS $$
DECLARE
  code TEXT;
  chars TEXT := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; -- Excludes confusing chars (0, O, I, 1)
  exists_check BOOLEAN;
BEGIN
  LOOP
    -- Generate 12-character code
    code := '';
    FOR i IN 1..12 LOOP
      code := code || substr(chars, floor(random() * length(chars))::int + 1, 1);
    END LOOP;
    
    -- Check if code already exists
    SELECT EXISTS(SELECT 1 FROM hospital_codes WHERE code = generate_hospital_code.code) INTO exists_check;
    
    -- Exit loop if code is unique
    EXIT WHEN NOT exists_check;
  END LOOP;
  
  RETURN code;
END;
$$ LANGUAGE plpgsql;

-- Function to generate unique doctor code (4 uppercase letters)
CREATE OR REPLACE FUNCTION generate_doctor_code() RETURNS TEXT AS $$
DECLARE
  code TEXT;
  exists_check BOOLEAN;
BEGIN
  LOOP
    -- Generate 4 uppercase letters (A-Z)
    code := upper(
      chr(65 + floor(random() * 26)::int) ||
      chr(65 + floor(random() * 26)::int) ||
      chr(65 + floor(random() * 26)::int) ||
      chr(65 + floor(random() * 26)::int)
    );
    
    -- Check if code already exists
    SELECT EXISTS(SELECT 1 FROM doctors WHERE doctor_code = code) INTO exists_check;
    
    -- Exit loop if code is unique
    EXIT WHEN NOT exists_check;
  END LOOP;
  
  RETURN code;
END;
$$ LANGUAGE plpgsql;

-- Generate initial hospital codes for existing hospitals
-- These codes are created once and can be updated directly in database if needed
DO $$
DECLARE
  hospital_rec RECORD;
  new_code TEXT;
BEGIN
  FOR hospital_rec IN SELECT id, name FROM hospitals LOOP
    -- Generate a complex code
    new_code := generate_hospital_code();
    
    -- Insert code (only if no active code exists)
    INSERT INTO hospital_codes (hospital_id, code, is_active, notes)
    SELECT hospital_rec.id, new_code, true, 'Initial code for ' || hospital_rec.name
    WHERE NOT EXISTS (
      SELECT 1 FROM hospital_codes 
      WHERE hospital_id = hospital_rec.id AND is_active = true
    );
  END LOOP;
END $$;
