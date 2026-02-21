-- Migration: Add daily_steps table for tracking patient step counts
-- Run this in the Supabase SQL Editor

CREATE TABLE IF NOT EXISTS daily_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    step_date DATE NOT NULL DEFAULT CURRENT_DATE,
    step_count INTEGER NOT NULL DEFAULT 0,
    source VARCHAR(50) DEFAULT 'unknown',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (patient_id, step_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_steps_patient_date
    ON daily_steps (patient_id, step_date DESC);
