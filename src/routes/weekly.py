"""
Weekly questionnaire endpoints
"""
from uuid import UUID
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from sqlalchemy import text

from src.models.schemas import WeeklyPayload
from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry
from src.utils.validators import validate_patient_code, validate_period
from src.services.patient_service import PatientService
from src.database.rls_context import set_db_context

router = APIRouter()


@router.post("/sendWeekly")
async def send_weekly(payload: WeeklyPayload, x_patient_code: Optional[str] = Header(None)):
    """Save weekly LARS questionnaire entry"""
    patient_code = validate_patient_code(x_patient_code)
    
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        async with session_maker() as session:
            async with session.begin():
                # Get or create patient
                patient_id_str = await PatientService.get_or_create_patient(session, patient_code)
                # Convert string to UUID for proper type handling
                patient_id = UUID(patient_id_str)
                
                # Calculate total_score from raw_data if available
                total_score = None
                if payload.raw_data and "total_score" in payload.raw_data:
                    total_score = payload.raw_data["total_score"]
                
                
                async with set_db_context(session, role='patient', user_id=patient_id_str):
                    # Save weekly entry
                    result = await session.execute(
                        text("""
                            INSERT INTO weekly_entries (
                                patient_id, entry_date,
                                flatus_control, liquid_stool_leakage, bowel_frequency,
                                repeat_bowel_opening, urgency_to_toilet, total_score
                            ) VALUES (
                                :patient_id,
                                COALESCE(CAST(:entry_date AS DATE), CURRENT_DATE),
                                :flatus_control, :liquid_stool_leakage, :bowel_frequency,
                                :repeat_bowel_opening, :urgency_to_toilet, :total_score
                            )
                            ON CONFLICT (patient_id, entry_date) DO UPDATE SET
                                flatus_control = EXCLUDED.flatus_control,
                                liquid_stool_leakage = EXCLUDED.liquid_stool_leakage,
                                bowel_frequency = EXCLUDED.bowel_frequency,
                                repeat_bowel_opening = EXCLUDED.repeat_bowel_opening,
                                urgency_to_toilet = EXCLUDED.urgency_to_toilet,
                                total_score = EXCLUDED.total_score
                            RETURNING id
                        """).bindparams(
                            patient_id=patient_id,
                            entry_date=payload.entry_date,
                            flatus_control=payload.flatus_control,
                            liquid_stool_leakage=payload.liquid_stool_leakage,
                            bowel_frequency=payload.bowel_frequency,
                            repeat_bowel_opening=payload.repeat_bowel_opening,
                            urgency_to_toilet=payload.urgency_to_toilet,
                            total_score=total_score,
                        )
                    )
                    row = result.first()
        return {"status": "ok", "id": str(row[0])}
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in sendWeekly: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


@router.get("/getLarsData")
async def get_lars_data(
    period: str,
    x_patient_code: Optional[str] = Header(None)
):
    """
    Get LARS score data for a patient within a fixed time window.
    Returns raw entries (no averaging) ordered chronologically:
      - weekly   -> last 7 days
      - monthly  -> last 30 days
      - 3months  -> last 90 days
      - 6months  -> last 180 days
      - yearly   -> last 365 days
    """
    patient_code = validate_patient_code(x_patient_code)
    period = validate_period(period)

    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    # Map period to a date window in days. Keep boundaries strict and equal
    # for steps and LARS so both series live on the exact same X range.
    window_days = {
        "weekly": 7,
        "monthly": 30,
        "3months": 90,
        "6months": 180,
        "yearly": 365,
    }[period]

    try:
        async with session_maker() as session:
            patient_id_str = await PatientService.get_patient_id(session, patient_code)
            if not patient_id_str:
                return JSONResponse(status_code=404, content={"status": "error", "detail": "Patient not found"})

            async with set_db_context(session, role='patient', user_id=patient_id_str):
                # Return individual entries, not aggregates, so the chart can show concrete values.
                query = text(f"""
                    SELECT we.entry_date, we.total_score
                    FROM weekly_entries we
                    INNER JOIN patients p ON p.id = we.patient_id
                    WHERE p.patient_code = :code
                      AND we.total_score IS NOT NULL
                      AND we.entry_date >= CURRENT_DATE - INTERVAL '{window_days} days'
                    ORDER BY we.entry_date ASC
                """)

                result = await execute_with_retry(session, query.bindparams(code=patient_code))
                if result is None:
                    return JSONResponse(
                        status_code=503,
                        content={"status": "error", "detail": "Database connection pool exhausted, please try again"}
                    )

                rows = result.fetchall()

            data = []
            for idx, row in enumerate(rows, start=1):
                data.append({
                    "index": idx,
                    "date": row[0].isoformat() if row[0] else None,
                    "score": int(row[1]) if row[1] is not None else None,
                })

            return {"status": "ok", "data": data}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getLarsData: {error_type}: {error_msg}")
        traceback.print_exc()
        
        # Return empty data instead of error for connection issues
        if ("MaxClientsInSessionMode" in error_msg or
            "max clients reached" in error_msg.lower() or
            "TimeoutError" in error_type or
            "timeout" in error_msg.lower() or
            "CancelledError" in error_type):
            print(f"Connection issue in getLarsData, returning empty data: {error_type}")
            return {"status": "ok", "data": []}
        
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )

