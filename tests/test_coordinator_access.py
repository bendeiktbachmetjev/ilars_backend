"""
Access rules for study coordinators (doctors.is_coordinator, migration_coordinators.sql).

A coordinator may VIEW the patients of every Lithuanian hospital (hospital code starts with 'LT'):
list, detail, status history. Every such read outside their own hospital is logged in
patient_access_log before data is returned. A coordinator may CHANGE only their own hospital's
patients, exactly like any other doctor. Ordinary doctors are unchanged.

The real route functions run against a fake database session that answers by SQL pattern,
so these tests need FastAPI and SQLAlchemy (backend requirements) but no database.
Run from the backend folder:
    python3 -m unittest discover -s tests -v
"""
import inspect
import json
import re
import unittest
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from unittest import mock

try:
    from fastapi import HTTPException, params as fastapi_params
    from fastapi.responses import JSONResponse
    import src.routes.patients as patients_routes
except ImportError as exc:  # backend requirements not installed in this interpreter
    raise unittest.SkipTest(f"backend requirements missing: {exc}")

SANT, KAUN, MAYO = (uuid.UUID(f"aa000000-0000-4000-8000-00000000000{i}") for i in (1, 2, 3))
HOSPITALS = {SANT: ("LTSANT", "Santaros"), KAUN: ("LTKAUN", "Kauno klinikos"), MAYO: ("MAYO01", "Mayo Clinic")}
DOC_C, DOC_D, DOC_K = (uuid.UUID(f"dd000000-0000-4000-8000-00000000000{i}") for i in (1, 2, 3))
DOCTORS = {  # uid -> (doctor id, hospital id, is_coordinator)
    "uid-coord": (DOC_C, SANT, True),
    "uid-doc": (DOC_D, SANT, False),     # ordinary doctor, same hospital as the coordinator
    "uid-kaun": (DOC_K, KAUN, False),
}
PATIENTS = {
    "SANT0001": {"id": uuid.UUID("ee000000-0000-4000-8000-000000000001"), "hospital_id": SANT, "doctor_id": DOC_D},
    "KAUN0001": {"id": uuid.UUID("ee000000-0000-4000-8000-000000000002"), "hospital_id": KAUN, "doctor_id": DOC_K},
    "MAYO0001": {"id": uuid.UUID("ee000000-0000-4000-8000-000000000003"), "hospital_id": MAYO, "doctor_id": None},
}
for _p in PATIENTS.values():
    _p.update(created_at=datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc), status="active", status_reason=None)
HISTORY_ID = "11111111-0000-4000-8000-000000000001"
TODAY = date(2026, 10, 5)


class Row(tuple):
    """Minimal stand-in for sqlalchemy Row: positional access plus ._mapping by column name.
    Unknown names map to None, so columns appended by other branches do not break the fake."""

    def __new__(cls, names, values):
        row = super().__new__(cls, values)
        row._names = names
        return row

    @property
    def _mapping(self):
        return defaultdict(lambda: None, zip(self._names, self))


class Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def scalar(self):
        return self._rows[0][0] if self._rows else None


def columns(select_list):
    return [c.strip() for c in select_list.split(",")]


class FakeSession:
    """Answers the route's SQL by pattern and records every statement and access-log row."""

    def __init__(self, uid, fail_log=False):
        self.doctor_id, self.hospital_id, self.is_coordinator = DOCTORS[uid]
        self.fail_log = fail_log
        self.statements = []
        self.log = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        self.commits += 1

    def writes(self):
        return [s for s in self.statements if re.match(r"\s*(INSERT|UPDATE|DELETE)\b", s)]

    def data_writes(self):
        return [s for s in self.writes() if "patient_access_log" not in s]

    async def execute(self, clause):
        sql = clause.text
        params = {k: bp.value for k, bp in clause._bindparams.items()}
        if "set_config" in sql:
            return Result()
        self.statements.append(sql)
        if "INSERT INTO patient_access_log" in sql:
            if self.fail_log:
                raise RuntimeError("access log unavailable")
            self.log.append((params["doctor_id"], params["patient_id"], params["action"]))
            return Result()
        if re.match(r"\s*(INSERT|UPDATE|DELETE)\b", sql):
            return Result()
        m = re.search(r"SELECT (.+?) FROM doctors WHERE firebase_uid", sql)
        if m:
            known = {"id": self.doctor_id, "hospital_id": self.hospital_id, "CURRENT_DATE": TODAY,
                     "is_coordinator": self.is_coordinator}
            names = columns(m.group(1))
            return Result([Row(names, [known[n] for n in names])])
        if "FROM hospitals WHERE id" in sql:
            hospital = HOSPITALS.get(uuid.UUID(str(params["hid"])))
            return Result([Row(["code"], [hospital[0]])] if hospital else [])
        m = re.search(r"SELECT (.+?) FROM patients WHERE patient_code = :(\w+)", sql)
        if m:
            patient = PATIENTS.get(params[m.group(2)])
            names = columns(m.group(1))
            return Result([Row(names, [dict(patient, CURRENT_DATE=TODAY)[n] for n in names])] if patient else [])
        if "FROM patients p" in sql and "LEFT JOIN doctors d" in sql:   # /getPatients list
            lt_too = "OR h.code LIKE 'LT%'" in sql
            rows = []
            for code, p in PATIENTS.items():
                hcode, hname = HOSPITALS[p["hospital_id"]]
                if not (str(p["doctor_id"]) == params["doctor_id"] or str(p["hospital_id"]) == params["hospital_id"]
                        or (lt_too and hcode.startswith("LT"))):
                    continue
                names = [f"c{i}" for i in range(17)] + ["hospital_name"]
                rows.append(Row(names, [code, p["created_at"], p["doctor_id"], p["hospital_id"], "active", None,
                                        "DR", hcode, "Ada", "One", 0, 0, 0, None, None, None, None, hname]))
            return Result(rows)
        if "FROM patient_status_history h" in sql:                      # deletePatientStatusChange lookup
            p = PATIENTS["KAUN0001"]
            return Result([Row(["id", "patient_id", "previous_status", "changed_at", "hospital_id", "patient_code"],
                               [uuid.UUID(HISTORY_ID), p["id"], "active", p["created_at"], p["hospital_id"],
                                "KAUN0001"])])
        return Result()


def route_kwargs(fn, **kwargs):
    """Kwargs for calling a route function directly: optional Query/Header params not given get None."""
    for name, param in inspect.signature(fn).parameters.items():
        if name not in kwargs and isinstance(param.default, fastapi_params.Param):
            kwargs[name] = None
    return kwargs


class CoordinatorAccessTests(unittest.IsolatedAsyncioTestCase):
    def session_for(self, uid, fail_log=False):
        session = FakeSession(uid, fail_log)
        for name, value in (("get_session", lambda: (lambda: session)), ("is_initialized", lambda: True)):
            patcher = mock.patch.object(patients_routes, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return session

    async def get_list(self, uid):
        return await patients_routes.get_patients(**route_kwargs(patients_routes.get_patients, status="all",
                                                                  claims={"uid": uid}))

    # ---------- list

    async def test_coordinator_list_has_every_lithuanian_hospital_and_is_logged(self):
        session = self.session_for("uid-coord")
        res = await self.get_list("uid-coord")
        sql = next(s for s in session.statements if "FROM patients p" in s)
        self.assertIn("OR p.hospital_id = CAST(:hospital_id AS uuid) OR h.code LIKE 'LT%')", sql)
        self.assertEqual(sorted(p["patient_code"] for p in res["patients"]), ["KAUN0001", "SANT0001"])  # no Mayo
        self.assertEqual(session.log, [(str(DOC_C), None, "list")])

    async def test_ordinary_doctor_list_unchanged_and_not_logged(self):
        session = self.session_for("uid-doc")
        res = await self.get_list("uid-doc")
        sql = next(s for s in session.statements if "FROM patients p" in s)
        self.assertNotIn("h.code LIKE", sql)
        self.assertEqual([p["patient_code"] for p in res["patients"]], ["SANT0001"])
        self.assertEqual(session.log, [])
        self.assertEqual(session.writes(), [])

    async def test_list_rows_say_who_may_edit_and_hide_other_join_codes(self):
        self.session_for("uid-coord")
        res = await self.get_list("uid-coord")
        rows = {p["patient_code"]: p for p in res["patients"]}
        own, other = rows["SANT0001"], rows["KAUN0001"]
        self.assertEqual((own["can_edit"], own["hospital_code"], own["hospital_name"]), (True, "LTSANT", "Santaros"))
        self.assertEqual((other["can_edit"], other["hospital_code"], other["hospital_name"]),
                         (False, None, "Kauno klinikos"))
        self.assertNotIn("LTKAUN", json.dumps(res, default=str))   # another hospital's join code: nowhere

    async def test_list_is_not_returned_when_the_log_fails(self):
        self.session_for("uid-coord", fail_log=True)
        res = await self.get_list("uid-coord")
        self.assertIsInstance(res, JSONResponse)
        self.assertEqual(res.status_code, 500)
        self.assertNotIn(b"KAUN0001", res.body)

    # ---------- detail and status history

    async def test_coordinator_reads_other_lithuanian_hospital_read_only_and_logged(self):
        session = self.session_for("uid-coord")
        res = await patients_routes.get_patient_detail(patient_code="KAUN0001", claims={"uid": "uid-coord"})
        self.assertEqual(res["status"], "ok")
        self.assertIs(res["can_edit"], False)
        self.assertEqual(session.log, [(str(DOC_C), PATIENTS["KAUN0001"]["id"], "detail")])
        first_data = next(i for i, s in enumerate(session.statements) if "weekly_entries" in s)
        log_at = next(i for i, s in enumerate(session.statements) if "patient_access_log" in s)
        self.assertLess(log_at, first_data)   # logged before any data is read

    async def test_coordinator_own_hospital_is_editable_and_not_logged(self):
        session = self.session_for("uid-coord")
        res = await patients_routes.get_patient_detail(patient_code="SANT0001", claims={"uid": "uid-coord"})
        self.assertIs(res["can_edit"], True)
        self.assertEqual(session.log, [])

    async def test_coordinator_cannot_read_a_foreign_hospital(self):
        session = self.session_for("uid-coord")
        for read in (patients_routes.get_patient_detail, patients_routes.get_patient_status_history):
            with self.subTest(read=read.__name__), self.assertRaises(HTTPException) as ctx:
                await read(patient_code="MAYO0001", claims={"uid": "uid-coord"})
            self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(session.log, [])
        self.assertFalse(any("weekly_entries" in s for s in session.statements))

    async def test_ordinary_doctor_still_cannot_read_another_hospital(self):
        session = self.session_for("uid-doc")
        for read in (patients_routes.get_patient_detail, patients_routes.get_patient_status_history):
            with self.subTest(read=read.__name__), self.assertRaises(HTTPException) as ctx:
                await read(patient_code="KAUN0001", claims={"uid": "uid-doc"})
            self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(session.writes(), [])

    async def test_detail_is_not_returned_when_the_log_fails(self):
        session = self.session_for("uid-coord", fail_log=True)
        res = await patients_routes.get_patient_detail(patient_code="KAUN0001", claims={"uid": "uid-coord"})
        self.assertIsInstance(res, JSONResponse)
        self.assertEqual(res.status_code, 500)
        self.assertFalse(any("weekly_entries" in s for s in session.statements))

    async def test_coordinator_status_history_of_other_hospital_is_logged(self):
        session = self.session_for("uid-coord")
        res = await patients_routes.get_patient_status_history(patient_code="KAUN0001", claims={"uid": "uid-coord"})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(session.log, [(str(DOC_C), PATIENTS["KAUN0001"]["id"], "status_history")])

    # ---------- writes: a coordinator changes nothing outside their own hospital

    async def test_coordinator_cannot_change_status_in_another_hospital(self):
        session = self.session_for("uid-coord")
        body = patients_routes.UpdatePatientStatusBody(patient_code="KAUN0001", status="inactive")
        with self.assertRaises(HTTPException) as ctx:
            await patients_routes.update_patient_status(body=body, claims={"uid": "uid-coord"})
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(session.writes(), [])

    async def test_coordinator_cannot_delete_a_status_change_in_another_hospital(self):
        session = self.session_for("uid-coord")
        body = patients_routes.DeletePatientStatusChangeBody(history_id=HISTORY_ID)
        with self.assertRaises(HTTPException) as ctx:
            await patients_routes.delete_patient_status_change(body=body, claims={"uid": "uid-coord"})
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(session.writes(), [])

    async def test_coordinator_can_still_change_own_hospital(self):
        session = self.session_for("uid-coord")
        body = patients_routes.UpdatePatientStatusBody(patient_code="SANT0001", status="inactive")
        res = await patients_routes.update_patient_status(body=body, claims={"uid": "uid-coord"})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(session.data_writes()), 2)   # history row + patients update
        self.assertEqual(session.log, [])


if __name__ == "__main__":
    unittest.main()
