-- Таблица истории статусов пациентов
CREATE TABLE IF NOT EXISTS patient_status_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
  previous_status TEXT,
  new_status TEXT NOT NULL,
  reason TEXT,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Индекс для быстрого поиска истории по пациенту
CREATE INDEX IF NOT EXISTS idx_patient_status_history_pid ON patient_status_history (patient_id, changed_at DESC);
