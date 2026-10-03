"""
Tests for the "which questionnaire today" rules (src/services/questionnaire_schedule.py).

Run from the backend folder (no database or extra packages needed):
    python3 -m unittest discover -s tests -v
"""
import random
import unittest
from datetime import date, timedelta

from src.services.questionnaire_schedule import (
    EQ5D5L_EARLY_DAYS,
    EQ5D5L_TIME_POINTS_DAYS,
    PRIORITY,
    pick_questionnaire,
)

START = date(2026, 1, 1)


def day(n: int) -> date:
    """Date of day n after START (day 0 = registration day)."""
    return START + timedelta(days=n)


def never_filled() -> dict:
    return {t: None for t in PRIORITY}


def simulate(start, first_day, last_day, present=lambda d: True, last_filled=None):
    """
    Walk day by day. On every day the patient opens the app (present), they fill
    whatever is offered. Returns [(date, type), ...] of everything filled.
    Also checks that nothing else is offered once something was filled that day.
    """
    last_filled = dict(last_filled or never_filled())
    fills = []
    current = first_day
    while current <= last_day:
        if present(current):
            offered = pick_questionnaire(current, start, last_filled)["questionnaire_type"]
            if offered is not None:
                last_filled[offered] = current
                fills.append((current, offered))
                again = pick_questionnaire(current, start, last_filled)
                assert again["questionnaire_type"] is None, f"second questionnaire offered on {current}"
                assert again["today_filled_type"] == offered
        current += timedelta(days=1)
    return fills


def dates_of(fills, qtype):
    return [d for d, t in fills if t == qtype]


def gaps(dates):
    return [(b - a).days for a, b in zip(dates, dates[1:])]


class NewPatientTests(unittest.TestCase):
    def test_first_days_bring_one_questionnaire_per_day(self):
        fills = simulate(START, day(0), day(4))
        self.assertEqual(
            [t for _, t in fills],
            ["eq5d5l", "monthly", "weekly", "daily", "daily"],
        )

    def test_first_reasons(self):
        choice = pick_questionnaire(day(0), START, never_filled())
        self.assertEqual(choice, {
            "questionnaire_type": "eq5d5l",
            "is_today_filled": False,
            "today_filled_type": None,
            "reason": "First EQ-5D-5L questionnaire",
        })

    def test_code_given_long_before_first_use(self):
        """Doctor created the code on day 0, patient opens the app on day 40."""
        fills = simulate(START, day(0), day(100), present=lambda d: d >= day(40))
        self.assertEqual(fills[:4], [
            (day(40), "eq5d5l"),   # covers the missed baseline, 14- and 30-day points
            (day(41), "monthly"),
            (day(42), "weekly"),
            (day(43), "daily"),
        ])
        self.assertEqual(dates_of(fills, "eq5d5l"), [day(40), day(90)])


class OnePerDayTests(unittest.TestCase):
    def test_nothing_more_after_filling_today(self):
        last = never_filled() | {"eq5d5l": day(0), "monthly": day(1), "weekly": day(2), "daily": day(5)}
        choice = pick_questionnaire(day(5), START, last)
        self.assertEqual(choice, {
            "questionnaire_type": None,
            "is_today_filled": True,
            "today_filled_type": "daily",
            "reason": "You have already completed a questionnaire today.",
        })

    def test_reports_highest_priority_type_filled_today(self):
        """Old rules allowed several on day 1; the edit button must open the main one."""
        last = never_filled() | {"weekly": day(0), "daily": day(0)}
        self.assertEqual(pick_questionnaire(day(0), START, last)["today_filled_type"], "weekly")

    def test_answer_dated_after_server_today_counts_as_today(self):
        """Web app sends the browser's local date, which can be ahead of the server's date."""
        last = never_filled() | {"eq5d5l": day(0), "monthly": day(1), "weekly": day(2), "daily": day(6)}
        choice = pick_questionnaire(day(5), START, last)
        self.assertTrue(choice["is_today_filled"])
        self.assertIsNone(choice["questionnaire_type"])


class EQ5D5LTests(unittest.TestCase):
    def test_daily_user_gets_it_exactly_on_time_points(self):
        fills = simulate(START, day(0), day(1000))
        self.assertEqual(
            dates_of(fills, "eq5d5l"),
            [day(0), day(14), day(30), day(90), day(180), day(365)],
        )

    def test_reported_bug_not_repeated_every_day(self):
        """
        Real case (patient BENAS): registered 2025-11-11, missed the 180-day point,
        filled EQ-5D-5L late on 2026-08-17. Old rules then offered EQ-5D-5L on every
        visit (08-28, 08-29, 09-04, 09-19, 10-02, 10-03) and nothing else.
        """
        start = date(2025, 11, 11)
        last = {
            "eq5d5l": date(2026, 8, 17),
            "monthly": date(2026, 4, 18),
            "weekly": date(2026, 6, 23),
            "daily": date(2026, 4, 4),
        }
        fills = simulate(start, date(2026, 8, 18), date(2026, 11, 20), last_filled=last)
        self.assertEqual(fills[:3], [
            (date(2026, 8, 18), "monthly"),
            (date(2026, 8, 19), "weekly"),
            (date(2026, 8, 20), "daily"),
        ])
        # Next EQ-5D-5L only at the 365-day point.
        self.assertEqual(dates_of(fills, "eq5d5l"), [date(2026, 11, 11)])

    def test_missed_time_points_give_one_questionnaire_not_one_each(self):
        last = never_filled() | {"eq5d5l": day(0), "monthly": day(1), "weekly": day(2), "daily": day(3)}
        fills = simulate(START, day(100), day(179), last_filled=last)
        self.assertEqual(fills[0], (day(100), "eq5d5l"))
        self.assertEqual(pick_questionnaire(day(100), START, never_filled())["reason"],
                         "EQ-5D-5L milestone at 90 days")
        self.assertEqual(dates_of(fills, "eq5d5l"), [day(100)])

    def test_late_fill_just_before_next_time_point_counts_for_it(self):
        """Back on day 86 (30-day point missed): one EQ-5D-5L, none again on day 90."""
        last = never_filled() | {"eq5d5l": day(0), "monthly": day(1), "weekly": day(2), "daily": day(3)}
        fills = simulate(START, day(86), day(179), last_filled=last)
        self.assertEqual(dates_of(fills, "eq5d5l"), [day(86)])

    def test_late_fill_eight_days_before_next_point_does_not_count(self):
        last = never_filled() | {"eq5d5l": day(0), "monthly": day(1), "weekly": day(2), "daily": day(3)}
        fills = simulate(START, day(82), day(179), last_filled=last)
        self.assertEqual(dates_of(fills, "eq5d5l"), [day(82), day(90)])

    def test_none_after_last_time_point(self):
        last = never_filled() | {"eq5d5l": day(365), "monthly": day(360), "weekly": day(364), "daily": day(366)}
        fills = simulate(START, day(367), day(2000), last_filled=last)
        self.assertEqual(dates_of(fills, "eq5d5l"), [])


class WeeklyMonthlyTests(unittest.TestCase):
    def test_intervals_for_a_patient_who_opens_the_app_every_day(self):
        fills = simulate(START, day(0), day(730))
        weekly_gaps = gaps(dates_of(fills, "weekly"))
        monthly_gaps = gaps(dates_of(fills, "monthly"))
        # Pushed back by at most 2 days when EQ-5D-5L / monthly take the day.
        self.assertTrue(all(7 <= g <= 9 for g in weekly_gaps), weekly_gaps)
        self.assertTrue(all(28 <= g <= 29 for g in monthly_gaps), monthly_gaps)
        # Daily is still the usual questionnaire (~80% of days).
        self.assertGreater(len(dates_of(fills, "daily")), 0.75 * len(fills))

    def test_long_break_brings_each_one_back_once(self):
        """Active for 2 months, away for 3 months, then back every day."""
        fills = simulate(
            START, day(0), day(200),
            present=lambda d: d <= day(60) or d >= day(151),
        )
        after_break = [t for d, t in fills if d >= day(151)]
        self.assertEqual(after_break[:6], ["eq5d5l", "monthly", "weekly", "daily", "daily", "daily"])


class RandomUsageTests(unittest.TestCase):
    """Hundreds of random visit patterns: the basic guarantees must always hold."""

    def test_guarantees_hold_for_random_visit_patterns(self):
        end = day(899)
        for seed in range(300):
            rng = random.Random(seed)
            chance = rng.choice([0.1, 0.3, 0.6, 0.9, 1.0])
            breaks = set()
            for _ in range(rng.randint(0, 4)):
                first = rng.randint(0, 700)
                breaks.update(range(first, first + rng.randint(5, 150)))
            visits = {
                day(n) for n in range(0, 900)
                if n not in breaks and rng.random() < chance
            }
            with self.subTest(seed=seed):
                fills = simulate(START, day(0), end, present=lambda d: d in visits)
                filled_on = dict(fills)

                # Never the same periodic questionnaire too soon (= no backlog).
                self.assertTrue(all(g >= 8 for g in gaps(dates_of(fills, "eq5d5l"))))
                self.assertTrue(all(g >= 7 for g in gaps(dates_of(fills, "weekly"))))
                self.assertTrue(all(g >= 28 for g in gaps(dates_of(fills, "monthly"))))

                # Once due, weekly/monthly can only be pushed back by a
                # higher-priority questionnaire, never by daily.
                for qtype, interval, allowed in (
                    ("weekly", 7, {"eq5d5l", "monthly"}),
                    ("monthly", 28, {"eq5d5l"}),
                ):
                    dates = dates_of(fills, qtype)
                    # Never filled yet = due from day 0; after the last fill, due until the end.
                    for prev, nxt in zip([START - timedelta(days=interval)] + dates,
                                         dates + [end + timedelta(days=1)]):
                        due = prev + timedelta(days=interval)
                        taken_by = {t for d, t in fills if due <= d < nxt}
                        self.assertLessEqual(taken_by, allowed, (qtype, prev, nxt))

                # An EQ-5D-5L time point not yet covered is served at the first visit.
                eq_dates = dates_of(fills, "eq5d5l")
                for p in EQ5D5L_TIME_POINTS_DAYS:
                    point = day(p)
                    first_visit = min((v for v in visits if v >= point), default=None)
                    if first_visit is None:
                        continue
                    covered_from = point - timedelta(days=EQ5D5L_EARLY_DAYS)
                    if not any(covered_from <= d < first_visit for d in eq_dates):
                        self.assertEqual(filled_on.get(first_visit), "eq5d5l", (p, first_visit))


if __name__ == "__main__":
    unittest.main()
