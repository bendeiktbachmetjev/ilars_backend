"""
Daily step count endpoints.
Patient sends steps via POST /sendSteps (X-Patient-Code header).
Doctor retrieves steps via getPatientDetail (included in patients.py response).

Storage: one row per patient in patient_steps table,
steps stored as JSONB {"2025-01-15": 5000, "2025-01-16": 7200, ...}
"""
import json
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
    Merges into the JSONB column: {"YYYY-MM-DD": step_count, ...}
    """
    patient_code = validate_patient_code(x_patient_code)

    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    if not payload.steps:
        return {"status": "ok", "saved": 0}

    new_steps = {}
    for entry in payload.steps:
        new_steps[entry.step_date] = entry.step_count

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

                await execute_with_retry(
                    session,
                    text("""
                        INSERT INTO patient_steps (patient_id, steps, updated_at)
                        VALUES (:pid, :new_steps, NOW())
                        ON CONFLICT (patient_id) DO UPDATE
                        SET steps = patient_steps.steps || :new_steps,
                            updated_at = NOW()
                    """).bindparams(
                        pid=patient_id,
                        new_steps=json.dumps(new_steps),
                    ),
                )

                return {"status": "ok", "saved": len(new_steps)}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)},
        )
