"""
Which questionnaire a patient should fill today.

Pure rules with no database access, so they can be unit-tested.
Full description with examples: docs/questionnaire-schedule.md
(keep it in sync when changing anything here).
"""
from datetime import date, timedelta
from typing import Dict, Optional

# When several questionnaires are due on the same day, the first one here wins:
# the rarer the questionnaire, the higher its priority. Daily is the fallback.
PRIORITY = ("eq5d5l", "monthly", "weekly", "daily")

WEEKLY_INTERVAL_DAYS = 7
MONTHLY_INTERVAL_DAYS = 28

# EQ-5D-5L time points, in days after the patient's start date (0 = baseline).
EQ5D5L_TIME_POINTS_DAYS = (0, 14, 30, 90, 180, 365)

# An EQ-5D-5L filled up to this many days before a time point counts for it.
# This also guarantees that two EQ-5D-5L are never given less than 8 days apart.
EQ5D5L_EARLY_DAYS = 7


def pick_questionnaire(
    today: date,
    start_date: date,
    last_filled: Dict[str, Optional[date]],
) -> dict:
    """
    Decide what the patient should fill today: at most one questionnaire per day.

    Args:
        today: Current date (same clock as the dates of saved answers)
        start_date: Date the patient was registered
        last_filled: Last date each type was filled, e.g. {"weekly": date | None, ...}

    Returns:
        The /getNextQuestionnaire response fields (without "status")
    """
    # ">=" rather than "==": the web app sends the browser's local date, which
    # can be one day ahead of the server's date shortly after local midnight.
    filled_today = [t for t in PRIORITY if last_filled.get(t) is not None and last_filled[t] >= today]
    if filled_today:
        return {
            "questionnaire_type": None,
            "is_today_filled": True,
            "today_filled_type": filled_today[0],
            "reason": "You have already completed a questionnaire today.",
        }

    questionnaire_type, reason = _first_due(today, start_date, last_filled)
    return {
        "questionnaire_type": questionnaire_type,
        "is_today_filled": False,
        "today_filled_type": None,
        "reason": reason,
    }


def _first_due(today: date, start_date: date, last_filled: Dict[str, Optional[date]]):
    """Return (type, reason) of the highest-priority questionnaire that is due."""
    eq5d5l_reason = _eq5d5l_due_reason(today, start_date, last_filled.get("eq5d5l"))
    if eq5d5l_reason:
        return "eq5d5l", eq5d5l_reason

    # Missed weeks/months never pile up: only the date of the LAST fill matters,
    # so after any break each questionnaire comes back once.
    last_monthly = last_filled.get("monthly")
    if last_monthly is None:
        return "monthly", "First monthly questionnaire"
    if (today - last_monthly).days >= MONTHLY_INTERVAL_DAYS:
        return "monthly", "Monthly questionnaire due"

    last_weekly = last_filled.get("weekly")
    if last_weekly is None:
        return "weekly", "First weekly questionnaire (LARS)"
    if (today - last_weekly).days >= WEEKLY_INTERVAL_DAYS:
        return "weekly", "Weekly questionnaire due"

    if last_filled.get("daily") is None:
        return "daily", "First daily questionnaire"
    return "daily", "Daily questionnaire available"


def _eq5d5l_due_reason(today: date, start_date: date, last_eq5d5l: Optional[date]) -> Optional[str]:
    """
    EQ-5D-5L is due when the latest time point that has already arrived is not
    covered by an EQ-5D-5L filled on or after (time point - EQ5D5L_EARLY_DAYS).

    Older missed time points are dropped: one late questionnaire covers them all.
    """
    days_since_start = (today - start_date).days
    arrived = [p for p in EQ5D5L_TIME_POINTS_DAYS if p <= days_since_start]
    if not arrived:
        return None
    point = arrived[-1]

    covered_from = start_date + timedelta(days=point - EQ5D5L_EARLY_DAYS)
    if last_eq5d5l is not None and last_eq5d5l >= covered_from:
        return None

    if point == 0:
        return "First EQ-5D-5L questionnaire"
    return f"EQ-5D-5L milestone at {point} days"
