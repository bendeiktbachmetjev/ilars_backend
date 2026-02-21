-- Migration: Replace patient_steps (JSONB) with daily_steps (one row per day per patient)
-- Run this in the Supabase SQL Editor

-- 1. Drop old tables
DROP TABLE IF EXISTS patient_steps;
DROP TABLE IF EXISTS daily_steps;

-- 2. Create new clean table
CREATE TABLE daily_steps (
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    step_date DATE NOT NULL,
    step_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (patient_id, step_date)
);
