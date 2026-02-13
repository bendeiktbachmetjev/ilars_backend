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

router = APIRouter()


@router.get("/getNextQuestionnaire")
async def get_next_questionnaire(x_patient_code: Optional[str] = Header(None)):
    """
    Determine which questionnaire should be filled today. At most ONE questionnaire is
    suggested per day. When several are overdue (e.g. user skipped a month), we pick
    the one that was due FIRST (earliest due date), so spacing stays logical: e.g.
    weekly that was due 4 weeks ago today, then tomorrow monthly, then next weekly in 7 days.

    Schedule rules:
    - EQ-5D-5L: at 2 weeks, 1 month, 3 months, 6 months, 12 months after registration
    - Weekly (LARS): every 7 days after last completion
    - Monthly: every 28 days after last completion
    - Daily: when no mandatory questionnaire is due

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
            
            # Get all patient data and last completion dates in ONE query
            patient_res = await execute_with_retry(
                session,
                text("""
                    SELECT 
                        p.id,
                        p.created_at::DATE as patient_created_date,
                        (SELECT MAX(entry_date) FROM weekly_entries WHERE patient_id = p.id) as last_weekly_date,
                        (SELECT MAX(entry_date) FROM monthly_entries WHERE patient_id = p.id) as last_monthly_date,
                        (SELECT MAX(entry_date) FROM eq5d5l_entries WHERE patient_id = p.id) as last_eq5d5l_date,
                        (SELECT MAX(entry_date) FROM daily_entries WHERE patient_id = p.id) as last_daily_date
                    FROM patients p
                    WHERE p.patient_code = :code
                """).bindparams(code=patient_code)
            )
            
            if patient_res is None:
                return {
                    "status": "ok",
                    "questionnaire_type": "daily",
                    "is_today_filled": False,
                    "reason": "Unable to determine questionnaire (database pool exhausted)"
                }
            
            patient_row = patient_res.first()
            
            # If patient doesn't exist, suggest first questionnaire (weekly)
            if not patient_row:
                return {
                    "status": "ok",
                    "questionnaire_type": "weekly",
                    "is_today_filled": False,
                    "reason": "Welcome! Please start with your first weekly questionnaire (LARS)"
                }
            
            # Ensure patient_id is UUID type for proper SQL handling
            patient_id_raw = patient_row[0]
            patient_id = UUID(str(patient_id_raw)) if patient_id_raw else None
            patient_created_date = patient_row[1] if patient_row[1] is not None else None
            last_weekly_date = patient_row[2] if patient_row[2] is not None else None
            last_monthly_date = patient_row[3] if patient_row[3] is not None else None
            last_eq5d5l_date = patient_row[4] if patient_row[4] is not None else None
            last_daily_date = patient_row[5] if patient_row[5] is not None else None
            
            # Build list of (questionnaire_type, due_date, reason) for each type that is due.
            # We return exactly ONE questionnaire per day: the one with the EARLIEST due date.
            # So if user skipped a month, they get the questionnaire that was due first, then
            # next day the next one — spacing is preserved (e.g. next weekly in 7 days after filling).
            type_priority = {"eq5d5l": 0, "weekly": 1, "monthly": 2, "daily": 3}  # tie-breaker
            candidates = []  # list of (due_date, priority, type, reason)

            # EQ-5D-5L: due at milestone dates (2w, 1m, 3m, 6m, 12m); window: milestone-3 .. milestone+7
            if patient_created_date and patient_id:
                days_since_start = (today - patient_created_date).days
                eq5d5l_milestones = [14, 30, 90, 180, 365]
                milestones_to_check = []
                for milestone_days in eq5d5l_milestones:
                    milestone_date = patient_created_date + timedelta(days=milestone_days)
                    window_start = milestone_date - timedelta(days=3)
                    window_end = milestone_date + timedelta(days=7)
                    if today >= window_start and days_since_start >= milestone_days - 3:
                        milestones_to_check.append((milestone_days, milestone_date, window_start, window_end))

                if milestones_to_check:
                    min_date = min(m[2] for m in milestones_to_check)
                    max_date = max(m[3] for m in milestones_to_check)
                    check_res = await execute_with_retry(
                        session,
                        text("""
                            SELECT entry_date FROM eq5d5l_entries
                            WHERE patient_id = :patient_id AND entry_date >= :min_date AND entry_date <= :max_date
                        """).bindparams(patient_id=patient_id, min_date=min_date, max_date=max_date)
                    )
                    filled_dates = set()
                    if check_res:
                        filled_dates = {row[0] for row in check_res.fetchall()}
                    for milestone_days, milestone_date, window_start, window_end in milestones_to_check:
                        if any(window_start <= d <= window_end for d in filled_dates):
                            continue
                        candidates.append((
                            milestone_date,
                            type_priority["eq5d5l"],
                            "eq5d5l",
                            f"EQ-5D-5L milestone at {milestone_days} days ({'due' if today >= milestone_date else 'upcoming'})"
                        ))
                        break  # only first unfilled milestone

            # Weekly: due 7 days after last fill, or from registration
            weekly_due_date = (last_weekly_date + timedelta(days=7)) if last_weekly_date else (patient_created_date or today)
            if today >= weekly_due_date:
                candidates.append((
                    weekly_due_date,
                    type_priority["weekly"],
                    "weekly",
                    "Weekly questionnaire due (7 days passed)" if last_weekly_date else "First weekly questionnaire (LARS)"
                ))

            # Monthly: due 28 days after last fill, or from registration
            monthly_due_date = (last_monthly_date + timedelta(days=28)) if last_monthly_date else (patient_created_date or today)
            if today >= monthly_due_date:
                candidates.append((
                    monthly_due_date,
                    type_priority["monthly"],
                    "monthly",
                    "Monthly questionnaire due (28+ days passed)" if last_monthly_date else "First monthly questionnaire"
                ))

            # Daily: due next day after last fill, or today if never filled
            daily_due_date = (last_daily_date + timedelta(days=1)) if last_daily_date else (patient_created_date or today)
            if today >= daily_due_date:
                candidates.append((
                    daily_due_date,
                    type_priority["daily"],
                    "daily",
                    "Daily questionnaire available" if last_daily_date else "First daily questionnaire"
                ))

            # Pick exactly one: earliest due date, then by type priority (so one questionnaire per day, logical order)
            if candidates:
                candidates.sort(key=lambda x: (x[0], x[1]))
                questionnaire_type = candidates[0][2]
                reason = candidates[0][3]
            else:
                # Fallback: nothing due (should not happen for daily) — offer daily
                questionnaire_type = "daily"
                reason = "Daily questionnaire available"
            
            # Check if today's questionnaire is already filled
            is_today_filled = False
            if questionnaire_type:
                try:
                    table_map = {
                        "weekly": "weekly_entries",
                        "monthly": "monthly_entries",
                        "eq5d5l": "eq5d5l_entries",
                        "daily": "daily_entries"
                    }
                    table_name = table_map.get(questionnaire_type)
                    if table_name:
                        check = await execute_with_retry(
                            session,
                            text(f"SELECT COUNT(*) FROM {table_name} WHERE patient_id = :pid AND entry_date = :today")
                            .bindparams(pid=patient_id, today=today)
                        )
                        if check:
                            check_row = check.first()
                            is_today_filled = check_row[0] > 0 if check_row else False
                except Exception as check_error:
                    print(f"Warning: Failed to check if today's questionnaire is filled: {check_error}")
                    is_today_filled = False
            
            return {
                "status": "ok",
                "questionnaire_type": questionnaire_type,
                "is_today_filled": is_today_filled,
                "reason": reason
            }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getNextQuestionnaire: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )

