-- Add optional email, and boolean permissions to patients table
ALTER TABLE patients ADD COLUMN IF NOT EXISTS email VARCHAR(255);
ALTER TABLE patients ADD COLUMN IF NOT EXISTS agreed_to_terms BOOLEAN DEFAULT FALSE;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS agreed_to_promos BOOLEAN DEFAULT FALSE;
