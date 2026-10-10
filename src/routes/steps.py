"""
Daily step count endpoints.
Patient sends steps via POST /sendSteps (X-Patient-Code header).
Patient queries sync start date via GET /getStepsSyncInfo.
Doctor retrieves steps via getPatientDetail (included in patients.py response).

Storage: one row per patient per day in daily_steps table.
"""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional, List
from pydantic import BaseModel
from sqlalchemy import text, bindparam, Date, Integer
from sqlalchemy.dialects.postgresql import UUID

from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry
from src.utils.validators import validate_patient_code, validate_period, parse_iso_date, utc_today
from src.services.patient_service import PatientService
from src.database.rls_context import set_db_context
from src.limits import patient_rate_limit

router = APIRouter(dependencies=[Depends(patient_rate_limit)])

# A first sync starts on the patient's start date (getStepsSyncInfo) and can
# carry ~550 days, so the number of rows is not capped - the dates are: from 30
# days before the patient was created (slack for clocks) to today, where a
# patient's today can be a day ahead of the server's UTC date.
STEPS_DAYS_BEFORE_CREATED = 30
MAX_STEPS_PER_DAY = 200_000


class StepEntry(BaseModel):
    step_date: str
    step_count: int


class StepsPayload(BaseModel):
    steps: List[StepEntry]


def steps_to_save(entries: List[StepEntry], created_on: date, today: date):
    """
    The entries to store - one per day, the last one sent wins - and how many
    were left out (a date outside the window, a count outside 0..200,000,
    or a repeated day).
    """
    first = created_on - timedelta(days=STEPS_DAYS_BEFORE_CREATED)
    last = today + timedelta(days=1)
    keep = {}
    for entry in entries:
        day = parse_iso_date(entry.step_date)
        if day is None or not first <= day <= last or not 0 <= entry.step_count <= MAX_STEPS_PER_DAY:
            continue
        keep[day] = entry.step_count
    return keep, len(entries) - len(keep)


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

            async with set_db_context(session, role='patient', user_id=patient_id):
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
                # Only codes a doctor created; an unknown one is never a new patient
                patient_id = await PatientService.get_patient_id(session, patient_code)
                if not patient_id:
                    print("🚦 [limit] /sendSteps: unknown patient code")
                    raise HTTPException(status_code=404, detail="Patient not found")

                saved = 0
                async with set_db_context(session, role='patient', user_id=patient_id):
                    created = await execute_with_retry(
                        session,
                        text("SELECT created_at::date FROM patients WHERE id = :pid").bindparams(
                            bindparam('pid', value=patient_id, type_=UUID),
                        ),
                    )
                    created_on = created.scalar() if created else None
                    if created_on is None:
                        raise HTTPException(status_code=503, detail="Database unavailable")
                    rows, skipped = steps_to_save(payload.steps, created_on, utc_today())
                    if skipped:
                        print(f"🚦 [limit] /sendSteps: skipped {skipped} of {len(payload.steps)} rows (dates outside {created_on - timedelta(days=STEPS_DAYS_BEFORE_CREATED)}..today, counts outside 0-{MAX_STEPS_PER_DAY}, or repeated days)")
                    for step_date, step_count in rows.items():
                        await execute_with_retry(
                            session,
                            text("""
                                INSERT INTO daily_steps (patient_id, step_date, step_count)
                                VALUES (:pid, :step_date, :step_count)
                                ON CONFLICT (patient_id, step_date)
                                DO UPDATE SET step_count = EXCLUDED.step_count
                            """).bindparams(
                                bindparam('pid', value=patient_id, type_=UUID),
                                bindparam('step_date', value=step_date, type_=Date),
                                bindparam('step_count', value=step_count, type_=Integer),
                            ),
                        )
                        saved += 1

                return {"status": "ok", "saved": saved, "skipped": skipped}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)},
        )


@router.get("/getStepsChartData")
async def get_steps_chart_data(
    period: str,
    x_patient_code: Optional[str] = Header(None),
):
    """
    Get historical steps data for charts within a fixed time window.
    Returns raw daily step counts (no aggregation) ordered chronologically:
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

    try:
        async with session_maker() as session:
            patient_id = await PatientService.get_patient_id(session, patient_code)
            if not patient_id:
                return {"status": "ok", "data": []}

            # Keep windows in sync with getLarsData so both series live on
            # the exact same X range.
            window_days = {
                "weekly": 7,
                "monthly": 30,
                "3months": 90,
                "6months": 180,
                "yearly": 365,
            }[period]

            query = text(f"""
                SELECT step_date, step_count
                FROM daily_steps
                WHERE patient_id = :pid
                AND step_date >= CURRENT_DATE - INTERVAL '{window_days} days'
                ORDER BY step_date ASC
            """)

            async with set_db_context(session, role='patient', user_id=patient_id):
                result = await execute_with_retry(
                    session,
                    query.bindparams(bindparam('pid', value=patient_id, type_=UUID))
                )

            data = []
            if result:
                for row in result.fetchall():
                    data.append({
                        "date": row[0].isoformat() if row[0] else None,
                        "steps": row[1] or 0
                    })

            return {"status": "ok", "data": data}
            
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)},
        )
