"""
Daily step count endpoints.
Patient sends steps via POST /sendSteps (X-Patient-Code header).
Doctor retrieves steps via getPatientDetail (included in patients.py response).
"""
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional, List
from pydantic import BaseModel
from sqlalchemy import text

from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry
from src.utils.validators import validate_patient_code
from src.services.patient_service import PatientService

router = APIRouter()


class StepEntry(BaseModel):
    step_date: str
    step_count: int
    source: Optional[str] = "unknown"


class StepsPayload(BaseModel):
    steps: List[StepEntry]


@router.post("/sendSteps")
async def send_steps(
    payload: StepsPayload,
    x_patient_code: Optional[str] = Header(None),
):
    """
    Save daily step counts for a patient.
    Accepts a batch of {step_date, step_count, source} entries.
    Uses upsert — last write wins for the same (patient, date).
    """
    patient_code = validate_patient_code(x_patient_code)

    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    if not payload.steps:
        return {"status": "ok", "saved": 0}

    try:
        async with session_maker() as session:
            async with session.begin():
                patient_id = await PatientService.get_or_create_patient(
                    session, patient_code
                )
                if not patient_id:
                    raise HTTPException(
                        status_code=500, detail="Failed to resolve patient"
                    )

                saved = 0
                for entry in payload.steps:
                    await execute_with_retry(
                        session,
                        text("""
                            INSERT INTO daily_steps (patient_id, step_date, step_count, source)
                            VALUES (:pid, :d, :c, :s)
                            ON CONFLICT (patient_id, step_date) DO UPDATE
                            SET step_count = EXCLUDED.step_count,
                                source     = EXCLUDED.source,
                                updated_at = NOW()
                        """).bindparams(
                            pid=patient_id,
                            d=entry.step_date,
                            c=entry.step_count,
                            s=entry.source or "unknown",
                        ),
                    )
                    saved += 1

                return {"status": "ok", "saved": saved}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)},
        )
