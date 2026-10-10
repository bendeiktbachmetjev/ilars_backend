"""
Validation utilities
"""
import re
from datetime import date, datetime, timezone
from typing import Optional
from fastapi import HTTPException

# A questionnaire answer is for today; the app sends no date (the database
# uses today) and the web form sends the patient's own today, at most a day
# away from the server's UTC date
ENTRY_DATE_WINDOW_DAYS = 2
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_patient_code(patient_code: Optional[str]) -> str:
    """
    Validate and normalize patient code
    
    Args:
        patient_code: Patient code to validate
        
    Returns:
        Normalized patient code
        
    Raises:
        HTTPException: If patient code is invalid
    """
    if not patient_code:
        raise HTTPException(status_code=400, detail="Missing X-Patient-Code header")
    
    patient_code = patient_code.strip().upper()
    
    if not patient_code or len(patient_code) < 4 or len(patient_code) > 64:
        raise HTTPException(status_code=400, detail="Invalid patient code format")
    
    return patient_code


def parse_iso_date(value) -> Optional[date]:
    """A YYYY-MM-DD string as a date, or None for anything else."""
    if not isinstance(value, str) or not ISO_DATE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def validate_entry_date(entry_date: Optional[str]) -> Optional[str]:
    """
    Check a questionnaire's entry_date: none (the database uses today) or a
    YYYY-MM-DD within ENTRY_DATE_WINDOW_DAYS of today.

    Raises:
        HTTPException: 400 for any other value
    """
    if entry_date is None:
        return None
    parsed = parse_iso_date(entry_date)
    if parsed is None or abs((parsed - utc_today()).days) > ENTRY_DATE_WINDOW_DAYS:
        print(f"🚦 [limit] entry_date refused: {str(entry_date)[:20]!r} (today ±{ENTRY_DATE_WINDOW_DAYS} days only)")
        raise HTTPException(
            status_code=400,
            detail=f"entry_date must be a date (YYYY-MM-DD) within {ENTRY_DATE_WINDOW_DAYS} days of today",
        )
    return parsed.isoformat()


def validate_period(period: str) -> str:
    """
    Validate time period parameter

    Args:
        period: Period to validate. Allowed values:
            - "weekly"    (7 days)
            - "monthly"   (30 days)
            - "3months"   (90 days)
            - "6months"   (180 days)
            - "yearly"    (365 days)

    Returns:
        Validated period

    Raises:
        HTTPException: If period is invalid
    """
    allowed = ["weekly", "monthly", "3months", "6months", "yearly"]
    if period not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period. Must be one of: {', '.join(allowed)}"
        )
    return period

