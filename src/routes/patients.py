"""
Patient endpoints for doctor interface
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry
from src.utils.validators import validate_patient_code
from src.routes.doctors import get_current_user

router = APIRouter()


@router.get("/getPatients")
async def get_patients(claims: dict = Depends(get_current_user)):
    """
    Get list of patients for the current doctor's hospital.
    Returns patient codes and basic info (no PII).
    Only shows patients from the doctor's hospital.
    """
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    # Get doctor's hospital_id
    uid = claims.get("uid") or claims.get("sub", "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    try:
        async with session_maker() as session:
            # Get doctor's id, hospital_id, and doctor_code
            doctor_result = await execute_with_retry(
                session,
                text("""
                    SELECT d.id, d.hospital_id, d.doctor_code, hc.code as hospital_code
                    FROM doctors d
                    LEFT JOIN hospital_codes hc ON d.hospital_id = hc.hospital_id AND hc.is_active = true
                    WHERE d.firebase_uid = :uid
                """).bindparams(uid=uid)
            )
            if doctor_result is None:
                raise HTTPException(status_code=503, detail="Database unavailable")
            
            doctor_row = doctor_result.first()
            if not doctor_row or not doctor_row[0]:
                # Doctor profile not found - return empty list
                return {"status": "ok", "patients": []}
            
            doctor_id = str(doctor_row[0])
            hospital_id = str(doctor_row[1]) if doctor_row[1] else None
            doctor_code = doctor_row[2] if len(doctor_row) > 2 else None
            hospital_code = doctor_row[3] if len(doctor_row) > 3 else None
            
            if not hospital_id or not doctor_code:
                # Doctor has no hospital or code assigned - return empty list
                return {"status": "ok", "patients": []}
            
            # Get patients with matching doctor_code and hospital_code
            # Filter by doctor_id (which corresponds to doctor_code) and hospital_id (which corresponds to hospital_code)
            result = await execute_with_retry(
                session,
                text("""
                    SELECT 
                        p.patient_code,
                        p.created_at,
                        p.doctor_id,
                        p.hospital_id,
                        d.doctor_code,
                        hc.code as hospital_code,
                        (SELECT COUNT(*) FROM weekly_entries WHERE patient_id = p.id) as weekly_count,
                        (SELECT COUNT(*) FROM daily_entries WHERE patient_id = p.id) as daily_count,
                        (SELECT COUNT(*) FROM monthly_entries WHERE patient_id = p.id) as monthly_count,
                        (SELECT total_score FROM weekly_entries WHERE patient_id = p.id AND total_score IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_lars_score,
                        (SELECT entry_date FROM weekly_entries WHERE patient_id = p.id AND total_score IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_lars_date,
                        (SELECT health_vas FROM eq5d5l_entries WHERE patient_id = p.id AND health_vas IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_eq5d5l_score,
                        (SELECT entry_date FROM eq5d5l_entries WHERE patient_id = p.id AND health_vas IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_eq5d5l_date
                    FROM patients p
                    LEFT JOIN doctors d ON p.doctor_id = d.id
                    LEFT JOIN hospital_codes hc ON p.hospital_id = hc.hospital_id AND hc.is_active = true
                    WHERE p.doctor_id = :doctor_id AND p.hospital_id = :hospital_id
                    ORDER BY p.created_at DESC
                """).bindparams(doctor_id=doctor_id, hospital_id=hospital_id)
            )
            
            if result is None:
                return JSONResponse(
                    status_code=503,
                    content={"status": "error", "detail": "Database connection pool exhausted, please try again"}
                )
            
            rows = result.fetchall()
            patients = []
            for row in rows:
                patients.append({
                    "patient_code": row[0],
                    "created_at": row[1].isoformat() if row[1] else None,
                    "doctor_code": row[4] if len(row) > 4 else None,
                    "hospital_code": row[5] if len(row) > 5 else None,
                    "weekly_count": row[6] or 0 if len(row) > 6 else 0,
                    "daily_count": row[7] or 0 if len(row) > 7 else 0,
                    "monthly_count": row[8] or 0 if len(row) > 8 else 0,
                    "last_lars_score": row[9] if len(row) > 9 and row[9] is not None else None,
                    "last_lars_date": row[10].isoformat() if len(row) > 10 and row[10] else None,
                    "last_eq5d5l_score": row[11] if len(row) > 11 and row[11] is not None else None,
                    "last_eq5d5l_date": row[12].isoformat() if len(row) > 12 and row[12] else None,
                })
            
            return {"status": "ok", "patients": patients}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getPatients: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


@router.get("/getPatientDetail")
async def get_patient_detail(
    patient_code: str = Query(..., description="Patient code"),
    claims: dict = Depends(get_current_user)
):
    """
    Get detailed patient data for charts and graphs.
    Returns LARS scores, EQ-5D-5L scores, daily entries with food/drink consumption.
    Only accessible if patient belongs to the doctor's hospital.
    """
    patient_code = validate_patient_code(patient_code)
    
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    # Get doctor's hospital_id
    uid = claims.get("uid") or claims.get("sub", "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    try:
        async with session_maker() as session:
            # Get doctor's hospital_id
            doctor_result = await execute_with_retry(
                session,
                text("SELECT hospital_id FROM doctors WHERE firebase_uid = :uid").bindparams(uid=uid)
            )
            if doctor_result is None:
                raise HTTPException(status_code=503, detail="Database unavailable")
            
            doctor_row = doctor_result.first()
            if not doctor_row or not doctor_row[0]:
                raise HTTPException(status_code=403, detail="Doctor has no hospital assigned")
            
            hospital_id = str(doctor_row[0])
            
            # Get patient_id and verify it belongs to the same hospital
            patient_res = await execute_with_retry(
                session,
                text("SELECT id, created_at, hospital_id FROM patients WHERE patient_code = :code").bindparams(code=patient_code)
            )
            if patient_res is None:
                return JSONResponse(
                    status_code=503,
                    content={"status": "error", "detail": "Database connection pool exhausted"}
                )
            
            patient_row = patient_res.first()
            if not patient_row:
                raise HTTPException(status_code=404, detail="Patient not found")
            
            patient_id = patient_row[0]
            created_at = patient_row[1]
            patient_hospital_id = str(patient_row[2]) if patient_row[2] else None
            
            # Verify patient belongs to the same hospital as doctor
            if patient_hospital_id != hospital_id:
                raise HTTPException(status_code=403, detail="Patient does not belong to your hospital")
            
            # Get LARS scores over time
            lars_res = await execute_with_retry(
                session,
                text("""
                    SELECT entry_date, total_score
                    FROM weekly_entries
                    WHERE patient_id = :pid AND total_score IS NOT NULL
                    ORDER BY entry_date ASC
                """).bindparams(pid=patient_id)
            )
            lars_data = []
            if lars_res:
                for row in lars_res.fetchall():
                    lars_data.append({
                        "date": row[0].isoformat() if row[0] else None,
                        "score": row[1]
                    })
            
            # Get EQ-5D-5L scores over time
            eq5d5l_res = await execute_with_retry(
                session,
                text("""
                    SELECT entry_date, health_vas
                    FROM eq5d5l_entries
                    WHERE patient_id = :pid AND health_vas IS NOT NULL
                    ORDER BY entry_date ASC
                """).bindparams(pid=patient_id)
            )
            eq5d5l_data = []
            if eq5d5l_res:
                for row in eq5d5l_res.fetchall():
                    eq5d5l_data.append({
                        "date": row[0].isoformat() if row[0] else None,
                        "score": row[1]
                    })
            
            # Get daily entries with food/drink consumption (last 30 days)
            daily_res = await execute_with_retry(
                session,
                text("""
                    SELECT 
                        entry_date,
                        food_vegetables_all, food_root_vegetables, food_whole_grains,
                        food_whole_grain_bread, food_nuts_and_seeds, food_legumes,
                        food_fruits_with_skin, food_berries, food_soft_fruits_no_skin, food_muesli_and_bran,
                        drink_water, drink_coffee, drink_tea, drink_alcohol,
                        drink_carbonated, drink_juices, drink_dairy, drink_energy,
                        bristol_scale, stool_count, bloating, impact_score
                    FROM daily_entries
                    WHERE patient_id = :pid
                        AND entry_date >= CURRENT_DATE - INTERVAL '30 days'
                    ORDER BY entry_date ASC
                """).bindparams(pid=patient_id)
            )
            daily_data = []
            if daily_res:
                for row in daily_res.fetchall():
                    daily_data.append({
                        "date": row[0].isoformat() if row[0] else None,
                        "food": {
                            "vegetables_all": row[1] or 0,
                            "root_vegetables": row[2] or 0,
                            "whole_grains": row[3] or 0,
                            "whole_grain_bread": row[4] or 0,
                            "nuts_and_seeds": row[5] or 0,
                            "legumes": row[6] or 0,
                            "fruits_with_skin": row[7] or 0,
                            "berries": row[8] or 0,
                            "soft_fruits_no_skin": row[9] or 0,
                            "muesli_and_bran": row[10] or 0,
                        },
                        "drink": {
                            "water": row[11] or 0,
                            "coffee": row[12] or 0,
                            "tea": row[13] or 0,
                            "alcohol": row[14] or 0,
                            "carbonated": row[15] or 0,
                            "juices": row[16] or 0,
                            "dairy": row[17] or 0,
                            "energy": row[18] or 0,
                        },
                        "bristol_scale": row[19],
                        "stool_count": row[20] or 0,
                        "bloating": float(row[21]) if row[21] else 0,
                        "impact_score": float(row[22]) if row[22] else 0,
                    })
            
            return {
                "status": "ok",
                "patient_code": patient_code,
                "created_at": created_at.isoformat() if created_at else None,
                "lars_scores": lars_data,
                "eq5d5l_scores": eq5d5l_data,
                "daily_entries": daily_data,
            }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getPatientDetail: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


@router.post("/createPatient")
async def create_patient(claims: dict = Depends(get_current_user)):
    """
    Create a new patient code for the current doctor's hospital.
    Returns the generated patient code that can be given to the patient.
    """
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    # Get doctor info
    uid = claims.get("uid") or claims.get("sub", "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    try:
        async with session_maker() as session:
            # Get doctor's hospital_code and doctor_code
            doctor_result = await execute_with_retry(
                session,
                text("""
                    SELECT d.id, d.hospital_id, d.doctor_code, hc.code as hospital_code
                    FROM doctors d
                    LEFT JOIN hospitals h ON d.hospital_id = h.id
                    LEFT JOIN hospital_codes hc ON h.id = hc.hospital_id AND hc.is_active = true
                    WHERE d.firebase_uid = :uid
                    LIMIT 1
                """).bindparams(uid=uid)
            )
            if doctor_result is None:
                raise HTTPException(status_code=503, detail="Database unavailable")
            
            doctor_row = doctor_result.first()
            if not doctor_row:
                raise HTTPException(status_code=404, detail="Doctor profile not found")
            
            doctor_id = str(doctor_row[0])
            hospital_id = str(doctor_row[1]) if doctor_row[1] else None
            doctor_code = doctor_row[2] if len(doctor_row) > 2 else None
            hospital_code = doctor_row[3] if len(doctor_row) > 3 else None
            
            if not hospital_id:
                raise HTTPException(status_code=400, detail="Doctor has no hospital assigned")
            
            if not doctor_code:
                raise HTTPException(status_code=400, detail="Doctor code not found")
            
            if not hospital_code:
                raise HTTPException(status_code=400, detail="Hospital code not found")
            
            # Generate completely random patient code (not based on hospital/doctor codes)
            code_result = await execute_with_retry(
                session,
                text("SELECT generate_patient_code()")
            )
            if not code_result:
                raise HTTPException(status_code=500, detail="Failed to generate patient code")
            
            patient_code = code_result.scalar()
            
            # Create patient with doctor_id and hospital_id
            patient_result = await execute_with_retry(
                session,
                text("""
                    INSERT INTO patients (patient_code, doctor_id, hospital_id)
                    VALUES (:code, CAST(:doctor_id AS uuid), CAST(:hospital_id AS uuid))
                    RETURNING id, created_at
                """).bindparams(
                    code=patient_code,
                    doctor_id=doctor_id,
                    hospital_id=hospital_id
                )
            )
            await session.commit()
            
            if not patient_result:
                raise HTTPException(status_code=500, detail="Failed to create patient")
            
            patient_row = patient_result.first()
            created_at = patient_row[1] if patient_row else None
            
            return {
                "status": "ok",
                "patient_code": patient_code,
                "created_at": created_at.isoformat() if created_at else None,
                "doctor_code": doctor_code,
                "hospital_code": hospital_code,
                "message": "Patient created successfully"
            }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in createPatient: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )

