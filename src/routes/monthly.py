"""
Monthly questionnaire endpoints
"""
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from sqlalchemy import text

from src.models.schemas import MonthlyPayload
from src.database.connection import get_session, is_initialized
from src.utils.validators import validate_patient_code
from src.services.patient_service import PatientService

router = APIRouter()


@router.post("/sendMonthly")
async def send_monthly(payload: MonthlyPayload, x_patient_code: Optional[str] = Header(None)):
    """Save monthly QoL questionnaire entry"""
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
                patient_id = await PatientService.get_or_create_patient(session, patient_code)
                
                # Parse raw_data
                raw = payload.raw_data or {}
                avoid_travel = raw.get("avoid_travel", 1.0)
                avoid_social = raw.get("avoid_social", 1.0)
                embarrassed = raw.get("embarrassed", 1.0)
                worry_notice = raw.get("worry_notice", 1.0)
                depressed = raw.get("depressed", 1.0)
                control = raw.get("control", 0.0)
                satisfaction = raw.get("satisfaction", 0.0)
                
                # Save monthly entry
                result = await session.execute(
                    text("""
                        INSERT INTO monthly_entries (
                            patient_id, entry_date, qol_score,
                            avoid_travel, avoid_social, embarrassed, worry_notice,
                            depressed, control, satisfaction
                        ) VALUES (
                            :patient_id,
                            COALESCE(CAST(:entry_date AS DATE), CURRENT_DATE),
                            :qol_score,
                            :avoid_travel, :avoid_social, :embarrassed, :worry_notice,
                            :depressed, :control, :satisfaction
                        )
                        ON CONFLICT (patient_id, entry_date) DO UPDATE SET
                            qol_score = EXCLUDED.qol_score,
                            avoid_travel = EXCLUDED.avoid_travel,
                            avoid_social = EXCLUDED.avoid_social,
                            embarrassed = EXCLUDED.embarrassed,
                            worry_notice = EXCLUDED.worry_notice,
                            depressed = EXCLUDED.depressed,
                            control = EXCLUDED.control,
                            satisfaction = EXCLUDED.satisfaction
                        RETURNING id
                    """).bindparams(
                        patient_id=patient_id,
                        entry_date=payload.entry_date,
                        qol_score=payload.qol_score,
                        avoid_travel=avoid_travel,
                        avoid_social=avoid_social,
                        embarrassed=embarrassed,
                        worry_notice=worry_notice,
                        depressed=depressed,
                        control=control,
                        satisfaction=satisfaction,
                    )
                )
                row = result.first()
        return {"status": "ok", "id": str(row[0])}
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in sendMonthly: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )

