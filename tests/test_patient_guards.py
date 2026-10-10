"""
Tests for the brakes on the patient endpoints (no login, only X-Patient-Code):

- an unknown code gets 404 and never creates a patient (sendDaily, sendWeekly,
  sendMonthly, sendEq5d5l, sendSteps);
- entry_date: none (= today) or today ±2 days;
- sendSteps: dates from 30 days before the patient was created to today, step
  counts 0..200,000, one row per day; a ~550-day first sync is not capped;
- request bodies over 1 MB: 413, with or without a Content-Length;
- about 120 requests a minute per address on the patient endpoints.

The database is an in-memory fake; nothing leaves the machine.
Run from the backend folder (needs fastapi, sqlalchemy, slowapi and httpx):
    python3 -m unittest discover -s tests -v
"""
import unittest
import uuid
from datetime import date, timedelta
from unittest import mock

try:
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    from src.limits import MAX_BODY_BYTES, limiter
    from src.main import app
    from src.routes.steps import MAX_STEPS_PER_DAY, StepEntry, steps_to_save
    from src.utils.validators import utc_today, validate_entry_date
    HAVE_DEPS = True
except ImportError:  # pragma: no cover
    HAVE_DEPS = False

KNOWN = "ABC123"
CREATED = date(2026, 4, 5)


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.rows[0][0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeDb:
    """Answers the few statements these routes send; remembers every one."""

    def __init__(self):
        self.statements = []
        self.patient_id = str(uuid.uuid4())
        self.created = CREATED

    def session(self):
        db = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def begin(self):
                return self

            async def commit(self):
                return None

            async def execute(self, stmt):
                sql = " ".join(str(stmt).split())
                params = stmt.compile().params
                db.statements.append((sql, params))
                if "FROM patients WHERE patient_code" in sql:
                    return FakeResult([(db.patient_id,)] if params.get("code") == KNOWN else [])
                if "SELECT created_at::date FROM patients" in sql:
                    return FakeResult([(db.created,)])
                if "RETURNING id" in sql:
                    return FakeResult([(uuid.uuid4(),)])
                return FakeResult([])

        return Session()

    def inserts(self, table):
        return [params for sql, params in self.statements if sql.startswith(f"INSERT INTO {table}")]


SEND_MODULES = ["daily", "weekly", "monthly", "eq5d5l", "steps", "patients", "questionnaire"]

BODIES = {
    "/sendDaily": {"bristol_scale": 4, "raw_data": {"stool_count": 2}},
    "/sendWeekly": {"flatus_control": 0, "liquid_stool_leakage": 0, "bowel_frequency": 0,
                    "repeat_bowel_opening": 0, "urgency_to_toilet": 0, "raw_data": {"total_score": 0}},
    "/sendMonthly": {"qol_score": 5, "raw_data": {}},
    "/sendEq5d5l": {"mobility": 1, "self_care": 1, "usual_activities": 1, "pain_discomfort": 1,
                    "anxiety_depression": 1, "health_vas": 80},
}
TABLE = {"/sendDaily": "daily_entries", "/sendWeekly": "weekly_entries",
         "/sendMonthly": "monthly_entries", "/sendEq5d5l": "eq5d5l_entries"}


@unittest.skipUnless(HAVE_DEPS, "needs fastapi, sqlalchemy, slowapi and httpx")
class PatientGuards(unittest.TestCase):
    def setUp(self):
        limiter.reset()
        self.db = FakeDb()
        self.patches = []
        for name in SEND_MODULES:
            for attr, value in (("is_initialized", lambda: True), ("get_session", lambda: self.db.session)):
                p = mock.patch(f"src.routes.{name}.{attr}", value)
                p.start()
                self.patches.append(p)
        self.client = TestClient(app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        limiter.reset()

    def post(self, path, body, code=KNOWN, ip="203.0.113.5"):
        return self.client.post(path, json=body, headers={"X-Patient-Code": code, "X-Real-IP": ip})

    # --- unknown codes ---------------------------------------------------------

    def test_unknown_code_is_404_and_creates_nothing(self):
        for path, body in BODIES.items():
            r = self.post(path, body, code="NOPE99")
            self.assertEqual(r.status_code, 404, path)
            self.assertEqual(r.json()["detail"], "Patient not found")
        r = self.post("/sendSteps", {"steps": [{"step_date": CREATED.isoformat(), "step_count": 10}]}, code="NOPE99")
        self.assertEqual(r.status_code, 404)
        for sql, _ in self.db.statements:
            self.assertFalse(sql.startswith("INSERT"), "nothing written for an unknown code: " + sql[:60])

    def test_known_code_still_saves(self):
        for path, body in BODIES.items():
            r = self.post(path, body)
            self.assertEqual(r.status_code, 200, f"{path}: {r.text}")
            self.assertEqual(len(self.db.inserts(TABLE[path])), 1, path)
            self.assertIsNone(self.db.inserts(TABLE[path])[0]["entry_date"], "no date = the database's today")

    # --- entry_date ------------------------------------------------------------

    def test_entry_date_window(self):
        today = utc_today()
        self.assertIsNone(validate_entry_date(None))
        for days in (-2, -1, 0, 1, 2):
            d = (today + timedelta(days=days)).isoformat()
            self.assertEqual(validate_entry_date(d), d)
        for bad in ((today - timedelta(days=3)).isoformat(), (today + timedelta(days=3)).isoformat(),
                    "2026-02-30", "20261010", "2026-W41-6", "", "yesterday", "1900-01-01"):
            with self.assertRaises(HTTPException, msg=bad) as ctx:
                validate_entry_date(bad)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_entry_date_on_the_routes(self):
        today = utc_today().isoformat()
        old = (utc_today() - timedelta(days=30)).isoformat()
        for path, body in BODIES.items():
            self.assertEqual(self.post(path, {**body, "entry_date": today}).status_code, 200, path)
            self.assertEqual(self.db.inserts(TABLE[path])[-1]["entry_date"], today)
            before = len(self.db.statements)
            r = self.post(path, {**body, "entry_date": old})
            self.assertEqual(r.status_code, 400, path)
            self.assertEqual(len(self.db.statements), before, "refused before the database")

    # --- steps -----------------------------------------------------------------

    def test_steps_window_and_counts(self):
        today = date(2026, 10, 10)
        entries = [
            StepEntry(step_date=(CREATED - timedelta(days=30)).isoformat(), step_count=0),       # first day allowed
            StepEntry(step_date=(CREATED - timedelta(days=31)).isoformat(), step_count=100),     # too early
            StepEntry(step_date=(today + timedelta(days=1)).isoformat(), step_count=100),        # a patient's today ahead of UTC
            StepEntry(step_date=(today + timedelta(days=2)).isoformat(), step_count=100),        # the future
            StepEntry(step_date="2026-05-01", step_count=MAX_STEPS_PER_DAY),
            StepEntry(step_date="2026-05-02", step_count=MAX_STEPS_PER_DAY + 1),
            StepEntry(step_date="2026-05-03", step_count=-1),
            StepEntry(step_date="not-a-date", step_count=10),
            StepEntry(step_date="2026-05-04", step_count=10),
            StepEntry(step_date="2026-05-04", step_count=20),                                    # the same day again
        ]
        keep, skipped = steps_to_save(entries, CREATED, today)
        self.assertEqual(keep, {
            CREATED - timedelta(days=30): 0,
            today + timedelta(days=1): 100,
            date(2026, 5, 1): MAX_STEPS_PER_DAY,
            date(2026, 5, 4): 20,
        })
        self.assertEqual(skipped, len(entries) - 4)

    def test_a_550_day_first_sync_is_not_capped(self):
        today = utc_today()
        days = [today - timedelta(days=n) for n in range(1, 551)]
        self.db.created = days[-1]
        r = self.post("/sendSteps", {"steps": [{"step_date": d.isoformat(), "step_count": 5000} for d in days]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"status": "ok", "saved": 550, "skipped": 0})
        self.assertEqual(len(self.db.inserts("daily_steps")), 550)

    def test_steps_outside_the_window_are_not_stored(self):
        r = self.post("/sendSteps", {"steps": [
            {"step_date": "2001-01-01", "step_count": 10},
            {"step_date": CREATED.isoformat(), "step_count": 10},
            {"step_date": CREATED.isoformat(), "step_count": 999999},
        ]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"status": "ok", "saved": 1, "skipped": 2})
        self.assertEqual([p["step_count"] for p in self.db.inserts("daily_steps")], [10])

    # --- body size ---------------------------------------------------------------

    def test_body_over_1_mb_is_refused(self):
        big = b'{"steps": [' + b" " * (MAX_BODY_BYTES + 10) + b"]}"
        r = self.client.post("/sendSteps", content=big, headers={"X-Patient-Code": KNOWN, "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)
        self.assertEqual(self.db.statements, [], "refused before the database")

        def chunks():
            yield b'{"steps": ['
            for _ in range(20):
                yield b" " * (64 * 1024)
            yield b"]}"
        r = self.client.post("/sendSteps", content=chunks(), headers={"X-Patient-Code": KNOWN, "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413, "a body without a length is cut off too")
        self.assertEqual(self.db.statements, [])

        # an ordinary body still passes
        self.assertEqual(self.post("/sendSteps", {"steps": [{"step_date": CREATED.isoformat(), "step_count": 1}]}).status_code, 200)

    # --- requests per address ------------------------------------------------------

    def test_120_requests_a_minute_per_address(self):
        headers = {"X-Patient-Code": KNOWN, "X-Real-IP": "198.51.100.20"}
        for i in range(120):
            self.assertNotEqual(self.client.get("/getNextQuestionnaire", headers=headers).status_code, 429, i)
        r = self.client.get("/validatePatientCode", headers=headers)
        self.assertEqual(r.status_code, 429, "the count is shared by all patient endpoints")
        self.assertTrue(1 <= int(r.headers["Retry-After"]) <= 60)
        r = self.post("/sendDaily", BODIES["/sendDaily"], ip="198.51.100.20")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.db.inserts("daily_entries"), [], "refused before anything is written")
        # another address, and the endpoints that are not the patient's, are not touched
        self.assertNotEqual(self.client.get("/getNextQuestionnaire", headers={**headers, "X-Real-IP": "198.51.100.21"}).status_code, 429)
        self.assertEqual(self.client.get("/healthz", headers=headers).status_code, 200)


if __name__ == "__main__":
    unittest.main()
