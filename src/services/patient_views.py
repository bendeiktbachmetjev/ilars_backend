"""
Doctor-portal response helpers for /getPatients and /getPatientDetail (API extension v2).

Pure functions: no database, no web framework, so they can be unit-tested with the
standard library (python3 -m unittest discover -s tests -v).

All additions are ADDITIVE: they produce new keys only. The legacy keys of both
endpoints are still built in src/routes/patients.py exactly as before.
"""
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence

# LARS points per stored answer index (Emmertsen & Laurberg 2012). Same table as the
# patient apps (web/app/js/views/weekly.js LARS_SCORES, Flutter weekly screen).
# Key order = order of the answer columns in the weekly SELECT.
LARS_ITEM_POINTS: Dict[str, tuple] = {
    "flatus_control": (0, 4, 7),
    "liquid_stool_leakage": (0, 3, 3),
    "bowel_frequency": (4, 2, 0, 5),
    "repeat_bowel_opening": (0, 9, 11),
    "urgency_to_toilet": (0, 11, 16),
}
LARS_ITEMS = tuple(LARS_ITEM_POINTS)

# EQ-5D-5L dimensions; stored 0..4, returned as EuroQol levels 1..5 (stored + 1).
EQ5D5L_DIMENSIONS = ("mobility", "self_care", "usual_activities", "pain_discomfort", "anxiety_depression")

# Monthly QoL columns, in SELECT order.
MONTHLY_FIELDS = ("qol_score", "avoid_travel", "avoid_social", "embarrassed",
                  "worry_notice", "depressed", "control", "satisfaction")

# How many of the latest LARS scores /getPatients returns for the list sparkline.
LIST_LARS_RECENT_POINTS = 12

# Optional blocks a client may request with /getPatients?include=...
INCLUDE_LARS_HISTORY = "lars_history"


def iso(d: Optional[date]) -> Optional[str]:
    """date -> 'YYYY-MM-DD' (None stays None)."""
    return d.isoformat() if d is not None else None


def num(v: Any) -> Optional[Any]:
    """DB number -> JSON number. Decimal (a NUMERIC column) becomes int when whole, else float."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def yes_no(v: Optional[str]) -> Optional[bool]:
    """'Yes' -> True, 'No' -> False, anything else / NULL -> None (not recorded)."""
    if v == "Yes":
        return True
    if v == "No":
        return False
    return None


def leakage(v: Optional[str]) -> Optional[str]:
    """DB 'None' | 'Liquid' | 'Solid' -> 'none' | 'liquid' | 'solid'; NULL/unknown -> None."""
    return {"None": "none", "Liquid": "liquid", "Solid": "solid"}.get(v) if v is not None else None


def lars_points(answers: Mapping[str, Optional[int]]) -> Dict[str, Optional[int]]:
    """Answer index per item -> LARS points per item (None if the index is missing or out of range)."""
    out: Dict[str, Optional[int]] = {}
    for item, table in LARS_ITEM_POINTS.items():
        idx = answers.get(item)
        out[item] = table[idx] if isinstance(idx, int) and 0 <= idx < len(table) else None
    return out


def weekly_entry(entry_date: date, total_score: Optional[int], answer_values: Sequence[Optional[int]]) -> Dict[str, Any]:
    """One weekly_entries row -> /getPatientDetail weekly_entries[] item."""
    answers = {item: (int(v) if v is not None else None) for item, v in zip(LARS_ITEMS, answer_values)}
    points = lars_points(answers)
    points_total = None if any(p is None for p in points.values()) else sum(points.values())
    return {
        "date": iso(entry_date),
        "score": int(total_score) if total_score is not None else None,
        "points_total": points_total,
        "answers": answers,
        "points": points,
    }


def eq5d5l_entry(entry_date: date, health_vas: Optional[int], stored_levels: Sequence[Optional[int]]) -> Dict[str, Any]:
    """One eq5d5l_entries row -> /getPatientDetail eq5d5l_entries[] item (levels 1..5)."""
    return {
        "date": iso(entry_date),
        "vas": int(health_vas) if health_vas is not None else None,
        "levels": {dim: (int(v) + 1 if v is not None else None) for dim, v in zip(EQ5D5L_DIMENSIONS, stored_levels)},
    }


def monthly_entry(entry_date: date, values: Sequence[Any]) -> Dict[str, Any]:
    """One monthly_entries row -> /getPatientDetail monthly_entries[] item."""
    item: Dict[str, Any] = {"date": iso(entry_date)}
    for field, v in zip(MONTHLY_FIELDS, values):
        item[field] = num(v)
    return item


def daily_extra(pads_used: Any, urgency: Optional[str], night_stools: Optional[str], leakage_value: Optional[str],
                incomplete_evacuation: Optional[str], activity_interfere: Any) -> Dict[str, Any]:
    """Six diary fields that /getPatientDetail daily_entries[] did not return before."""
    return {
        "pads_used": num(pads_used),
        "urgency": yes_no(urgency),
        "night_stools": yes_no(night_stools),
        "leakage": leakage(leakage_value),
        "incomplete_evacuation": yes_no(incomplete_evacuation),
        "activity_interfere": num(activity_interfere),
    }


def parse_include(include: Optional[str]) -> set:
    """'a, b' -> {'a', 'b'}; unknown names are ignored by the caller."""
    return {part.strip() for part in (include or "").split(",") if part.strip()}


def list_extension(m: Mapping[str, Any], include: set) -> Dict[str, Any]:
    """
    Extra /getPatients keys for one patient, from the appended SELECT columns
    (row._mapping). Keys: see docs/doctor-api-v2.md.
    """
    lars = [{"date": iso(d), "score": int(s)} for d, s in zip(m["lars_dates"] or [], m["lars_values"] or [])]
    vas = [{"date": iso(d), "score": int(s)} for d, s in zip(m["vas_dates"] or [], m["vas_values"] or [])]
    last_dates = {
        "daily": iso(m["last_daily_date"]),
        "weekly": iso(m["last_weekly_date"]),
        "monthly": iso(m["last_monthly_date"]),
        "eq5d5l": iso(m["last_eq5d5l_entry_date"]),
    }
    present = [d for d in last_dates.values() if d is not None]
    out: Dict[str, Any] = {
        "first_lars_score": lars[0]["score"] if lars else None,
        "first_lars_date": lars[0]["date"] if lars else None,
        "lars_recent": lars[-LIST_LARS_RECENT_POINTS:],
        "first_eq5d5l_score": vas[0]["score"] if vas else None,
        "first_eq5d5l_date": vas[0]["date"] if vas else None,
        "prev_eq5d5l_score": vas[-2]["score"] if len(vas) >= 2 else None,
        "prev_eq5d5l_date": vas[-2]["date"] if len(vas) >= 2 else None,
        "eq5d5l_count": int(m["eq5d5l_count"] or 0),
        "last_dates": last_dates,
        "last_entry_date": max(present) if present else None,   # ISO dates sort as text
        "adherence_30d": {
            "days_with_entry": int(m["adherence_days_with_entry"] or 0),
            "days_expected": int(m["adherence_days_expected"] or 0),
        },
    }
    if INCLUDE_LARS_HISTORY in include:
        out["lars_history"] = lars
    return out
