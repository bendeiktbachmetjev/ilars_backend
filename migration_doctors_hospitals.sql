-- Migration: Doctors and Hospitals tables
-- Run this migration to add doctor profile and hospital support
--
-- To run: connect to your PostgreSQL (e.g. Supabase) and execute this file:
--   psql $DATABASE_URL -f migration_doctors_hospitals.sql

-- Hospitals table (admin-managed list, doctors select from dropdown)
CREATE TABLE IF NOT EXISTS hospitals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Doctors table (linked to Firebase UID from Google Sign-In)
CREATE TABLE IF NOT EXISTS doctors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firebase_uid TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL,
  first_name TEXT,
  last_name TEXT,
  hospital_id UUID REFERENCES hospitals(id) ON DELETE SET NULL,
  date_of_birth DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_doctors_firebase_uid ON doctors (firebase_uid);
CREATE INDEX IF NOT EXISTS idx_doctors_email ON doctors (email);
CREATE INDEX IF NOT EXISTS idx_doctors_hospital ON doctors (hospital_id);

-- Insert default hospitals (can be extended via admin or separate migration)
INSERT INTO hospitals (name) VALUES
  ('Vilnius University Hospital Santaros Klinikos'),
  ('Kaunas Clinics of Lithuanian University of Health Sciences'),
  ('Klaipėda University Hospital'),
  ('Šiauliai Republican Hospital'),
  ('Panevėžys County Hospital')
ON CONFLICT (name) DO NOTHING;
