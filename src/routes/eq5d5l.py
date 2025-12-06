"""
EQ-5D-5L questionnaire endpoints
"""
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from sqlalchemy import text

from src.models.schemas import Eq5d5lPayload
from src.database.connection import get_session, is_initialized
from src.utils.validators import validate_patient_code
from src.services.patient_service import PatientService

router = APIRouter()


@router.post("/sendEq5d5l")
async def send_eq5d5l(payload: Eq5d5lPayload, x_patient_code: Optional[str] = Header(None)):
    """Save EQ-5D-5L questionnaire entry"""
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
                
                # Extract health VAS from payload or raw_data
                health_vas = payload.health_vas
                if health_vas is None and payload.raw_data is not None:
                    hv = payload.raw_data.get("health_vas")
                    if isinstance(hv, (int, float)):
                        try:
                            health_vas = int(hv)
                        except Exception:
                            health_vas = None
                
                # Save EQ-5D-5L entry
                result = await session.execute(
                    text("""
                        INSERT INTO eq5d5l_entries (
                            patient_id, entry_date,
                            mobility, self_care, usual_activities,
                            pain_discomfort, anxiety_depression, health_vas
                        ) VALUES (
                            :patient_id,
                            COALESCE(CAST(:entry_date AS DATE), CURRENT_DATE),
                            :mobility, :self_care, :usual_activities,
                            :pain_discomfort, :anxiety_depression, :health_vas
                        )
                        ON CONFLICT (patient_id, entry_date) DO UPDATE SET
                            mobility = EXCLUDED.mobility,
                            self_care = EXCLUDED.self_care,
                            usual_activities = EXCLUDED.usual_activities,
                            pain_discomfort = EXCLUDED.pain_discomfort,
                            anxiety_depression = EXCLUDED.anxiety_depression,
                            health_vas = EXCLUDED.health_vas
                        RETURNING id
                    """).bindparams(
                        patient_id=patient_id,
                        entry_date=payload.entry_date,
                        mobility=payload.mobility,
                        self_care=payload.self_care,
                        usual_activities=payload.usual_activities,
                        pain_discomfort=payload.pain_discomfort,
                        anxiety_depression=payload.anxiety_depression,
                        health_vas=health_vas,
                    )
                )
                row = result.first()
        return {"status": "ok", "id": str(row[0])}
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in sendEq5d5l: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )

