"""
Daily step count endpoints.
Patient sends steps via POST /sendSteps (X-Patient-Code header).
Patient queries sync start date via GET /getStepsSyncInfo.
Doctor retrieves steps via getPatientDetail (included in patients.py response).

Storage: one row per patient per day in daily_steps table.
"""
from datetime import date, timedelta
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional, List
from pydantic import BaseModel
from sqlalchemy import text, bindparam, Date, Integer
from sqlalchemy.dialects.postgresql import UUID

from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry
from src.utils.validators import validate_patient_code
from src.services.patient_service import PatientService

router = APIRouter()


class StepEntry(BaseModel):
    step_date: str
    step_count: int


class StepsPayload(BaseModel):
    steps: List[StepEntry]


@router.get("/getStepsSyncInfo")
async def get_steps_sync_info(
    x_patient_code: Optional[str] = Header(None),
):
    """
    Returns the date from which the client should start syncing steps.
    - If steps already exist: MAX(step_date) + 1 day
    - If no steps yet: patient created_at date
    """
    patient_code = validate_patient_code(x_patient_code)

    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    try:
        async with session_maker() as session:
            patient_id = await PatientService.get_patient_id(session, patient_code)
            if not patient_id:
                raise HTTPException(status_code=404, detail="Patient not found")

            result = await execute_with_retry(
                session,
                text("""
                    SELECT
                        (SELECT MAX(step_date) FROM daily_steps WHERE patient_id = :pid),
                        (SELECT created_at::date FROM patients WHERE id = :pid)
                """).bindparams(
                    bindparam('pid', value=patient_id, type_=UUID),
                ),
            )

            row = result.first() if result else None
            last_step_date = row[0] if row and row[0] else None
            created_at = row[1] if row and row[1] else None

            if last_step_date:
                start_date = last_step_date + timedelta(days=1)
            elif created_at:
                start_date = created_at
            else:
                start_date = date.today() - timedelta(days=30)

            return {
                "status": "ok",
                "start_date": start_date.isoformat(),
            }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)},
        )


@router.post("/sendSteps")
async def send_steps(
    payload: StepsPayload,
    x_patient_code: Optional[str] = Header(None),
):
    """
    Save daily step counts for a patient.
    Each entry becomes a separate row in daily_steps.
    ON CONFLICT updates the step_count for that day.
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
                            INSERT INTO daily_steps (patient_id, step_date, step_count)
                            VALUES (:pid, :step_date, :step_count)
                            ON CONFLICT (patient_id, step_date)
                            DO UPDATE SET step_count = EXCLUDED.step_count
                        """).bindparams(
                            bindparam('pid', value=patient_id, type_=UUID),
                            bindparam('step_date', value=date.fromisoformat(entry.step_date), type_=Date),
                            bindparam('step_count', value=entry.step_count, type_=Integer),
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
