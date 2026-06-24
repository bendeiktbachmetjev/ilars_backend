-- Migration: Lithuanian colorectal cancer registry
-- 1) Mark Lithuanian hospitals with an "LT" code prefix (used to detect Lithuanian doctors).
--    Doctors are linked to hospitals by hospital_id (UUID), so changing the code does NOT
--    break access for existing doctors; the code is only used at registration time.
-- 2) Create registry_patients table (PII/names stay in Firebase, not here).
-- 3) RLS: national read for any doctor, write only by the owning doctor.

-- ============================================================
-- 1. Lithuanian hospital codes -> LT prefix
-- ============================================================
UPDATE hospitals
SET code = 'LT' || code
WHERE code IN ('AT9FXVX9G8WZ','4FSJL5D7QB2Z','NVC01AYSIDM','K4PYGWZ49KGW','KFFSLDXDZUW3','GEPF3HQ296DJ')
  AND code NOT LIKE 'LT%';

-- ============================================================
-- 2. registry_patients table
-- ============================================================
CREATE TABLE IF NOT EXISTS registry_patients (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Identifiers / meta
  lin TEXT,                         -- LIN (pseudonimizuotas)
  personal_id_code TEXT,            -- Asmens ID kodas iš dokumento
  doctor_id UUID NOT NULL REFERENCES doctors(id),
  hospital_id UUID NOT NULL REFERENCES hospitals(id),
  study_patient_id UUID UNIQUE REFERENCES patients(id) ON DELETE SET NULL, -- 1:1 link to study
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- A. Demografija / bazė
  birth_date DATE,
  sex SMALLINT CHECK (sex IN (0,1)),
  diagnosis_date DATE,
  index_operation_date DATE,
  age_at_diagnosis SMALLINT CHECK (age_at_diagnosis BETWEEN 0 AND 130),
  height_cm SMALLINT CHECK (height_cm BETWEEN 0 AND 300),
  weight_kg NUMERIC(5,1) CHECK (weight_kg >= 0),
  bmi NUMERIC(4,1) CHECK (bmi >= 0),
  asa_score SMALLINT CHECK (asa_score BETWEEN 1 AND 5),
  ecog SMALLINT CHECK (ecog BETWEEN 0 AND 4),
  family_crc_history SMALLINT CHECK (family_crc_history IN (0,1)),
  diabetes SMALLINT CHECK (diabetes IN (0,1)),
  cardiovascular_disease SMALLINT CHECK (cardiovascular_disease IN (0,1)),
  glucocorticoid_use SMALLINT CHECK (glucocorticoid_use IN (0,1)),
  cea_pre_treatment NUMERIC(7,2) CHECK (cea_pre_treatment >= 0),
  prehabilitation SMALLINT CHECK (prehabilitation IN (0,1)),

  -- B. MRI / klinikinis stadijavimas
  mri_date DATE,
  ct TEXT CHECK (ct IN ('cT1','cT2','cT3','cT4a','cT4b')),
  cn TEXT CHECK (cn IN ('cN0','cN1','cN2')),
  cm TEXT CHECK (cm IN ('cM0','cM1')),
  clinical_stage TEXT CHECK (clinical_stage IN ('I','II','III','IV')),
  emvi SMALLINT CHECK (emvi IN (0,1)),
  mrf SMALLINT CHECK (mrf IN (0,1,2)),
  tumor_distance_anus_cm NUMERIC(4,1) CHECK (tumor_distance_anus_cm >= 0),
  tumor_distance_arj_cm NUMERIC(4,1) CHECK (tumor_distance_arj_cm >= 0),
  sphincter_invasion SMALLINT CHECK (sphincter_invasion IN (0,1)),
  circumferential SMALLINT CHECK (circumferential IN (0,1,2)),
  mesorectal_ln_mri SMALLINT CHECK (mesorectal_ln_mri IN (0,1)),

  -- C. Neoadjuvantinis gydymas
  nct SMALLINT CHECK (nct IN (0,1)),
  nct_start_date DATE,
  nct_end_date DATE,
  nct_scheme TEXT CHECK (nct_scheme IN ('CAPOX','FOLFOX','FOLFIRI','kita')),
  nct_cycles SMALLINT CHECK (nct_cycles >= 0),
  nrt_start_date DATE,
  nrt_end_date DATE,
  nrt_dose_gy NUMERIC(5,1) CHECK (nrt_dose_gy >= 0),
  new_mts_after_neoadj SMALLINT CHECK (new_mts_after_neoadj IN (0,1)),
  mrtrg SMALLINT CHECK (mrtrg BETWEEN 1 AND 5),

  -- D. Operacija
  operation_date DATE,
  operation_type TEXT CHECK (operation_type IN ('LAR','APR','Hartmann','TaTME','PME','kita')),
  operation_approach SMALLINT CHECK (operation_approach IN (1,2,3)),
  conversion SMALLINT CHECK (conversion IN (0,1)),
  operation_duration_min SMALLINT CHECK (operation_duration_min >= 0),
  blood_loss_ml SMALLINT CHECK (blood_loss_ml >= 0),
  tme_quality SMALLINT CHECK (tme_quality IN (1,2,3)),
  ileostomy SMALLINT CHECK (ileostomy IN (0,1)),
  anastomosis_type TEXT CHECK (anastomosis_type IN ('colorectal','coloanal','nėra')),
  ileostomy_closure_date DATE,
  complications SMALLINT CHECK (complications IN (0,1)),
  clavien_dindo TEXT CHECK (clavien_dindo IN ('0','I','II','IIIa','IIIb','IVa','IVb','V')),
  anastomotic_leak SMALLINT CHECK (anastomotic_leak IN (0,1)),
  reoperation_30d SMALLINT CHECK (reoperation_30d IN (0,1)),
  rehospitalization_30d SMALLINT CHECK (rehospitalization_30d IN (0,1)),
  hospital_stay_days SMALLINT CHECK (hospital_stay_days >= 0),
  death_30d SMALLINT CHECK (death_30d IN (0,1)),
  complications_icd10 TEXT,

  -- E. Patologija
  pt TEXT CHECK (pt IN ('pT0','pT1','pT2','pT3','pT4a','pT4b')),
  pn TEXT CHECK (pn IN ('pN0','pN1a','pN1b','pN1c','pN2a','pN2b')),
  pm TEXT CHECK (pm IN ('pM0','pM1a','pM1b','pM1c')),
  ptnm_stage TEXT CHECK (ptnm_stage IN ('0','I','IIA','IIB','IIC','IIIA','IIIB','IIIC','IVA','IVB','IVC')),
  histology_type TEXT CHECK (histology_type IN ('adenokarcinoma','mucinozinė','signetinis','kita')),
  histology_grade TEXT CHECK (histology_grade IN ('G1','G2','G3')),
  resection_margin TEXT CHECK (resection_margin IN ('R0','R1','R2')),
  proximal_margin_cm NUMERIC(4,1) CHECK (proximal_margin_cm >= 0),
  distal_margin_cm NUMERIC(4,1) CHECK (distal_margin_cm >= 0),
  ln_removed SMALLINT CHECK (ln_removed >= 0),
  ln_positive SMALLINT CHECK (ln_positive >= 0),
  lvi SMALLINT CHECK (lvi IN (0,1)),
  pni SMALLINT CHECK (pni IN (0,1)),
  dworak_trg SMALLINT CHECK (dworak_trg BETWEEN 1 AND 4),
  specimen_length_cm NUMERIC(4,1) CHECK (specimen_length_cm >= 0),
  cea_post_op NUMERIC(7,2) CHECK (cea_post_op >= 0),

  -- F. Molekulinė diagnostika
  kras_status TEXT CHECK (kras_status IN ('wt','mut','neatlikta')),
  kras_mutation TEXT,
  nras_status TEXT CHECK (nras_status IN ('wt','mut','neatlikta')),
  braf_status TEXT CHECK (braf_status IN ('wt','mut','neatlikta')),
  mmr_msi_status TEXT CHECK (mmr_msi_status IN ('pMMR/MSS','dMMR/MSI-H','neatlikta')),
  mlh1 TEXT CHECK (mlh1 IN ('išreikštas','prarastas','neatliktas')),
  msh2 TEXT CHECK (msh2 IN ('išreikštas','prarastas','neatliktas')),
  msh6 TEXT CHECK (msh6 IN ('išreikštas','prarastas','neatliktas')),
  pms2 TEXT CHECK (pms2 IN ('išreikštas','prarastas','neatliktas')),
  her2 TEXT CHECK (her2 IN ('neg','poz(2+)','poz(3+)','neatlikta')),

  -- G. Adjuvantinis gydymas
  act_scheme TEXT CHECK (act_scheme IN ('CAPOX','FOLFOX','FOLFIRI','nėra')),
  act_start_date DATE,
  act_end_date DATE,
  act_cycles SMALLINT CHECK (act_cycles >= 0),
  art SMALLINT CHECK (art IN (0,1)),
  art_dose_gy NUMERIC(5,1) CHECK (art_dose_gy >= 0),

  -- H. Stebėjimas / baigtys
  mts_development SMALLINT CHECK (mts_development IN (0,1)),
  mts_location TEXT,
  local_recurrence SMALLINT CHECK (local_recurrence IN (0,1)),
  recurrence_date DATE,
  last_contact_date DATE,
  vital_status SMALLINT CHECK (vital_status IN (0,1)),
  death_date DATE,
  cancer_related_death SMALLINT CHECK (cancer_related_death IN (0,1)),
  notes TEXT,

  -- I. PROMs (LARS / Wexner)
  lars_baseline SMALLINT CHECK (lars_baseline BETWEEN 0 AND 42),
  lars_0m SMALLINT CHECK (lars_0m BETWEEN 0 AND 42),
  lars_3m SMALLINT CHECK (lars_3m BETWEEN 0 AND 42),
  lars_6m SMALLINT CHECK (lars_6m BETWEEN 0 AND 42),
  lars_12m SMALLINT CHECK (lars_12m BETWEEN 0 AND 42),
  lars_category_12m SMALLINT CHECK (lars_category_12m IN (0,1,2)),
  wexner_0m SMALLINT CHECK (wexner_0m BETWEEN 0 AND 20),
  wexner_12m SMALLINT CHECK (wexner_12m BETWEEN 0 AND 20)
);

CREATE INDEX IF NOT EXISTS idx_registry_hospital ON registry_patients (hospital_id);
CREATE INDEX IF NOT EXISTS idx_registry_doctor ON registry_patients (doctor_id);
CREATE INDEX IF NOT EXISTS idx_registry_study_patient ON registry_patients (study_patient_id);

-- ============================================================
-- 3. Row Level Security
-- ============================================================
ALTER TABLE registry_patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE registry_patients FORCE ROW LEVEL SECURITY;

CREATE POLICY system_bypass_registry ON registry_patients FOR ALL
    USING (current_setting('app.current_role', true) = 'system');

-- National READ for any doctor (backend additionally restricts SELECT to LT hospitals)
CREATE POLICY registry_doctor_select ON registry_patients FOR SELECT
    USING (current_setting('app.current_role', true) = 'doctor');

-- WRITE only by the owning doctor
CREATE POLICY registry_doctor_insert ON registry_patients FOR INSERT
    WITH CHECK (
        current_setting('app.current_role', true) = 'doctor'
        AND doctor_id = NULLIF(current_setting('app.doctor_id', true), '')::uuid
    );

CREATE POLICY registry_doctor_update ON registry_patients FOR UPDATE
    USING (
        current_setting('app.current_role', true) = 'doctor'
        AND doctor_id = NULLIF(current_setting('app.doctor_id', true), '')::uuid
    )
    WITH CHECK (
        current_setting('app.current_role', true) = 'doctor'
        AND doctor_id = NULLIF(current_setting('app.doctor_id', true), '')::uuid
    );

CREATE POLICY registry_doctor_delete ON registry_patients FOR DELETE
    USING (
        current_setting('app.current_role', true) = 'doctor'
        AND doctor_id = NULLIF(current_setting('app.doctor_id', true), '')::uuid
    );
