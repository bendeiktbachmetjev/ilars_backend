## Backend schema and migrations

This folder contains SQL schema for the core relational storage in Postgres (compatible with Supabase/Neon/RDS etc.).

### Prerequisites
- A Postgres 13+ database
- `pgcrypto` extension enabled (the script enables it if possible)

### Apply schema
```
psql "$DATABASE_URL" -f schema.sql
```

`$DATABASE_URL` example:
```
postgres://USER:PASSWORD@HOST:PORT/DBNAME
```

### Tables overview
- `patients`: patient registry keyed by `patient_code` (no PII)
- `weekly_entries`: LARS weekly questionnaire; raw selections and a computed `total_score`
- `daily_entries`: daily metrics; structured columns + flexible JSONB payloads
- `monthly_entries`: monthly QoL or similar; optional scores + JSONB payloads

### Questionnaire schedule
Which questionnaire a patient gets each day (one per day, priorities, EQ-5D-5L time points, edge cases): see [docs/questionnaire-schedule.md](docs/questionnaire-schedule.md).

### Analytics guidance
- Use `idx_*_patient_date` for per-patient time series queries
- Use JSONB GIN indexes for ad-hoc filtering and future fields
- Consider materialized views for dashboard summaries later

### Security notes
- Store only pseudonymous `patient_code`
- Add row-level security and API roles in the app backend (not covered here)

### SSL certificate for Supabase (local dev)
- In Supabase: Settings → Database → SSL Configuration → Download certificate.
- Save as `backend/certs/supabase-ca.pem` or anywhere and set env var `SUPABASE_CA_PATH` to the file path.
- The backend uses this CA to verify TLS when connecting via asyncpg.


