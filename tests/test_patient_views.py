"""
Tests for the doctor-portal response helpers (src/services/patient_views.py).

Run from the backend folder (no database or extra packages needed):
    python3 -m unittest discover -s tests -v
"""
import itertools
import unittest
from datetime import date, timedelta
from decimal import Decimal

from src.services.patient_views import (
    LARS_ITEM_POINTS,
    LIST_LARS_RECENT_POINTS,
    daily_extra,
    eq5d5l_entry,
    lars_points,
    list_extension,
    monthly_entry,
    num,
    parse_include,
    weekly_entry,
)

D = date(2026, 10, 1)


def mapping(**over):
    """An appended-columns row as /getPatients sees it via row._mapping."""
    base = {
        "lars_dates": None, "lars_values": None, "vas_dates": None, "vas_values": None,
        "eq5d5l_count": 0, "last_daily_date": None, "last_weekly_date": None,
        "last_monthly_date": None, "last_eq5d5l_entry_date": None,
        "adherence_days_with_entry": 0, "adherence_days_expected": 0,
    }
    base.update(over)
    return base


class LarsScoring(unittest.TestCase):
    def test_maximum_is_42_and_minimum_is_0(self):
        best = min(sum(t[i] for t, i in zip(LARS_ITEM_POINTS.values(), c))
                   for c in itertools.product(*[range(len(t)) for t in LARS_ITEM_POINTS.values()]))
        worst = max(sum(t[i] for t, i in zip(LARS_ITEM_POINTS.values(), c))
                    for c in itertools.product(*[range(len(t)) for t in LARS_ITEM_POINTS.values()]))
        self.assertEqual((best, worst), (0, 42))

    def test_untouched_form_scores_4(self):
        # both apps pre-select index 0; bowel_frequency index 0 = "more than 7 times a day" = 4 points
        self.assertEqual(weekly_entry(D, 4, [0, 0, 0, 0, 0])["points_total"], 4)

    def test_points_and_total(self):
        e = weekly_entry(D, 32, [2, 1, 1, 1, 1])
        self.assertEqual(e["points"], {"flatus_control": 7, "liquid_stool_leakage": 3, "bowel_frequency": 2,
                                       "repeat_bowel_opening": 9, "urgency_to_toilet": 11})
        self.assertEqual((e["score"], e["points_total"], e["date"]), (32, 32, "2026-10-01"))

    def test_missing_total_keeps_row_and_computes_points(self):
        e = weekly_entry(D, None, [1, 0, 2, 1, 1])
        self.assertIsNone(e["score"])
        self.assertEqual(e["points_total"], 24)

    def test_out_of_range_answer_gives_null_points(self):
        p = lars_points({"flatus_control": 9, "liquid_stool_leakage": 0, "bowel_frequency": 0,
                         "repeat_bowel_opening": 0, "urgency_to_toilet": None})
        self.assertIsNone(p["flatus_control"])
        self.assertIsNone(p["urgency_to_toilet"])
        self.assertIsNone(weekly_entry(D, None, [9, 0, 0, 0, 0])["points_total"])


class OtherRows(unittest.TestCase):
    def test_eq5d5l_levels_are_stored_plus_one_and_vas_may_be_null(self):
        e = eq5d5l_entry(D, None, [0, 4, 1, 2, 3])
        self.assertEqual(e["levels"], {"mobility": 1, "self_care": 5, "usual_activities": 2,
                                       "pain_discomfort": 3, "anxiety_depression": 4})
        self.assertIsNone(e["vas"])

    def test_monthly_numeric_columns_become_plain_numbers(self):
        e = monthly_entry(D, [None, Decimal("3.0"), 2, 2, 3, 2, Decimal("6.5"), 7])
        self.assertIsNone(e["qol_score"])
        self.assertEqual(e["avoid_travel"], 3)
        self.assertIsInstance(e["avoid_travel"], int)
        self.assertEqual(e["control"], 6.5)
        self.assertEqual(num(None), None)

    def test_daily_extra(self):
        self.assertEqual(daily_extra(2, "Yes", "No", "Solid", "Yes", 6),
                         {"pads_used": 2, "urgency": True, "night_stools": False, "leakage": "solid",
                          "incomplete_evacuation": True, "activity_interfere": 6})
        self.assertEqual(daily_extra(0, None, "maybe", "None", "No", 0)["leakage"], "none")
        self.assertIsNone(daily_extra(0, None, "maybe", None, "No", 0)["urgency"])
        self.assertIsNone(daily_extra(0, None, "maybe", None, "No", 0)["night_stools"])
        self.assertIsNone(daily_extra(0, None, "maybe", None, "No", 0)["leakage"])


class ListExtension(unittest.TestCase):
    def test_empty_patient(self):
        out = list_extension(mapping(), set())
        self.assertEqual(out["lars_recent"], [])
        self.assertIsNone(out["first_lars_score"])
        self.assertIsNone(out["last_entry_date"])
        self.assertEqual(out["adherence_30d"], {"days_with_entry": 0, "days_expected": 0})
        self.assertNotIn("lars_history", out)

    def test_recent_keeps_last_12_oldest_first_and_history_is_opt_in(self):
        dates = [D - timedelta(days=7 * (14 - k)) for k in range(15)]
        out = list_extension(mapping(lars_dates=dates, lars_values=list(range(15))), parse_include("lars_history, junk"))
        self.assertEqual(len(out["lars_recent"]), LIST_LARS_RECENT_POINTS)
        self.assertEqual(out["lars_recent"][0]["score"], 3)
        self.assertEqual(out["lars_recent"][-1], {"date": "2026-10-01", "score": 14})
        self.assertEqual((out["first_lars_score"], out["first_lars_date"]), (0, dates[0].isoformat()))
        self.assertEqual(len(out["lars_history"]), 15)

    def test_vas_first_and_previous(self):
        out = list_extension(mapping(vas_dates=[D - timedelta(40), D - timedelta(10)], vas_values=[55, 70], eq5d5l_count=3), set())
        self.assertEqual((out["first_eq5d5l_score"], out["prev_eq5d5l_score"], out["eq5d5l_count"]), (55, 55, 3))
        one = list_extension(mapping(vas_dates=[D], vas_values=[60], eq5d5l_count=1), set())
        self.assertIsNone(one["prev_eq5d5l_score"])

    def test_last_entry_date_is_max_over_types(self):
        out = list_extension(mapping(last_daily_date=D + timedelta(1), last_weekly_date=D - timedelta(5),
                                     last_monthly_date=D - timedelta(38), last_eq5d5l_entry_date=D - timedelta(10)), set())
        self.assertEqual(out["last_entry_date"], "2026-10-02")
        self.assertEqual(out["last_dates"]["monthly"], "2026-08-24")


if __name__ == "__main__":
    unittest.main()
