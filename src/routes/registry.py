"""
Registry endpoints — Lithuanian colorectal cancer registry.

Only available to Lithuanian doctors (their hospital code starts with 'LT').
Names/PII are NOT stored here (they live in Firebase); this table holds only
pseudonymized identifiers (lin, personal_id_code) and clinical variables.

Access model:
  - READ is national: any Lithuanian doctor can read all registry records of
    Lithuanian hospitals (RLS select policy + WHERE h.code LIKE 'LT%').
  - WRITE is owner-only: only the doctor who created a record can edit it
    (RLS insert/update/delete policy on doctor_id = app.doctor_id).
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Depends, Body
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry
from src.database.rls_context import set_db_context
from src.routes.doctors import get_current_user
from src.utils.validators import validate_patient_code

router = APIRouter()


# ---------------------------------------------------------------------------
# Field metadata: which columns the doctor may edit, and their SQL cast type.
# The form sends every value as a string; we CAST per-column so asyncpg does not
# choke on type mismatches and empty strings become NULL.
# ---------------------------------------------------------------------------
DATE_FIELDS = {
    "birth_date", "diagnosis_date", "index_operation_date", "mri_date",
    "nct_start_date", "nct_end_date", "nrt_start_date", "nrt_end_date",
    "operation_date", "ileostomy_closure_date", "act_start_date", "act_end_date",
    "recurrence_date", "last_contact_date", "death_date",
}
NUM_FIELDS = {
    "weight_kg", "bmi", "cea_pre_treatment", "tumor_distance_anus_cm",
    "tumor_distance_arj_cm", "nrt_dose_gy", "proximal_margin_cm",
    "distal_margin_cm", "specimen_length_cm", "cea_post_op", "art_dose_gy",
}
TEXT_FIELDS = {
    "lin", "personal_id_code", "ct", "cn", "cm", "clinical_stage", "nct_scheme",
    "operation_type", "anastomosis_type", "clavien_dindo", "complications_icd10",
    "pt", "pn", "pm", "ptnm_stage", "histology_type", "histology_grade",
    "resection_margin", "kras_status", "kras_mutation", "nras_status",
    "braf_status", "mmr_msi_status", "mlh1", "msh2", "msh6", "pms2", "her2",
    "act_scheme", "mts_location", "notes",
}
INT_FIELDS = {
    "sex", "age_at_diagnosis", "height_cm", "asa_score", "ecog",
    "family_crc_history", "diabetes", "cardiovascular_disease",
    "glucocorticoid_use", "prehabilitation", "emvi", "mrf", "sphincter_invasion",
    "circumferential", "mesorectal_ln_mri", "nct", "nct_cycles",
    "new_mts_after_neoadj", "mrtrg", "operation_approach", "conversion",
    "operation_duration_min", "blood_loss_ml", "tme_quality", "ileostomy",
    "complications", "anastomotic_leak", "reoperation_30d", "rehospitalization_30d",
    "hospital_stay_days", "death_30d", "ln_removed", "ln_positive", "lvi", "pni",
    "dworak_trg", "mts_development", "local_recurrence", "vital_status",
    "cancer_related_death", "lars_baseline", "lars_0m", "lars_3m", "lars_6m",
    "lars_12m", "lars_category_12m", "wexner_0m", "wexner_12m",
}
EDITABLE_FIELDS = DATE_FIELDS | NUM_FIELDS | TEXT_FIELDS | INT_FIELDS


def _cast_sql(col: str) -> str:
    """Return 'col = CAST(:col AS <type>)' for a known column."""
    if col in DATE_FIELDS:
        pgtype = "date"
    elif col in NUM_FIELDS:
        pgtype = "numeric"
    elif col in TEXT_FIELDS:
        pgtype = "text"
    else:
        pgtype = "smallint"
    return f"{col} = CAST(:{col} AS {pgtype})"


def _json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _row_to_dict(mapping) -> dict:
    return {k: _json_safe(v) for k, v in dict(mapping).items()}


async def get_lithuanian_doctor(claims: dict = Depends(get_current_user)) -> dict:
    """Resolve the current doctor and ensure they belong to a Lithuanian hospital."""
    uid = claims.get("uid") or claims.get("sub", "")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token")
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")

    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")

    async with session_maker() as session:
        res = await execute_with_retry(
            session,
            text("""
                SELECT d.id, d.hospital_id, h.code
                FROM doctors d
                JOIN hospitals h ON d.hospital_id = h.id
                WHERE d.firebase_uid = :uid
            """).bindparams(uid=uid)
        )
        row = res.first() if res else None
        if not row or not row[2] or not str(row[2]).startswith("LT"):
            raise HTTPException(status_code=403, detail="Registry available only for Lithuanian hospitals")
        return {"doctor_id": str(row[0]), "hospital_id": str(row[1])}


_SELECT_COLS = """
    rp.*,
    d.first_name AS owner_first_name,
    d.last_name AS owner_last_name,
    d.doctor_code AS owner_doctor_code,
    sp.patient_code AS study_patient_code
"""


@router.get("/getRegistryPatients")
async def get_registry_patients(doctor: dict = Depends(get_lithuanian_doctor)):
    """List all registry records of Lithuanian hospitals (national). Names come from Firebase."""
    session_maker = get_session()
    try:
        async with session_maker() as session:
            async with set_db_context(session, role='doctor', doctor_id=doctor["doctor_id"], hospital_id=doctor["hospital_id"]):
                res = await execute_with_retry(
                    session,
                    text(f"""
                        SELECT {_SELECT_COLS}
                        FROM registry_patients rp
                        JOIN hospitals h ON rp.hospital_id = h.id
                        LEFT JOIN doctors d ON rp.doctor_id = d.id
                        LEFT JOIN patients sp ON rp.study_patient_id = sp.id
                        WHERE h.code LIKE 'LT%'
                        ORDER BY
                            CASE WHEN rp.doctor_id = CAST(:did AS uuid) THEN 0 ELSE 1 END,
                            rp.updated_at DESC
                    """).bindparams(did=doctor["doctor_id"])
                )
            rows = res.mappings().all() if res else []
            patients = []
            for m in rows:
                d = _row_to_dict(m)
                d["is_mine"] = str(m["doctor_id"]) == doctor["doctor_id"]
                patients.append(d)
            return {"status": "ok", "patients": patients}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in getRegistryPatients: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@router.get("/getRegistryPatientDetail")
async def get_registry_patient_detail(id: str = Query(...), doctor: dict = Depends(get_lithuanian_doctor)):
    """Return a single registry record (full row)."""
    session_maker = get_session()
    try:
        async with session_maker() as session:
            async with set_db_context(session, role='doctor', doctor_id=doctor["doctor_id"], hospital_id=doctor["hospital_id"]):
                res = await execute_with_retry(
                    session,
                    text(f"""
                        SELECT {_SELECT_COLS}
                        FROM registry_patients rp
                        JOIN hospitals h ON rp.hospital_id = h.id
                        LEFT JOIN doctors d ON rp.doctor_id = d.id
                        LEFT JOIN patients sp ON rp.study_patient_id = sp.id
                        WHERE rp.id = CAST(:rid AS uuid) AND h.code LIKE 'LT%'
                    """).bindparams(rid=id)
                )
            m = res.mappings().first() if res else None
            if not m:
                raise HTTPException(status_code=404, detail="Registry record not found")
            d = _row_to_dict(m)
            d["is_mine"] = str(m["doctor_id"]) == doctor["doctor_id"]
            return {"status": "ok", "patient": d}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in getRegistryPatientDetail: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@router.post("/createRegistryPatient")
async def create_registry_patient(doctor: dict = Depends(get_lithuanian_doctor)):
    """Create an empty registry record owned by the current doctor; return its id."""
    session_maker = get_session()
    try:
        async with session_maker() as session:
            async with set_db_context(session, role='doctor', doctor_id=doctor["doctor_id"], hospital_id=doctor["hospital_id"]):
                res = await execute_with_retry(
                    session,
                    text("""
                        INSERT INTO registry_patients (doctor_id, hospital_id)
                        VALUES (CAST(:did AS uuid), CAST(:hid AS uuid))
                        RETURNING id, created_at
                    """).bindparams(did=doctor["doctor_id"], hid=doctor["hospital_id"])
                )
                await session.commit()
            row = res.first() if res else None
            if not row:
                raise HTTPException(status_code=500, detail="Failed to create registry record")
            return {"status": "ok", "id": str(row[0]), "created_at": row[1].isoformat() if row[1] else None}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in createRegistryPatient: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@router.post("/updateRegistryPatient")
async def update_registry_patient(body: dict = Body(...), doctor: dict = Depends(get_lithuanian_doctor)):
    """Update editable fields of a registry record. RLS restricts writes to the owner."""
    rid = body.get("id")
    data = body.get("data") or {}
    if not rid:
        raise HTTPException(status_code=400, detail="Missing registry record id")

    # Whitelist columns; convert empty strings to NULL.
    updates = {}
    for k, v in data.items():
        if k in EDITABLE_FIELDS:
            updates[k] = None if (isinstance(v, str) and v.strip() == "") else v

    if not updates:
        return {"status": "ok", "detail": "No changes"}

    set_clause = ", ".join(_cast_sql(k) for k in updates) + ", updated_at = now()"
    params = dict(updates)
    params["rid"] = rid
    params["did"] = doctor["doctor_id"]

    session_maker = get_session()
    try:
        async with session_maker() as session:
            async with set_db_context(session, role='doctor', doctor_id=doctor["doctor_id"], hospital_id=doctor["hospital_id"]):
                # Owner-only write enforced explicitly (defense-in-depth alongside RLS).
                res = await execute_with_retry(
                    session,
                    text(f"""
                        UPDATE registry_patients
                        SET {set_clause}
                        WHERE id = CAST(:rid AS uuid) AND doctor_id = CAST(:did AS uuid)
                        RETURNING id
                    """).bindparams(**params)
                )
                await session.commit()
            if not (res and res.first()):
                # RLS blocked it (not owner) or record missing.
                raise HTTPException(status_code=403, detail="Not found or not your record")
            return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in updateRegistryPatient: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@router.post("/deleteRegistryPatient")
async def delete_registry_patient(body: dict = Body(...), doctor: dict = Depends(get_lithuanian_doctor)):
    """Delete a registry record. Owner-only (explicit doctor_id filter + RLS)."""
    rid = body.get("id")
    if not rid:
        raise HTTPException(status_code=400, detail="Missing registry record id")

    session_maker = get_session()
    try:
        async with session_maker() as session:
            async with set_db_context(session, role='doctor', doctor_id=doctor["doctor_id"], hospital_id=doctor["hospital_id"]):
                res = await execute_with_retry(
                    session,
                    text("""
                        DELETE FROM registry_patients
                        WHERE id = CAST(:rid AS uuid) AND doctor_id = CAST(:did AS uuid)
                        RETURNING id
                    """).bindparams(rid=rid, did=doctor["doctor_id"])
                )
                await session.commit()
            if not (res and res.first()):
                raise HTTPException(status_code=403, detail="Not found or not your record")
            return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in deleteRegistryPatient: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@router.post("/linkRegistryToStudy")
async def link_registry_to_study(body: dict = Body(...), doctor: dict = Depends(get_lithuanian_doctor)):
    """Link a registry record (owned by the doctor) to a study patient in the doctor's hospital."""
    registry_id = body.get("registry_id")
    patient_code = validate_patient_code(body.get("patient_code"))
    if not registry_id:
        raise HTTPException(status_code=400, detail="Missing registry_id")

    session_maker = get_session()
    try:
        async with session_maker() as session:
            # Find the study patient and verify it belongs to the doctor's hospital.
            async with set_db_context(session, role='doctor', doctor_id=doctor["doctor_id"], hospital_id=doctor["hospital_id"]):
                pres = await execute_with_retry(
                    session,
                    text("SELECT id, hospital_id FROM patients WHERE patient_code = :c").bindparams(c=patient_code)
                )
            prow = pres.first() if pres else None
            if not prow:
                raise HTTPException(status_code=404, detail="Study patient not found")
            if str(prow[1]) != doctor["hospital_id"]:
                raise HTTPException(status_code=403, detail="Study patient is not in your hospital")
            study_id = str(prow[0])

            try:
                async with set_db_context(session, role='doctor', doctor_id=doctor["doctor_id"], hospital_id=doctor["hospital_id"]):
                    ures = await execute_with_retry(
                        session,
                        text("""
                            UPDATE registry_patients
                            SET study_patient_id = CAST(:sid AS uuid), updated_at = now()
                            WHERE id = CAST(:rid AS uuid) AND doctor_id = CAST(:did AS uuid)
                            RETURNING id
                        """).bindparams(sid=study_id, rid=registry_id, did=doctor["doctor_id"])
                    )
                    await session.commit()
            except Exception as e:
                msg = str(e).lower()
                if "unique" in msg or "duplicate" in msg:
                    raise HTTPException(status_code=409, detail="This study patient is already linked to another registry record")
                raise

            if not (ures and ures.first()):
                raise HTTPException(status_code=403, detail="Not found or not your registry record")
            return {"status": "ok", "patient_code": patient_code}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in linkRegistryToStudy: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@router.post("/unlinkRegistryFromStudy")
async def unlink_registry_from_study(body: dict = Body(...), doctor: dict = Depends(get_lithuanian_doctor)):
    """Remove the study link from a registry record (owner only)."""
    registry_id = body.get("registry_id")
    if not registry_id:
        raise HTTPException(status_code=400, detail="Missing registry_id")

    session_maker = get_session()
    try:
        async with session_maker() as session:
            async with set_db_context(session, role='doctor', doctor_id=doctor["doctor_id"], hospital_id=doctor["hospital_id"]):
                res = await execute_with_retry(
                    session,
                    text("""
                        UPDATE registry_patients
                        SET study_patient_id = NULL, updated_at = now()
                        WHERE id = CAST(:rid AS uuid) AND doctor_id = CAST(:did AS uuid)
                        RETURNING id
                    """).bindparams(rid=registry_id, did=doctor["doctor_id"])
                )
                await session.commit()
            if not (res and res.first()):
                raise HTTPException(status_code=403, detail="Not found or not your registry record")
            return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in unlinkRegistryFromStudy: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@router.get("/getLinkableStudyPatients")
async def get_linkable_study_patients(doctor: dict = Depends(get_lithuanian_doctor)):
    """Study patients in the doctor's hospital not yet linked to any registry record."""
    session_maker = get_session()
    try:
        async with session_maker() as session:
            async with set_db_context(session, role='doctor', doctor_id=doctor["doctor_id"], hospital_id=doctor["hospital_id"]):
                res = await execute_with_retry(
                    session,
                    text("""
                        SELECT p.patient_code, p.created_at, p.doctor_id
                        FROM patients p
                        WHERE p.hospital_id = CAST(:hid AS uuid)
                          AND p.id NOT IN (
                              SELECT study_patient_id FROM registry_patients WHERE study_patient_id IS NOT NULL
                          )
                        ORDER BY
                            CASE WHEN p.doctor_id = CAST(:did AS uuid) THEN 0 ELSE 1 END,
                            p.created_at DESC
                    """).bindparams(hid=doctor["hospital_id"], did=doctor["doctor_id"])
                )
            rows = res.fetchall() if res else []
            patients = [{
                "patient_code": r[0],
                "created_at": r[1].isoformat() if r[1] else None,
                "is_mine": str(r[2]) == doctor["doctor_id"],
            } for r in rows]
            return {"status": "ok", "patients": patients}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in getLinkableStudyPatients: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@router.get("/getLinkableRegistryPatients")
async def get_linkable_registry_patients(doctor: dict = Depends(get_lithuanian_doctor)):
    """Registry records owned by the doctor that are not yet linked to a study patient."""
    session_maker = get_session()
    try:
        async with session_maker() as session:
            async with set_db_context(session, role='doctor', doctor_id=doctor["doctor_id"], hospital_id=doctor["hospital_id"]):
                res = await execute_with_retry(
                    session,
                    text("""
                        SELECT id, lin, personal_id_code
                        FROM registry_patients
                        WHERE doctor_id = CAST(:did AS uuid) AND study_patient_id IS NULL
                        ORDER BY updated_at DESC
                    """).bindparams(did=doctor["doctor_id"])
                )
            rows = res.fetchall() if res else []
            records = [{
                "id": str(r[0]),
                "lin": r[1],
                "personal_id_code": r[2],
            } for r in rows]
            return {"status": "ok", "records": records}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"Error in getLinkableRegistryPatients: {type(e).__name__}: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})
