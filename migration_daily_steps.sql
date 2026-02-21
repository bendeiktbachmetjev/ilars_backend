-- Migration: Add patient_steps table for tracking daily step counts
-- Run this in the Supabase SQL Editor
--
-- Structure: one row per patient, steps stored as JSONB
-- Example: {"2025-01-15": 5000, "2025-01-16": 7200, "2025-01-17": 3400}
--
-- If you already ran the previous migration (daily_steps), drop it first:
-- DROP TABLE IF EXISTS daily_steps;

CREATE TABLE IF NOT EXISTS patient_steps (
    patient_id UUID PRIMARY KEY REFERENCES patients(id) ON DELETE CASCADE,
    steps JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
