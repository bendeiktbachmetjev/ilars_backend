"""
Hospitals endpoint - list of hospitals for doctor profile dropdown
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry

router = APIRouter()


@router.get("/hospitals/by-code/{code}")
async def get_hospital_by_code(code: str):
    """
    Get hospital by active code (for doctor registration).
    Only returns hospital if code is active.
    """
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    try:
        async with session_maker() as session:
            # Look up hospital via hospital_codes table
            result = await execute_with_retry(
                session,
                text("""
                    SELECT h.id, h.name, hc.code
                    FROM hospitals h
                    INNER JOIN hospital_codes hc ON h.id = hc.hospital_id
                    WHERE hc.code = :code AND hc.is_active = true
                """).bindparams(code=code.upper())
            )
            if result is None:
                return JSONResponse(
                    status_code=503,
                    content={"status": "error", "detail": "Database connection pool exhausted"}
                )
            row = result.first()
            if not row:
                return JSONResponse(
                    status_code=404,
                    content={"status": "error", "detail": "Hospital code not found or inactive"}
                )
            return {
                "status": "ok",
                "hospital": {
                    "id": str(row[0]),
                    "name": row[1]
                    # Don't return code in response for security
                }
            }
    except Exception as e:
        import traceback
        print(f"Error in get_hospital_by_code: {e}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)}
        )


@router.get("/hospitals")
async def get_hospitals():
    """
    Get list of all hospitals (for doctor profile dropdown).
    Hospitals are admin-managed; doctors can only select from this list.
    """
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    try:
        async with session_maker() as session:
            result = await execute_with_retry(
                session,
                text("SELECT id, name FROM hospitals ORDER BY name ASC")
            )
            if result is None:
                return JSONResponse(
                    status_code=503,
                    content={"status": "error", "detail": "Database connection pool exhausted"}
                )
            rows = result.fetchall()
            hospitals = [{"id": str(row[0]), "name": row[1]} for row in rows]
            return {"status": "ok", "hospitals": hospitals}
    except Exception as e:
        import traceback
        print(f"Error in get_hospitals: {e}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)}
        )
