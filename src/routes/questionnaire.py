"""
Questionnaire logic endpoints
"""
from uuid import UUID
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from datetime import date, timedelta
from sqlalchemy import text

from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry
from src.utils.validators import validate_patient_code
from src.database.rls_context import set_db_context

router = APIRouter()


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
    Determine which questionnaire should be filled today. 
    Rule 1: On Day 1 (0 total entries), patient is allowed to fill all 4 questionnaires in sequence.
    Rule 2: For established users, AT MOST ONE questionnaire is suggested per day.
    Rule 3: Daily questionnaires do NOT accumulate. If not used, they disappear.
    Rule 4: Cadence priority: EQ5D5L > Weekly > Monthly > Daily (Fallback).
    
    Returns questionnaire type: "daily", "weekly", "monthly", "eq5d5l", or null if all done.
    """
    patient_code = validate_patient_code(x_patient_code)

    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    try:
        async with session_maker() as session:
            today = date.today()

            # 1. Get all patient data and last completion dates in ONE query
            # We also get counts to check if they are a brand new user
            async with set_db_context(session, role='system'):
                patient_res = await execute_with_retry(
                    session,
                    text("""
                        SELECT 
                            p.id,
                            p.created_at::DATE as patient_created_date,
                            (SELECT MAX(entry_date) FROM weekly_entries WHERE patient_id = p.id) as last_weekly_date,
                            (SELECT MAX(entry_date) FROM monthly_entries WHERE patient_id = p.id) as last_monthly_date,
                            (SELECT MAX(entry_date) FROM eq5d5l_entries WHERE patient_id = p.id) as last_eq5d5l_date,
                            (SELECT MAX(entry_date) FROM daily_entries WHERE patient_id = p.id) as last_daily_date,
                            (SELECT COUNT(*) FROM weekly_entries WHERE patient_id = p.id) as count_weekly,
                            (SELECT COUNT(*) FROM monthly_entries WHERE patient_id = p.id) as count_monthly,
                            (SELECT COUNT(*) FROM eq5d5l_entries WHERE patient_id = p.id) as count_eq5d5l,
                            (SELECT COUNT(*) FROM daily_entries WHERE patient_id = p.id) as count_daily
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

            # Extract variables
            patient_id_raw = patient_row[0]
            patient_id = UUID(str(patient_id_raw)) if patient_id_raw else None
            patient_created_date = patient_row[1] if patient_row[
                1] is not None else None
            last_weekly_date = patient_row[2] if patient_row[
                2] is not None else None
            last_monthly_date = patient_row[3] if patient_row[
                3] is not None else None
            last_eq5d5l_date = patient_row[4] if patient_row[
                4] is not None else None
            last_daily_date = patient_row[5] if patient_row[
                5] is not None else None

            # Counts
            total_history_count = ((patient_row[6] or 0) +
                                   (patient_row[7] or 0) +
                                   (patient_row[8] or 0) +
                                   (patient_row[9] or 0))

            is_new_user = total_history_count < 4 and today == patient_created_date
            if total_history_count == 0:
                is_new_user = True

            # Helper: identify which type was filled today, if any.
            # EQ-5D-5L > weekly > monthly > daily mirrors the cadence priority
            # used when scheduling the next questionnaire.
            def _today_filled_type():
                if last_eq5d5l_date == today:
                    return "eq5d5l"
                if last_weekly_date == today:
                    return "weekly"
                if last_monthly_date == today:
                    return "monthly"
                if last_daily_date == today:
                    return "daily"
                return None

            # 2. Global "Filled Today" Check (Unless New User)
            if not is_new_user:
                filled_today = _today_filled_type()
                if filled_today is not None:
                    # They already filled SOMETHING today. Block the rest but
                    # tell the client which one, so it can offer "edit today".
                    return {
                        "status": "ok",
                        "questionnaire_type": None,
                        "is_today_filled": True,
                        "today_filled_type": filled_today,
                        "reason": "You have already completed a questionnaire today.",
                    }

            type_priority = {"eq5d5l": 0, "monthly": 1, "weekly": 2}
            candidates = []

            # EQ-5D-5L logic (milestones)
            if patient_created_date and patient_id:
                days_since_start = (today - patient_created_date).days
                if days_since_start == 0 and patient_row[8] == 0:
                    candidates.append(
                        (today, type_priority["eq5d5l"], "eq5d5l",
                         "First EQ-5D-5L questionnaire"))
                else:
                    eq5d5l_milestones = [14, 30, 90, 180, 365]
                    milestones_to_check = []
                    for milestone_days in eq5d5l_milestones:
                        milestone_date = patient_created_date + timedelta(
                            days=milestone_days)
                        window_start = milestone_date - timedelta(days=3)
                        window_end = milestone_date + timedelta(days=7)
                        if today >= window_start and days_since_start >= milestone_days - 3:
                            milestones_to_check.append(
                                (milestone_days, milestone_date, window_start,
                                 window_end))

                    if milestones_to_check:
                        min_date = min(m[2] for m in milestones_to_check)
                        max_date = max(m[3] for m in milestones_to_check)
                        async with set_db_context(session, role='system'):
                            check_res = await execute_with_retry(
                                session,
                                text("""
                                    SELECT entry_date FROM eq5d5l_entries
                                    WHERE patient_id = :patient_id AND entry_date >= :min_date AND entry_date <= :max_date
                                """).bindparams(patient_id=patient_id,
                                                min_date=min_date,
                                                max_date=max_date))
                        filled_dates = set()
                        if check_res:
                            filled_dates = {
                                row[0]
                                for row in check_res.fetchall()
                            }
                        for milestone_days, milestone_date, window_start, window_end in milestones_to_check:
                            if any(window_start <= d <= window_end
                                   for d in filled_dates):
                                continue
                            candidates.append(
                                (milestone_date, type_priority["eq5d5l"],
                                 "eq5d5l",
                                 f"EQ-5D-5L milestone at {milestone_days} days"
                                 ))
                            break

            # Monthly logic
            if not last_monthly_date:
                candidates.append(
                    (patient_created_date or today, type_priority["monthly"],
                     "monthly", "First monthly questionnaire"))
            else:
                monthly_due_date = last_monthly_date + timedelta(days=28)
                if today >= monthly_due_date:
                    candidates.append(
                        (monthly_due_date, type_priority["monthly"], "monthly",
                         "Monthly questionnaire due"))

            # Weekly logic
            if not last_weekly_date:
                candidates.append(
                    (patient_created_date or today, type_priority["weekly"],
                     "weekly", "First weekly questionnaire (LARS)"))
            else:
                weekly_due_date = last_weekly_date + timedelta(days=7)
                if today >= weekly_due_date:
                    candidates.append(
                        (weekly_due_date, type_priority["weekly"], "weekly",
                         "Weekly questionnaire due"))

            # Select Questionnaire
            if candidates:
                # Sort primarily by oldest due_date, then by priority (eq5d5l > monthly > weekly)
                candidates.sort(key=lambda x: (x[0], x[1]))
                questionnaire_type = candidates[0][2]
                reason = candidates[0][3]
            else:
                # Fallback: No cadenced questionnaires are due. Serve the daily.
                # Since we already checked the "Filled Today" lock, this is guaranteed safe limit to 1.

                # EXCEPT: We must check if they filled a Daily today specifically for new users bypassing the global lock.
                if is_new_user and last_daily_date == today:
                    return {
                        "status": "ok",
                        "questionnaire_type": None,
                        "is_today_filled": True,
                        "today_filled_type": _today_filled_type(),
                        "reason": "All set! You have completed all initial questionnaires.",
                    }

                questionnaire_type = "daily"
                reason = ("First daily questionnaire" if not last_daily_date
                          else "Daily questionnaire available")

            return {
                "status": "ok",
                "questionnaire_type": questionnaire_type,
                "is_today_filled": False,
                "today_filled_type": _today_filled_type(),
                "reason": reason,
            }

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
