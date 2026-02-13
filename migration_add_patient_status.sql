-- Migration: Add status column to patients table
-- Status: 'active' = patient is participating; 'inactive' = deceased, refused, lost to follow-up, etc.
-- Inactive patients remain in DB but are hidden from main list; shown in separate section

-- Add status column with default 'active' for existing rows
ALTER TABLE patients 
ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active' 
CHECK (status IN ('active', 'inactive'));

-- Add optional reason for inactivation (e.g. deceased, refused, lost_to_follow_up)
ALTER TABLE patients 
ADD COLUMN IF NOT EXISTS status_reason TEXT;

-- Create index for filtering by status
CREATE INDEX IF NOT EXISTS idx_patients_status ON patients(status);
CREATE INDEX IF NOT EXISTS idx_patients_hospital_status ON patients(hospital_id, status);

-- Add comments
COMMENT ON COLUMN patients.status IS 'active = participating in study; inactive = archived (deceased, refused, etc.)';
COMMENT ON COLUMN patients.status_reason IS 'Optional reason for inactive status';
