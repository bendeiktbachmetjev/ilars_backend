-- Полная схема с отдельными колонками для каждого поля
-- Все данные в отдельных колонках, не в JSONB

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Таблица пациентов
CREATE TABLE patients (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_code TEXT NOT NULL UNIQUE CHECK (length(patient_code) BETWEEN 4 AND 64),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Таблица истории статусов пациентов
CREATE TABLE patient_status_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  previous_status TEXT,
  new_status TEXT NOT NULL,
  reason TEXT,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Weekly (LARS) опросник - все поля уже отдельные
CREATE TABLE weekly_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
  
  flatus_control SMALLINT NOT NULL CHECK (flatus_control BETWEEN 0 AND 2),
  liquid_stool_leakage SMALLINT NOT NULL CHECK (liquid_stool_leakage BETWEEN 0 AND 2),
  bowel_frequency SMALLINT NOT NULL CHECK (bowel_frequency BETWEEN 0 AND 3),
  repeat_bowel_opening SMALLINT NOT NULL CHECK (repeat_bowel_opening BETWEEN 0 AND 2),
  urgency_to_toilet SMALLINT NOT NULL CHECK (urgency_to_toilet BETWEEN 0 AND 2),
  total_score SMALLINT,
  
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (patient_id, entry_date)
);

-- Daily опросник - все поля отдельные
CREATE TABLE daily_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
  
  -- Основные поля
  bristol_scale SMALLINT CHECK (bristol_scale BETWEEN 1 AND 7),
  stool_count SMALLINT NOT NULL DEFAULT 0,
  pads_used SMALLINT NOT NULL DEFAULT 0,
  urgency TEXT NOT NULL DEFAULT 'No' CHECK (urgency IN ('Yes', 'No')),
  night_stools TEXT NOT NULL DEFAULT 'No' CHECK (night_stools IN ('Yes', 'No')),
  leakage TEXT NOT NULL DEFAULT 'None' CHECK (leakage IN ('None', 'Liquid', 'Solid')),
  incomplete_evacuation TEXT NOT NULL DEFAULT 'No' CHECK (incomplete_evacuation IN ('Yes', 'No')),
  bloating NUMERIC(5, 2) NOT NULL DEFAULT 0,
  impact_score NUMERIC(5, 2) NOT NULL DEFAULT 0,
  activity_interfere NUMERIC(5, 2) NOT NULL DEFAULT 0,
  
  -- Food consumption - отдельные колонки для каждого типа еды
  food_vegetables_all SMALLINT NOT NULL DEFAULT 0,
  food_root_vegetables SMALLINT NOT NULL DEFAULT 0,
  food_whole_grains SMALLINT NOT NULL DEFAULT 0,
  food_whole_grain_bread SMALLINT NOT NULL DEFAULT 0,
  food_nuts_and_seeds SMALLINT NOT NULL DEFAULT 0,
  food_legumes SMALLINT NOT NULL DEFAULT 0,
  food_fruits_with_skin SMALLINT NOT NULL DEFAULT 0,
  food_berries SMALLINT NOT NULL DEFAULT 0,
  food_soft_fruits_no_skin SMALLINT NOT NULL DEFAULT 0,
  food_muesli_and_bran SMALLINT NOT NULL DEFAULT 0,
  
  -- Drink consumption - отдельные колонки для каждого типа напитка
  drink_water SMALLINT NOT NULL DEFAULT 0,
  drink_coffee SMALLINT NOT NULL DEFAULT 0,
  drink_tea SMALLINT NOT NULL DEFAULT 0,
  drink_alcohol SMALLINT NOT NULL DEFAULT 0,
  drink_carbonated SMALLINT NOT NULL DEFAULT 0,
  drink_juices SMALLINT NOT NULL DEFAULT 0,
  drink_dairy SMALLINT NOT NULL DEFAULT 0,
  drink_energy SMALLINT NOT NULL DEFAULT 0,
  
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (patient_id, entry_date)
);

-- Monthly опросник - все поля отдельные
CREATE TABLE monthly_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
  
  qol_score SMALLINT,
  avoid_travel NUMERIC(3, 1) NOT NULL DEFAULT 1 CHECK (avoid_travel BETWEEN 1 AND 4),
  avoid_social NUMERIC(3, 1) NOT NULL DEFAULT 1 CHECK (avoid_social BETWEEN 1 AND 4),
  embarrassed NUMERIC(3, 1) NOT NULL DEFAULT 1 CHECK (embarrassed BETWEEN 1 AND 4),
  worry_notice NUMERIC(3, 1) NOT NULL DEFAULT 1 CHECK (worry_notice BETWEEN 1 AND 4),
  depressed NUMERIC(3, 1) NOT NULL DEFAULT 1 CHECK (depressed BETWEEN 1 AND 4),
  control NUMERIC(4, 1) NOT NULL DEFAULT 0 CHECK (control BETWEEN 0 AND 10),
  satisfaction NUMERIC(4, 1) NOT NULL DEFAULT 0 CHECK (satisfaction BETWEEN 0 AND 10),
  
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (patient_id, entry_date)
);

-- EQ-5D-5L опросник - все поля уже отдельные
CREATE TABLE eq5d5l_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
  
  mobility SMALLINT NOT NULL CHECK (mobility BETWEEN 0 AND 4),
  self_care SMALLINT NOT NULL CHECK (self_care BETWEEN 0 AND 4),
  usual_activities SMALLINT NOT NULL CHECK (usual_activities BETWEEN 0 AND 4),
  pain_discomfort SMALLINT NOT NULL CHECK (pain_discomfort BETWEEN 0 AND 4),
  anxiety_depression SMALLINT NOT NULL CHECK (anxiety_depression BETWEEN 0 AND 4),
  -- EQ-5D VAS today (0..100), optional
  health_vas SMALLINT CHECK (health_vas BETWEEN 0 AND 100),
  
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (patient_id, entry_date)
);

-- Индексы
CREATE INDEX idx_patients_code ON patients (patient_code);
CREATE INDEX idx_patient_status_history_pid ON patient_status_history (patient_id, changed_at DESC);
CREATE INDEX idx_weekly_patient_date ON weekly_entries (patient_id, entry_date DESC);
CREATE INDEX idx_daily_patient_date ON daily_entries (patient_id, entry_date DESC);
CREATE INDEX idx_monthly_patient_date ON monthly_entries (patient_id, entry_date DESC);
CREATE INDEX idx_eq5d5l_patient_date ON eq5d5l_entries (patient_id, entry_date DESC);
