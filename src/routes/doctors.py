"""
Doctor profile endpoints - requires Firebase ID token
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry
from src.services.firebase_auth import verify_id_token

router = APIRouter()


class DoctorProfileUpdate(BaseModel):
    email: Optional[str] = None  # Required for create, from Google
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    hospital_code: Optional[str] = None  # Required - only way to assign hospital
    date_of_birth: Optional[str] = None  # YYYY-MM-DD


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Extract and verify Firebase ID token, return decoded claims (uid, email, etc.)"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    
    print(f"Verifying token (length: {len(token)})")
    decoded = verify_id_token(token)
    if not decoded:
        print("Token verification returned None")
        raise HTTPException(status_code=401, detail="Invalid token")
    
    print(f"Token verified successfully, uid: {decoded.get('uid', 'N/A')}")
    return decoded


@router.get("/doctors/me")
async def get_doctor_profile(claims: dict = Depends(get_current_user)):
    """
    Get current doctor profile by Firebase UID.
    Returns null profile fields if doctor has not completed profile yet.
    """
    uid = claims.get("uid", "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    try:
        async with session_maker() as session:
            result = await execute_with_retry(
                session,
                text("""
                    SELECT d.id, d.firebase_uid, d.email, d.first_name, d.last_name,
                           d.hospital_id, d.date_of_birth, d.created_at, d.updated_at,
                           d.doctor_code,
                           h.name as hospital_name
                    FROM doctors d
                    LEFT JOIN hospitals h ON d.hospital_id = h.id
                    WHERE d.firebase_uid = :uid
                """).bindparams(uid=uid)
            )
            if result is None:
                return JSONResponse(status_code=503, content={"status": "error", "detail": "Database unavailable"})

            row = result.first()
            if not row:
                # Auto-create profile on first access
                email = claims.get("email", "")
                if not email:
                    return {"status": "ok", "profile": None, "needs_profile": True}
                
                # Generate doctor code
                code_result = await execute_with_retry(
                    session,
                    text("SELECT generate_doctor_code()")
                )
                doctor_code = code_result.scalar() if code_result else None
                
                # Create profile without hospital
                await execute_with_retry(
                    session,
                    text("""
                        INSERT INTO doctors (firebase_uid, email, doctor_code)
                        VALUES (:uid, :email, :dcode)
                        RETURNING id, firebase_uid, email, first_name, last_name,
                                  hospital_id, date_of_birth, created_at, updated_at, doctor_code
                    """).bindparams(
                        uid=uid,
                        email=email,
                        dcode=doctor_code
                    )
                )
                await session.commit()
                
                # Fetch created profile
                result = await execute_with_retry(
                    session,
                    text("""
                        SELECT d.id, d.firebase_uid, d.email, d.first_name, d.last_name,
                               d.hospital_id, d.date_of_birth, d.created_at, d.updated_at,
                               d.doctor_code,
                               h.name as hospital_name
                        FROM doctors d
                        LEFT JOIN hospitals h ON d.hospital_id = h.id
                        WHERE d.firebase_uid = :uid
                    """).bindparams(uid=uid)
                )
                row = result.first() if result else None
                if not row:
                    return {"status": "ok", "profile": None, "needs_profile": True}

            hospital_id = str(row[5]) if row[5] else None
            dob = row[6].isoformat() if row[6] else None
            doctor_code = row[9] if len(row) > 9 and row[9] else None
            hospital_name = row[10] if len(row) > 10 and row[10] else None
            
            # Profile is complete only if hospital_id exists (doctor_code is auto-generated)
            needs_profile = not hospital_id

            return {
                "status": "ok",
                "profile": {
                    "id": str(row[0]),
                    "firebase_uid": row[1],
                    "email": row[2],
                    "first_name": row[3],
                    "last_name": row[4],
                    "hospital_id": hospital_id,
                    "hospital_name": hospital_name,
                    "doctor_code": doctor_code,
                    "date_of_birth": dob,
                    "created_at": row[7].isoformat() if row[7] else None,
                    "updated_at": row[8].isoformat() if row[8] else None,
                },
                "needs_profile": needs_profile,
            }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in get_doctor_profile: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@router.post("/doctors")
async def create_or_update_doctor_profile(
    body: DoctorProfileUpdate,
    claims: dict = Depends(get_current_user),
):
    """
    Create or update doctor profile.
    Requires: Authorization: Bearer <Firebase ID token>
    """
    uid = claims.get("uid", "")
    email = body.email or claims.get("email", "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    dob = None
    if body.date_of_birth:
        try:
            dob = date.fromisoformat(body.date_of_birth)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_of_birth format (use YYYY-MM-DD)")

    try:
        async with session_maker() as session:
            # Check if doctor profile exists
            check = await execute_with_retry(
                session,
                text("SELECT id, email, doctor_code, hospital_id FROM doctors WHERE firebase_uid = :uid").bindparams(uid=uid)
            )
            if check is None:
                return JSONResponse(status_code=503, content={"status": "error", "detail": "Database unavailable"})

            existing = check.first()
            doctor_exists = existing is not None
            
            # Hospital can only be assigned through code - no manual selection allowed
            hospital_id_final = None
            if body.hospital_code:
                # Resolve hospital_id from hospital_code (check active codes only)
                hospital_result = await execute_with_retry(
                    session,
                    text("""
                        SELECT h.id 
                        FROM hospitals h
                        INNER JOIN hospital_codes hc ON h.id = hc.hospital_id
                        WHERE hc.code = :code AND hc.is_active = true
                    """).bindparams(code=body.hospital_code.upper())
                )
                if hospital_result:
                    hospital_row = hospital_result.first()
                    if hospital_row:
                        hospital_id_final = str(hospital_row[0])
                    else:
                        raise HTTPException(status_code=404, detail="Hospital code not found or inactive")
                else:
                    raise HTTPException(status_code=404, detail="Hospital code not found or inactive")
            elif doctor_exists:
                # If updating existing doctor without hospital_code, keep existing hospital_id
                hospital_id_final = str(existing[3]) if existing[3] else None
            else:
                # New doctor must provide hospital_code (but this shouldn't happen as profile is auto-created)
                raise HTTPException(status_code=400, detail="Hospital code is required")

            doctor_code = None

            if existing:
                doctor_code = existing[2]  # Existing doctor_code
                
                # Generate doctor code if it doesn't exist
                if not doctor_code:
                    code_result = await execute_with_retry(
                        session,
                        text("SELECT generate_doctor_code()")
                    )
                    if code_result:
                        doctor_code = code_result.scalar()
                
                await execute_with_retry(
                    session,
                    text("""
                        UPDATE doctors SET
                            email = COALESCE(:email, email),
                            first_name = COALESCE(:fn, first_name),
                            last_name = COALESCE(:ln, last_name),
                            hospital_id = CASE WHEN :hid IS NOT NULL AND :hid != '' THEN :hid::uuid ELSE hospital_id END,
                            date_of_birth = COALESCE(:dob, date_of_birth),
                            doctor_code = COALESCE(:dcode, doctor_code),
                            updated_at = now()
                        WHERE firebase_uid = :uid
                    """).bindparams(
                        email=email,
                        fn=body.first_name or None,
                        ln=body.last_name or None,
                        hid=hospital_id_final or None,
                        dob=dob,
                        dcode=doctor_code,
                        uid=uid,
                    )
                )
                await session.commit()
            else:
                if not email:
                    raise HTTPException(status_code=400, detail="Email is required for new doctor registration")
                
                # Generate doctor code for new doctor
                code_result = await execute_with_retry(
                    session,
                    text("SELECT generate_doctor_code()")
                )
                if code_result:
                    doctor_code = code_result.scalar()
                
                await execute_with_retry(
                    session,
                    text("""
                        INSERT INTO doctors (firebase_uid, email, first_name, last_name, hospital_id, date_of_birth, doctor_code)
                        VALUES (:uid, :email, :fn, :ln,
                                CASE WHEN :hid IS NOT NULL AND :hid != '' THEN :hid::uuid ELSE NULL END,
                                :dob, :dcode)
                    """).bindparams(
                        uid=uid,
                        email=email,
                        fn=body.first_name or None,
                        ln=body.last_name or None,
                        hid=hospital_id_final or None,
                        dob=dob,
                        dcode=doctor_code,
                    )
                )
                await session.commit()

            return {"status": "ok", "detail": "Profile saved", "doctor_code": doctor_code}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})
