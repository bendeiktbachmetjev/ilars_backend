-- Query to get all active hospital codes
-- Run this in your database to see codes for doctor registration

SELECT 
    h.id as hospital_id,
    h.name as hospital_name,
    hc.code as hospital_code,
    hc.created_at as code_created,
    hc.is_active
FROM hospitals h
INNER JOIN hospital_codes hc ON h.id = hc.hospital_id
WHERE hc.is_active = true
ORDER BY h.name;

-- Example output:
-- hospital_id | hospital_name                                    | hospital_code | code_created          | is_active
-- ------------|--------------------------------------------------|---------------|----------------------|----------
-- uuid-123    | Vilnius University Hospital Santaros Klinikos  | K7M9P2R4X8Y3  | 2025-02-11 10:00:00  | true
-- uuid-456    | Kaunas Clinics...                               | A2B4C6D8E0F2  | 2025-02-11 10:00:00  | true
