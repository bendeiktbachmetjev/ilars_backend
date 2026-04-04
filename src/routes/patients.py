"""
Patient endpoints for doctor interface
"""
from fastapi import APIRouter, HTTPException, Query, Depends, Body
from fastapi.responses import JSONResponse
from sqlalchemy import text
from pydantic import BaseModel

from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry
from src.utils.validators import validate_patient_code
from src.routes.doctors import get_current_user

router = APIRouter()

from fastapi import Header
from src.services.patient_service import PatientService
from src.database.rls_context import set_db_context

@router.get("/validatePatientCode")
async def validate_patient_code_endpoint(x_patient_code: str = Header(None, description="Patient Code")):
    """
    Validate if a patient code exists in the database.
    Used by frontend to check code validity before login/saving.
    """
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        valid_code = validate_patient_code(x_patient_code)
    except HTTPException:
        return JSONResponse(status_code=200, content={"status": "error", "detail": "Invalid patient code"})
        
    try:
        async with session_maker() as session:
            patient_id = await PatientService.get_patient_id(session, valid_code)
            if not patient_id:
                return JSONResponse(status_code=200, content={"status": "error", "detail": "Invalid patient code"})
            
            return {"status": "ok", "valid": True}
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"Error in validatePatientCode: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": "Internal server error"}
        )

class PatientProfileUpdate(BaseModel):
    email: str | None = None
    agreed_to_terms: bool
    agreed_to_promos: bool

@router.get("/getPatientProfile")
async def get_patient_profile(x_patient_code: str = Header(..., description="Patient Code")):
    """
    Get patient profile data including email and consents.
    """
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        valid_code = validate_patient_code(x_patient_code)
    except HTTPException:
        return JSONResponse(status_code=400, content={"status": "error", "detail": "Invalid patient code format"})
        
    try:
        async with session_maker() as session:
            # 1. Verify patient exists and get ID
            patient_id = await PatientService.get_patient_id(session, valid_code)
            if not patient_id:
                return JSONResponse(status_code=404, content={"status": "error", "detail": "Patient not found"})
                
            # 2. Get profile tracking row
            async with set_db_context(session, role='patient', user_id=patient_id):
                result = await execute_with_retry(
                    session,
                    text("SELECT email, agreed_to_terms, agreed_to_promos FROM patients WHERE id = CAST(:pid AS UUID)").bindparams(pid=patient_id)
                )
            
            row = result.first()
            if not row:
                return JSONResponse(status_code=404, content={"status": "error", "detail": "Profile not found"})
                
            return {
                "status": "ok",
                "email": row[0],
                "agreed_to_terms": row[1] if row[1] is not None else False,
                "agreed_to_promos": row[2] if row[2] is not None else False
            }
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"Error in getPatientProfile: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": "Internal server error"}
        )

@router.post("/unsubscribePatient")
async def unsubscribe_patient(x_patient_code: str = Header(..., description="Patient Code")):
    """
    Withdraw consent for promotional emails.
    """
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        valid_code = validate_patient_code(x_patient_code)
    except HTTPException:
        return JSONResponse(status_code=400, content={"status": "error", "detail": "Invalid patient code format"})
        
    try:
        async with session_maker() as session:
            patient_id = await PatientService.get_patient_id(session, valid_code)
            if not patient_id:
                return JSONResponse(status_code=404, content={"status": "error", "detail": "Patient not found"})
            
            async with set_db_context(session, role='patient', user_id=patient_id):
                await execute_with_retry(
                    session,
                    text("UPDATE patients SET agreed_to_promos = false, email = NULL WHERE id = CAST(:pid AS UUID)").bindparams(pid=patient_id)
                )
                await session.commit()
            
            return {"status": "ok"}
    except Exception as e:
        import traceback
        print(f"Error in unsubscribePatient: {str(e)}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": "Internal server error"}
        )

class PatientSubscribe(BaseModel):
    email: str

@router.post("/subscribePatient")
async def subscribe_patient(
    payload: PatientSubscribe,
    x_patient_code: str = Header(..., description="Patient Code")
):
    """
    Subscribe to promotional emails and optional provide a new email.
    """
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        valid_code = validate_patient_code(x_patient_code)
    except HTTPException:
        return JSONResponse(status_code=400, content={"status": "error", "detail": "Invalid patient code format"})
        
    try:
        async with session_maker() as session:
            patient_id = await PatientService.get_patient_id(session, valid_code)
            if not patient_id:
                return JSONResponse(status_code=404, content={"status": "error", "detail": "Patient not found"})
            
            async with set_db_context(session, role='patient', user_id=patient_id):
                await execute_with_retry(
                    session,
                    text("UPDATE patients SET agreed_to_promos = true, email = :email WHERE id = CAST(:pid AS UUID)").bindparams(
                        email=payload.email,
                        pid=patient_id
                    )
                )
                await session.commit()
            
            return {"status": "ok"}
    except Exception as e:
        import traceback
        print(f"Error in subscribePatient: {str(e)}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": "Internal server error"}
        )

@router.post("/updatePatientProfile")
async def update_patient_profile(
    payload: PatientProfileUpdate,
    x_patient_code: str = Header(..., description="Patient Code")
):
    """
    Update patient profile with email and consent flags.
    Used by frontend on initial login.
    """
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        valid_code = validate_patient_code(x_patient_code)
    except HTTPException:
        return JSONResponse(status_code=400, content={"status": "error", "detail": "Invalid patient code format"})
        
    try:
        async with session_maker() as session:
            # 1. Verify patient exists
            patient_id = await PatientService.get_patient_id(session, valid_code)
            if not patient_id:
                return JSONResponse(status_code=404, content={"status": "error", "detail": "Patient not found"})
            
            # 2. Update optional profile fields
            async with set_db_context(session, role='patient', user_id=patient_id):
                await execute_with_retry(
                    session,
                    text("""
                        UPDATE patients 
                        SET email = :email, 
                            agreed_to_terms = :terms, 
                            agreed_to_promos = :promos
                        WHERE id = CAST(:pid AS UUID)
                    """).bindparams(
                        email=payload.email,
                        terms=payload.agreed_to_terms,
                        promos=payload.agreed_to_promos,
                        pid=patient_id
                    )
                )
                await session.commit()
            
            return {"status": "ok"}
    except Exception as e:
        import traceback
        error_msg = str(e)
        print(f"Error in updatePatientProfile: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": "Internal server error"}
        )

@router.get("/getPatients")
async def get_patients(
    status: str = Query("active", description="active | inactive | all"),
    claims: dict = Depends(get_current_user)
):
    """
    Get list of patients for the current doctor's hospital.
    Returns patient codes and basic info (no PII).
    status=active (default): only active patients
    status=inactive: only inactive patients (archived)
    status=all: all patients with status field
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
            # Get doctor's hospital_id and doctor_id
            doctor_result = await execute_with_retry(
                session,
                text("SELECT id, hospital_id FROM doctors WHERE firebase_uid = :uid").bindparams(uid=uid)
            )
            if doctor_result is None:
                raise HTTPException(status_code=503, detail="Database unavailable")
            
            doctor_row = doctor_result.first()
            if not doctor_row or not doctor_row[1]:
                # Doctor has no hospital assigned - return empty list
                return {"status": "ok", "patients": []}
            
            doctor_id = str(doctor_row[0])
            hospital_id = str(doctor_row[1])

            # Debug logging to understand filtering issues
            print(f"[getPatients] uid={uid}, doctor_id={doctor_id}, hospital_id={hospital_id}")
            
            # Build status filter
            status_filter = ""
            if status == "active":
                status_filter = "AND p.status = 'active'"
            elif status == "inactive":
                status_filter = "AND p.status IN ('inactive', 'dead')"

            # Get patients from the same hospital with doctor and hospital codes + doctor name
            # Sort: first patients of current doctor, then other patients from same hospital
            async with set_db_context(session, role='doctor', doctor_id=doctor_id, hospital_id=hospital_id):
                result = await execute_with_retry(
                    session,
                    text(f"""
                        SELECT 
                            p.patient_code,
                            p.created_at,
                            p.doctor_id,
                            p.hospital_id,
                            p.status,
                            p.status_reason,
                            d.doctor_code,
                            h.code as hospital_code,
                            d.first_name,
                            d.last_name,
                            (SELECT COUNT(*) FROM weekly_entries WHERE patient_id = p.id) as weekly_count,
                            (SELECT COUNT(*) FROM daily_entries WHERE patient_id = p.id) as daily_count,
                            (SELECT COUNT(*) FROM monthly_entries WHERE patient_id = p.id) as monthly_count,
                            (SELECT total_score FROM weekly_entries WHERE patient_id = p.id AND total_score IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_lars_score,
                            (SELECT entry_date FROM weekly_entries WHERE patient_id = p.id AND total_score IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_lars_date,
                            (SELECT health_vas FROM eq5d5l_entries WHERE patient_id = p.id AND health_vas IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_eq5d5l_score,
                            (SELECT entry_date FROM eq5d5l_entries WHERE patient_id = p.id AND health_vas IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_eq5d5l_date
                        FROM patients p
                        LEFT JOIN doctors d ON p.doctor_id = d.id
                        LEFT JOIN hospitals h ON p.hospital_id = h.id
                        WHERE 
                            (p.doctor_id = CAST(:doctor_id AS uuid) OR p.hospital_id = CAST(:hospital_id AS uuid))
                            {status_filter}
                        ORDER BY 
                            CASE WHEN p.doctor_id = CAST(:doctor_id AS uuid) THEN 0 ELSE 1 END,
                            p.created_at DESC
                    """).bindparams(hospital_id=hospital_id, doctor_id=doctor_id)
                )
            
            if result is None:
                return JSONResponse(
                    status_code=503,
                    content={"status": "error", "detail": "Database connection pool exhausted, please try again"}
                )
            
            rows = result.fetchall()
            print(f"[getPatients] fetched_rows={len(rows)}")
            if rows:
                # Log first row's doctor/hospital linkage for debugging
                first = rows[0]
                try:
                    print(f"[getPatients] first_row: patient_code={first[0]}, doctor_id={first[2]}, hospital_id={first[3]}")
                except Exception as _e:
                    print(f"[getPatients] first_row debug failed: {type(_e).__name__}: {_e}")
            patients = []
            for row in rows:
                patients.append({
                    "patient_code": row[0],
                    "created_at": row[1].isoformat() if row[1] else None,
                    "status": row[4] if len(row) > 4 else "active",
                    "status_reason": row[5] if len(row) > 5 else None,
                    "doctor_code": row[6] if len(row) > 6 else None,
                    "hospital_code": row[7] if len(row) > 7 else None,
                    "doctor_first_name": row[8] if len(row) > 8 else None,
                    "doctor_last_name": row[9] if len(row) > 9 else None,
                    "weekly_count": row[10] or 0 if len(row) > 10 else 0,
                    "daily_count": row[11] or 0 if len(row) > 11 else 0,
                    "monthly_count": row[12] or 0 if len(row) > 12 else 0,
                    "last_lars_score": row[13] if len(row) > 13 and row[13] is not None else None,
                    "last_lars_date": row[14].isoformat() if len(row) > 14 and row[14] else None,
                    "last_eq5d5l_score": row[15] if len(row) > 15 and row[15] is not None else None,
                    "last_eq5d5l_date": row[16].isoformat() if len(row) > 16 and row[16] else None,
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
            async with set_db_context(session, role='doctor', hospital_id=hospital_id):
                patient_res = await execute_with_retry(
                    session,
                    text("SELECT id, created_at, hospital_id, status, status_reason FROM patients WHERE patient_code = :code").bindparams(code=patient_code)
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
            patient_status = patient_row[3] if len(patient_row) > 3 else "active"
            patient_status_reason = patient_row[4] if len(patient_row) > 4 else None
            
            # Verify patient belongs to the same hospital as doctor
            if patient_hospital_id != hospital_id:
                raise HTTPException(status_code=403, detail="Patient does not belong to your hospital")
            
            async with set_db_context(session, role='doctor', hospital_id=hospital_id):
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
            
            async with set_db_context(session, role='doctor', hospital_id=hospital_id):
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
            
            async with set_db_context(session, role='doctor', hospital_id=hospital_id):
                # Daily questionnaires for doctor charts
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
                            AND entry_date >= CURRENT_DATE - INTERVAL '730 days'
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
            
            async with set_db_context(session, role='doctor', hospital_id=hospital_id):
                # Get daily step counts (one row per day)
                steps_res = await execute_with_retry(
                    session,
                    text("""
                        SELECT step_date, step_count
                        FROM daily_steps
                        WHERE patient_id = :pid
                        ORDER BY step_date ASC
                    """).bindparams(pid=patient_id)
                )
            steps_data = []
            if steps_res:
                for row in steps_res.fetchall():
                    steps_data.append({
                        "date": row[0].isoformat() if row[0] else None,
                        "steps": row[1] or 0,
                    })

            return {
                "status": "ok",
                "patient_code": patient_code,
                "created_at": created_at.isoformat() if created_at else None,
                "patient_status": patient_status,
                "patient_status_reason": patient_status_reason,
                "lars_scores": lars_data,
                "eq5d5l_scores": eq5d5l_data,
                "daily_entries": daily_data,
                "daily_steps": steps_data,
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
                    SELECT d.id, d.hospital_id, d.doctor_code, h.code as hospital_code
                    FROM doctors d
                    LEFT JOIN hospitals h ON d.hospital_id = h.id
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
            
            async with set_db_context(session, role='doctor', doctor_id=doctor_id, hospital_id=hospital_id):
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


class UpdatePatientStatusBody(BaseModel):
    patient_code: str
    status: str  # 'active' | 'inactive' | 'dead'
    status_reason: str | None = None


@router.post("/updatePatientStatus")
async def update_patient_status(
    body: UpdatePatientStatusBody = Body(...),
    claims: dict = Depends(get_current_user)
):
    """
    Update patient status (active/inactive).
    Only doctor from same hospital can update.
    """
    patient_code = validate_patient_code(body.patient_code)
    if body.status not in ("active", "inactive", "dead"):
        raise HTTPException(status_code=400, detail="status must be 'active', 'inactive', or 'dead'")

    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    uid = claims.get("uid") or claims.get("sub", "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        async with session_maker() as session:
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

            async with set_db_context(session, role='doctor', hospital_id=hospital_id):
                patient_res = await execute_with_retry(
                    session,
                    text("SELECT id, hospital_id, status FROM patients WHERE patient_code = :code").bindparams(code=patient_code)
                )
            if patient_res is None:
                raise HTTPException(status_code=503, detail="Database unavailable")

            patient_row = patient_res.first()
            if not patient_row:
                raise HTTPException(status_code=404, detail="Patient not found")

            patient_id = patient_row[0]
            patient_hospital_id = str(patient_row[1]) if patient_row[1] else None
            patient_status = patient_row[2] if len(patient_row) > 2 else "active"

            if patient_hospital_id != hospital_id:
                raise HTTPException(status_code=403, detail="Patient does not belong to your hospital")

            if patient_status != body.status:
                async with set_db_context(session, role='doctor', hospital_id=hospital_id):
                    await execute_with_retry(
                        session,
                        text("""
                            INSERT INTO patient_status_history (patient_id, previous_status, new_status, reason)
                            VALUES (:patient_id, :prev_status, :new_status, :reason)
                        """).bindparams(
                            patient_id=patient_id,
                            prev_status=patient_status,
                            new_status=body.status,
                            reason=body.status_reason or None
                        )
                    )

            async with set_db_context(session, role='doctor', hospital_id=hospital_id):
                await execute_with_retry(
                    session,
                    text("""
                        UPDATE patients
                        SET status = :status, status_reason = :status_reason
                        WHERE patient_code = :code
                    """).bindparams(
                        code=patient_code,
                        status=body.status,
                        status_reason=body.status_reason or None
                    )
                )
                await session.commit()

            return {
                "status": "ok",
                "patient_code": patient_code,
                "patient_status": body.status,
                "message": "Patient status updated"
            }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in updatePatientStatus: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


@router.get("/getPatientStatusHistory")
async def get_patient_status_history(
    patient_code: str = Query(..., description="Patient code"),
    claims: dict = Depends(get_current_user)
):
    """
    Get history of patient status changes.
    Only doctor from same hospital can view.
    """
    patient_code = validate_patient_code(patient_code)

    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    uid = claims.get("uid") or claims.get("sub", "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        async with session_maker() as session:
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

            patient_res = await execute_with_retry(
                session,
                text("SELECT id, hospital_id FROM patients WHERE patient_code = :code").bindparams(code=patient_code)
            )
            if patient_res is None:
                raise HTTPException(status_code=503, detail="Database unavailable")

            patient_row = patient_res.first()
            if not patient_row:
                raise HTTPException(status_code=404, detail="Patient not found")

            patient_id = patient_row[0]
            patient_hospital_id = str(patient_row[1]) if patient_row[1] else None

            if patient_hospital_id != hospital_id:
                raise HTTPException(status_code=403, detail="Patient does not belong to your hospital")

            history_res = await execute_with_retry(
                session,
                text("""
                    SELECT id, previous_status, new_status, reason, changed_at
                    FROM patient_status_history
                    WHERE patient_id = :patient_id
                    ORDER BY changed_at DESC
                """).bindparams(patient_id=patient_id)
            )
            
            history_data = []
            if history_res:
                for row in history_res.fetchall():
                    history_data.append({
                        "id": str(row[0]),
                        "previous_status": row[1],
                        "new_status": row[2],
                        "reason": row[3],
                        "changed_at": row[4].isoformat() if row[4] else None
                    })

            return {
                "status": "ok",
                "patient_code": patient_code,
                "history": history_data
            }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getPatientStatusHistory: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


class DeletePatientStatusChangeBody(BaseModel):
    history_id: str


@router.post("/deletePatientStatusChange")
async def delete_patient_status_change(
    body: DeletePatientStatusChangeBody = Body(...),
    claims: dict = Depends(get_current_user)
):
    """
    Delete a specific patient status change history record.
    If it was the most recent change, the patient's status will revert to the previous_status of that record.
    Only doctor from same hospital can update.
    """
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    uid = claims.get("uid") or claims.get("sub", "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        async with session_maker() as session:
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

            # Find the history record and verify hospital ownership
            history_res = await execute_with_retry(
                session,
                text("""
                    SELECT h.id, h.patient_id, h.previous_status, h.changed_at, p.hospital_id, p.patient_code 
                    FROM patient_status_history h
                    JOIN patients p ON h.patient_id = p.id
                    WHERE h.id = CAST(:history_id AS uuid)
                """).bindparams(history_id=body.history_id)
            )
            if history_res is None:
                raise HTTPException(status_code=503, detail="Database unavailable")

            history_row = history_res.first()
            if not history_row:
                raise HTTPException(status_code=404, detail="Status change history not found")

            hist_id, patient_id, previous_status, changed_at, patient_hospital_id, patient_code = history_row

            if str(patient_hospital_id) != hospital_id:
                raise HTTPException(status_code=403, detail="Patient does not belong to your hospital")

            # Check if this is the most recent status change
            latest_res = await execute_with_retry(
                session,
                text("""
                    SELECT id FROM patient_status_history
                    WHERE patient_id = :patient_id
                    ORDER BY changed_at DESC
                    LIMIT 1
                """).bindparams(patient_id=patient_id)
            )
            
            latest_row = latest_res.first() if latest_res else None
            is_latest = latest_row is not None and str(latest_row[0]) == str(hist_id)

            # Revert the patient status if it's the latest
            if is_latest:
                await execute_with_retry(
                    session,
                    text("""
                        UPDATE patients
                        SET status = :previous_status
                        WHERE id = :patient_id
                    """).bindparams(
                        previous_status=previous_status,
                        patient_id=patient_id
                    )
                )

            # Delete the history record
            await execute_with_retry(
                session,
                text("""
                    DELETE FROM patient_status_history
                    WHERE id = CAST(:history_id AS uuid)
                """).bindparams(history_id=body.history_id)
            )
            
            await session.commit()

            return {
                "status": "ok",
                "message": "Status change deleted",
                "patient_code": patient_code,
                "reverted_to": previous_status if is_latest else None
            }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in deletePatientStatusChange: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )

