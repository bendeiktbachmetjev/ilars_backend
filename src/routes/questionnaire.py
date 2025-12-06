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
    Determine which questionnaire should be filled today based on:
    - EQ-5D-5L: at 2 weeks, 1 month, 3 months, 6 months, 12 months after patient registration
    - Weekly (LARS): once per week (every 7 days)
    - Monthly: once per month (~30 days)
    - Daily: if no mandatory questionnaires are due
    
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
            
            # Determine next questionnaire using priority logic
            questionnaire_type = None
            reason = None
            
            # Priority 1: EQ-5D-5L (quality of life) - scheduled milestones
            if patient_created_date:
                days_since_start = (today - patient_created_date).days
                eq5d5l_milestones = [14, 30, 90, 180, 365]  # 2 weeks, 1 month, 3 months, 6 months, 12 months
                
                milestones_to_check = []
                for milestone_days in eq5d5l_milestones:
                    milestone_date = patient_created_date + timedelta(days=milestone_days)
                    if today >= milestone_date - timedelta(days=3) and days_since_start >= milestone_days - 3:
                        milestones_to_check.append((milestone_days, milestone_date))
                
                if milestones_to_check:
                    date_ranges = []
                    for milestone_days, milestone_date in milestones_to_check:
                        window_start = milestone_date - timedelta(days=3)
                        window_end = milestone_date + timedelta(days=7)
                        date_ranges.append((milestone_days, milestone_date, window_start, window_end))
                    
                    if date_ranges:
                        min_date = min(range_item[2] for range_item in date_ranges)
                        max_date = max(range_item[3] for range_item in date_ranges)
                        
                        check_res = await execute_with_retry(
                            session,
                            text("""
                                SELECT entry_date
                                FROM eq5d5l_entries
                                WHERE patient_id = :patient_id
                                    AND entry_date >= :min_date
                                    AND entry_date <= :max_date
                            """).bindparams(
                                patient_id=patient_id,
                                min_date=min_date,
                                max_date=max_date
                            )
                        )
                        
                        filled_dates = set()
                        if check_res:
                            filled_dates = {row[0] for row in check_res.fetchall()}
                        
                        for milestone_days, milestone_date, window_start, window_end in date_ranges:
                            milestone_filled = any(
                                window_start <= filled_date <= window_end 
                                for filled_date in filled_dates
                            )
                            
                            if not milestone_filled:
                                questionnaire_type = "eq5d5l"
                                reason = f"EQ-5D-5L milestone at {milestone_days} days ({'due' if days_since_start >= milestone_days else 'upcoming'})"
                                break
            
            # Priority 2: Weekly (LARS) - once per week
            if not questionnaire_type:
                if last_weekly_date:
                    days_since_weekly = (today - last_weekly_date).days
                    if days_since_weekly >= 7:
                        questionnaire_type = "weekly"
                        reason = "Weekly questionnaire due (7 days passed)"
                else:
                    questionnaire_type = "weekly"
                    reason = "First weekly questionnaire"
            
            # Priority 3: Monthly - once per month
            if not questionnaire_type:
                if last_monthly_date:
                    days_since_monthly = (today - last_monthly_date).days
                    if days_since_monthly >= 28:
                        weekly_due_today = False
                        if last_weekly_date:
                            days_since_weekly = (today - last_weekly_date).days
                            if days_since_weekly >= 7:
                                weekly_due_today = True
                        
                        if not weekly_due_today:
                            questionnaire_type = "monthly"
                            reason = "Monthly questionnaire due (28+ days passed)"
                else:
                    weekly_due = False
                    if last_weekly_date:
                        days_since_weekly = (today - last_weekly_date).days
                        if days_since_weekly >= 7:
                            weekly_due = True
                    
                    if not weekly_due:
                        questionnaire_type = "monthly"
                        reason = "First monthly questionnaire"
            
            # Priority 4: Daily - if no mandatory questionnaires are due
            if not questionnaire_type:
                if last_daily_date:
                    if (today - last_daily_date).days >= 1:
                        questionnaire_type = "daily"
                        reason = "Daily questionnaire available"
                else:
                    questionnaire_type = "daily"
                    reason = "First daily questionnaire"
            
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

