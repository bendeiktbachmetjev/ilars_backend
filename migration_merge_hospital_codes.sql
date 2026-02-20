-- Migration: Merge hospital_codes into hospitals table
-- Simplifies structure by moving code directly into hospitals table
-- Removes unnecessary hospital_codes table

-- Step 1: Add code column to hospitals table
ALTER TABLE hospitals 
ADD COLUMN IF NOT EXISTS code TEXT UNIQUE;

-- Step 2: Migrate active codes from hospital_codes to hospitals
-- Only migrate codes that are active (is_active = true)
UPDATE hospitals h
SET code = (
    SELECT hc.code 
    FROM hospital_codes hc 
    WHERE hc.hospital_id = h.id 
    AND hc.is_active = true 
    LIMIT 1
)
WHERE EXISTS (
    SELECT 1 
    FROM hospital_codes hc 
    WHERE hc.hospital_id = h.id 
    AND hc.is_active = true
);

-- Step 3: Generate codes for hospitals that don't have one yet
DO $$
DECLARE
    hospital_rec RECORD;
    new_code TEXT;
    chars TEXT := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    exists_check BOOLEAN;
BEGIN
    FOR hospital_rec IN SELECT id FROM hospitals WHERE code IS NULL LOOP
        LOOP
            -- Generate 12-character code
            new_code := '';
            FOR i IN 1..12 LOOP
                new_code := new_code || substr(chars, floor(random() * length(chars))::int + 1, 1);
            END LOOP;
            
            -- Check if code already exists in hospitals
            SELECT EXISTS(SELECT 1 FROM hospitals WHERE hospitals.code = new_code) INTO exists_check;
            
            -- Exit loop if code is unique
            EXIT WHEN NOT exists_check;
        END LOOP;
        
        -- Update hospital with generated code
        UPDATE hospitals SET code = new_code WHERE id = hospital_rec.id;
    END LOOP;
END $$;

-- Step 4: Update generate_hospital_code() function to check hospitals.code instead of hospital_codes
CREATE OR REPLACE FUNCTION generate_hospital_code() RETURNS TEXT AS $$
DECLARE
    new_code TEXT;
    chars TEXT := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; -- Excludes confusing chars (0, O, I, 1)
    exists_check BOOLEAN;
BEGIN
    LOOP
        -- Generate 12-character code
        new_code := '';
        FOR i IN 1..12 LOOP
            new_code := new_code || substr(chars, floor(random() * length(chars))::int + 1, 1);
        END LOOP;
        
        -- Check if code already exists in hospitals table
        SELECT EXISTS(SELECT 1 FROM hospitals WHERE hospitals.code = new_code) INTO exists_check;
        
        -- Exit loop if code is unique
        EXIT WHEN NOT exists_check;
    END LOOP;
    
    RETURN new_code;
END;
$$ LANGUAGE plpgsql;

-- Step 5: Create index on hospitals.code for faster lookups
CREATE INDEX IF NOT EXISTS idx_hospitals_code ON hospitals(code) WHERE code IS NOT NULL;

-- Step 6: Drop old indexes related to hospital_codes
DROP INDEX IF EXISTS idx_hospitals_code_old;
DROP INDEX IF EXISTS idx_hospital_codes_hospital;

-- Step 7: Drop hospital_codes table (CASCADE will handle foreign key constraints)
DROP TABLE IF EXISTS hospital_codes CASCADE;

-- Add comment
COMMENT ON COLUMN hospitals.code IS '12-character code for doctor registration. Unique, can be NULL if not set.';
