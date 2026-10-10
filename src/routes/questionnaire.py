"""
Questionnaire logic endpoints
"""
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from sqlalchemy import text

from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry
from src.utils.validators import validate_patient_code
from src.database.rls_context import set_db_context
from src.services.questionnaire_schedule import pick_questionnaire
from src.limits import patient_rate_limit

router = APIRouter(dependencies=[Depends(patient_rate_limit)])


# Supported questionnaire types for GET /getTodayEntry.
# Maps type -> (table, column list used to build the response dict).
# The column list intentionally uses raw DB names; the client knows how to
# map them back onto form fields (same names as in the POST raw_data).
_TODAY_ENTRY_TABLES = {
    "daily": (
        "daily_entries",
        [
            "bristol_scale", "stool_count", "pads_used", "urgency",
            "night_stools", "leakage", "incomplete_evacuation",
            "bloating", "impact_score", "activity_interfere",
            "food_vegetables_all", "food_root_vegetables", "food_whole_grains",
            "food_whole_grain_bread", "food_nuts_and_seeds", "food_legumes",
            "food_fruits_with_skin", "food_berries", "food_soft_fruits_no_skin",
            "food_muesli_and_bran",
            "drink_water", "drink_coffee", "drink_tea", "drink_alcohol",
            "drink_carbonated", "drink_juices", "drink_dairy", "drink_energy",
        ],
    ),
    "weekly": (
        "weekly_entries",
        [
            "flatus_control", "liquid_stool_leakage", "bowel_frequency",
            "repeat_bowel_opening", "urgency_to_toilet", "total_score",
        ],
    ),
    "monthly": (
        "monthly_entries",
        [
            "qol_score", "avoid_travel", "avoid_social", "embarrassed",
            "worry_notice", "depressed", "control", "satisfaction",
        ],
    ),
    "eq5d5l": (
        "eq5d5l_entries",
        [
            "mobility", "self_care", "usual_activities",
            "pain_discomfort", "anxiety_depression", "health_vas",
        ],
    ),
}


@router.get("/getTodayEntry")
async def get_today_entry(
    type: str,
    x_patient_code: Optional[str] = Header(None),
):
    """
    Return the patient's entry for today (if any) for the given questionnaire type.
    Used to pre-fill the form when the patient wants to edit an answer they
    already saved earlier the same day.
    Response: {status: "ok", data: {...fields...} | null}
    """
    patient_code = validate_patient_code(x_patient_code)

    if type not in _TODAY_ENTRY_TABLES:
        raise HTTPException(status_code=400, detail=f"Invalid questionnaire type: {type}")

    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    table, columns = _TODAY_ENTRY_TABLES[type]
    # Build the SELECT safely — table and column names come from a hard-coded map,
    # never from user input, so f-string interpolation is safe here.
    select_cols = ", ".join(columns)

    try:
        async with session_maker() as session:
            async with set_db_context(session, role='system'):
                res = await execute_with_retry(
                    session,
                    text(f"""
                        SELECT {select_cols}
                        FROM {table} e
                        INNER JOIN patients p ON p.id = e.patient_id
                        WHERE p.patient_code = :code
                          AND e.entry_date = CURRENT_DATE
                        LIMIT 1
                    """).bindparams(code=patient_code),
                )

            if res is None:
                return {"status": "ok", "data": None}

            row = res.first()
            if row is None:
                return {"status": "ok", "data": None}

            data = {col: row[i] for i, col in enumerate(columns)}
            return {"status": "ok", "data": data}

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = e.__class__.__name__
        print(f"Error in getTodayEntry: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type},
        )


@router.get("/getNextQuestionnaire")
async def get_next_questionnaire(x_patient_code: Optional[str] = Header(None)):
    """
    Determine which questionnaire should be filled today (at most one per day).
    Rules: src/services/questionnaire_schedule.py, described with examples in
    docs/questionnaire-schedule.md.

    Returns questionnaire type: "daily", "weekly", "monthly", "eq5d5l", or null
    if today's questionnaire is already done.
    """
    patient_code = validate_patient_code(x_patient_code)

    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    try:
        async with session_maker() as session:
            # "today" comes from the database clock: the same CURRENT_DATE that
            # dates saved answers in the send* endpoints, so both always agree.
            async with set_db_context(session, role='system'):
                patient_res = await execute_with_retry(
                    session,
                    text("""
                        SELECT
                            CURRENT_DATE AS today,
                            p.created_at::DATE AS start_date,
                            (SELECT MAX(entry_date) FROM daily_entries WHERE patient_id = p.id) AS last_daily,
                            (SELECT MAX(entry_date) FROM weekly_entries WHERE patient_id = p.id) AS last_weekly,
                            (SELECT MAX(entry_date) FROM monthly_entries WHERE patient_id = p.id) AS last_monthly,
                            (SELECT MAX(entry_date) FROM eq5d5l_entries WHERE patient_id = p.id) AS last_eq5d5l
                        FROM patients p
                        WHERE p.patient_code = :code
                    """).bindparams(code=patient_code))

            if patient_res is None:
                return {
                    "status":
                    "ok",
                    "questionnaire_type":
                    "daily",
                    "is_today_filled":
                    False,
                    "reason":
                    "Unable to determine questionnaire (database pool exhausted)"
                }

            patient_row = patient_res.first()

            # If patient doesn't exist, suggest first questionnaire (eq5d5l)
            if not patient_row:
                return {
                    "status":
                    "ok",
                    "questionnaire_type":
                    "eq5d5l",
                    "is_today_filled":
                    False,
                    "reason":
                    "Welcome! Please start with your first Quality of Life questionnaire (EQ-5D-5L)"
                }

            choice = pick_questionnaire(
                today=patient_row.today,
                start_date=patient_row.start_date,
                last_filled={
                    "daily": patient_row.last_daily,
                    "weekly": patient_row.last_weekly,
                    "monthly": patient_row.last_monthly,
                    "eq5d5l": patient_row.last_eq5d5l,
                },
            )
            return {"status": "ok", **choice}

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getNextQuestionnaire: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(status_code=500,
                            content={
                                "status": "error",
                                "detail": error_msg,
                                "error_type": error_type
                            })
