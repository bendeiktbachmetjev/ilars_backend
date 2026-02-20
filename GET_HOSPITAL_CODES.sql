-- Query to get all hospital codes
-- Run this in your database to see codes for doctor registration

SELECT 
    id as hospital_id,
    name as hospital_name,
    code as hospital_code,
    created_at
FROM hospitals
WHERE code IS NOT NULL
ORDER BY name;

-- Example output:
-- hospital_id | hospital_name                                    | hospital_code | created_at
-- ------------|--------------------------------------------------|---------------|----------------------
-- uuid-123    | Vilnius University Hospital Santaros Klinikos  | K7M9P2R4X8Y3  | 2025-02-11 10:00:00
-- uuid-456    | Kaunas Clinics...                               | A2B4C6D8E0F2  | 2025-02-11 10:00:00
