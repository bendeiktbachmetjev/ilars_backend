-- Migration: Replace patient_steps (JSONB) with daily_steps (one row per day per patient)
-- Run this in the Supabase SQL Editor

-- 1. Create new table
CREATE TABLE IF NOT EXISTS daily_steps (
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    step_date DATE NOT NULL,
    step_count INTEGER NOT NULL DEFAULT 0,
    source VARCHAR(50) DEFAULT 'unknown',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (patient_id, step_date)
);

-- 2. Migrate existing data from patient_steps JSONB into daily_steps rows
INSERT INTO daily_steps (patient_id, step_date, step_count, source)
SELECT
    ps.patient_id,
    (kv.key)::DATE,
    (kv.value)::INTEGER,
    'apple_health'
FROM patient_steps ps,
     jsonb_each_text(ps.steps) AS kv(key, value)
ON CONFLICT (patient_id, step_date) DO NOTHING;

-- 3. Drop old table
DROP TABLE IF EXISTS patient_steps;
