-- Insert hospitals (run in Supabase SQL Editor if dropdown is empty)
INSERT INTO hospitals (name) VALUES
  ('Vilnius University Hospital Santaros Klinikos'),
  ('Kaunas Clinics of Lithuanian University of Health Sciences'),
  ('Klaipeda University Hospital'),
  ('Siauliai Republican Hospital'),
  ('Panevezys County Hospital')
ON CONFLICT (name) DO NOTHING;
