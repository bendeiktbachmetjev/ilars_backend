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
    hospital_id: Optional[str] = None
    date_of_birth: Optional[str] = None  # YYYY-MM-DD


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Extract and verify Firebase ID token, return decoded claims (uid, email, etc.)"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization[7:].strip()
    decoded = verify_id_token(token)
    if not decoded:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
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
                return {"status": "ok", "profile": None, "needs_profile": True}

            hospital_id = str(row[5]) if row[5] else None
            dob = row[6].isoformat() if row[6] else None

            return {
                "status": "ok",
                "profile": {
                    "id": str(row[0]),
                    "firebase_uid": row[1],
                    "email": row[2],
                    "first_name": row[3],
                    "last_name": row[4],
                    "hospital_id": hospital_id,
                    "hospital_name": row[9],
                    "date_of_birth": dob,
                    "created_at": row[7].isoformat() if row[7] else None,
                    "updated_at": row[8].isoformat() if row[8] else None,
                },
                "needs_profile": False,
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
            check = await execute_with_retry(
                session,
                text("SELECT id, email FROM doctors WHERE firebase_uid = :uid").bindparams(uid=uid)
            )
            if check is None:
                return JSONResponse(status_code=503, content={"status": "error", "detail": "Database unavailable"})

            existing = check.first()

            if existing:
                await execute_with_retry(
                    session,
                    text("""
                        UPDATE doctors SET
                            first_name = COALESCE(:fn, first_name),
                            last_name = COALESCE(:ln, last_name),
                            hospital_id = CASE WHEN :hid IS NOT NULL AND :hid != '' THEN :hid::uuid ELSE hospital_id END,
                            date_of_birth = COALESCE(:dob, date_of_birth),
                            updated_at = now()
                        WHERE firebase_uid = :uid
                    """).bindparams(
                        fn=body.first_name or None,
                        ln=body.last_name or None,
                        hid=body.hospital_id or None,
                        dob=dob,
                        uid=uid,
                    )
                )
                await session.commit()
            else:
                if not email:
                    raise HTTPException(status_code=400, detail="Email is required for new doctor registration")
                await execute_with_retry(
                    session,
                    text("""
                        INSERT INTO doctors (firebase_uid, email, first_name, last_name, hospital_id, date_of_birth)
                        VALUES (:uid, :email, :fn, :ln,
                                CASE WHEN :hid IS NOT NULL AND :hid != '' THEN :hid::uuid ELSE NULL END,
                                :dob)
                    """).bindparams(
                        uid=uid,
                        email=email,
                        fn=body.first_name or None,
                        ln=body.last_name or None,
                        hid=body.hospital_id or None,
                        dob=dob,
                    )
                )
                await session.commit()

            return {"status": "ok", "detail": "Profile saved"}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})
