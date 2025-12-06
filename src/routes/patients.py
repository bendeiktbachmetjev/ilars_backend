"""
Patient endpoints for doctor interface
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.database.connection import get_session, is_initialized
from src.database.queries import execute_with_retry
from src.utils.validators import validate_patient_code

router = APIRouter()


@router.get("/getPatients")
async def get_patients():
    """
    Get list of all patients for doctor interface.
    Returns patient codes and basic info (no PII).
    """
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        async with session_maker() as session:
            result = await execute_with_retry(
                session,
                text("""
                    SELECT 
                        p.patient_code,
                        p.created_at,
                        (SELECT COUNT(*) FROM weekly_entries WHERE patient_id = p.id) as weekly_count,
                        (SELECT COUNT(*) FROM daily_entries WHERE patient_id = p.id) as daily_count,
                        (SELECT COUNT(*) FROM monthly_entries WHERE patient_id = p.id) as monthly_count,
                        (SELECT total_score FROM weekly_entries WHERE patient_id = p.id AND total_score IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_lars_score,
                        (SELECT entry_date FROM weekly_entries WHERE patient_id = p.id AND total_score IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_lars_date,
                        (SELECT health_vas FROM eq5d5l_entries WHERE patient_id = p.id AND health_vas IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_eq5d5l_score,
                        (SELECT entry_date FROM eq5d5l_entries WHERE patient_id = p.id AND health_vas IS NOT NULL ORDER BY entry_date DESC LIMIT 1) as last_eq5d5l_date
                    FROM patients p
                    ORDER BY p.created_at DESC
                """)
            )
            
            if result is None:
                return JSONResponse(
                    status_code=503,
                    content={"status": "error", "detail": "Database connection pool exhausted, please try again"}
                )
            
            rows = result.fetchall()
            patients = []
            for row in rows:
                patients.append({
                    "patient_code": row[0],
                    "created_at": row[1].isoformat() if row[1] else None,
                    "weekly_count": row[2] or 0,
                    "daily_count": row[3] or 0,
                    "monthly_count": row[4] or 0,
                    "last_lars_score": row[5] if row[5] is not None else None,
                    "last_lars_date": row[6].isoformat() if row[6] else None,
                    "last_eq5d5l_score": row[7] if row[7] is not None else None,
                    "last_eq5d5l_date": row[8].isoformat() if row[8] else None,
                })
            
            return {"status": "ok", "patients": patients}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getPatients: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


@router.get("/getPatientDetail")
async def get_patient_detail(patient_code: str = Query(..., description="Patient code")):
    """
    Get detailed patient data for charts and graphs.
    Returns LARS scores, EQ-5D-5L scores, daily entries with food/drink consumption.
    """
    patient_code = validate_patient_code(patient_code)
    
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        async with session_maker() as session:
            # Get patient_id
            patient_res = await execute_with_retry(
                session,
                text("SELECT id, created_at FROM patients WHERE patient_code = :code").bindparams(code=patient_code)
            )
            if patient_res is None:
                return JSONResponse(
                    status_code=503,
                    content={"status": "error", "detail": "Database connection pool exhausted"}
                )
            
            patient_row = patient_res.first()
            if not patient_row:
                raise HTTPException(status_code=404, detail="Patient not found")
            
            patient_id = patient_row[0]
            created_at = patient_row[1]
            
            # Get LARS scores over time
            lars_res = await execute_with_retry(
                session,
                text("""
                    SELECT entry_date, total_score
                    FROM weekly_entries
                    WHERE patient_id = :pid AND total_score IS NOT NULL
                    ORDER BY entry_date ASC
                """).bindparams(pid=patient_id)
            )
            lars_data = []
            if lars_res:
                for row in lars_res.fetchall():
                    lars_data.append({
                        "date": row[0].isoformat() if row[0] else None,
                        "score": row[1]
                    })
            
            # Get EQ-5D-5L scores over time
            eq5d5l_res = await execute_with_retry(
                session,
                text("""
                    SELECT entry_date, health_vas
                    FROM eq5d5l_entries
                    WHERE patient_id = :pid AND health_vas IS NOT NULL
                    ORDER BY entry_date ASC
                """).bindparams(pid=patient_id)
            )
            eq5d5l_data = []
            if eq5d5l_res:
                for row in eq5d5l_res.fetchall():
                    eq5d5l_data.append({
                        "date": row[0].isoformat() if row[0] else None,
                        "score": row[1]
                    })
            
            # Get daily entries with food/drink consumption (last 30 days)
            daily_res = await execute_with_retry(
                session,
                text("""
                    SELECT 
                        entry_date,
                        food_vegetables_all, food_root_vegetables, food_whole_grains,
                        food_whole_grain_bread, food_nuts_and_seeds, food_legumes,
                        food_fruits_with_skin, food_berries, food_soft_fruits_no_skin, food_muesli_and_bran,
                        drink_water, drink_coffee, drink_tea, drink_alcohol,
                        drink_carbonated, drink_juices, drink_dairy, drink_energy,
                        bristol_scale, stool_count, bloating, impact_score
                    FROM daily_entries
                    WHERE patient_id = :pid
                        AND entry_date >= CURRENT_DATE - INTERVAL '30 days'
                    ORDER BY entry_date ASC
                """).bindparams(pid=patient_id)
            )
            daily_data = []
            if daily_res:
                for row in daily_res.fetchall():
                    daily_data.append({
                        "date": row[0].isoformat() if row[0] else None,
                        "food": {
                            "vegetables_all": row[1] or 0,
                            "root_vegetables": row[2] or 0,
                            "whole_grains": row[3] or 0,
                            "whole_grain_bread": row[4] or 0,
                            "nuts_and_seeds": row[5] or 0,
                            "legumes": row[6] or 0,
                            "fruits_with_skin": row[7] or 0,
                            "berries": row[8] or 0,
                            "soft_fruits_no_skin": row[9] or 0,
                            "muesli_and_bran": row[10] or 0,
                        },
                        "drink": {
                            "water": row[11] or 0,
                            "coffee": row[12] or 0,
                            "tea": row[13] or 0,
                            "alcohol": row[14] or 0,
                            "carbonated": row[15] or 0,
                            "juices": row[16] or 0,
                            "dairy": row[17] or 0,
                            "energy": row[18] or 0,
                        },
                        "bristol_scale": row[19],
                        "stool_count": row[20] or 0,
                        "bloating": float(row[21]) if row[21] else 0,
                        "impact_score": float(row[22]) if row[22] else 0,
                    })
            
            return {
                "status": "ok",
                "patient_code": patient_code,
                "created_at": created_at.isoformat() if created_at else None,
                "lars_scores": lars_data,
                "eq5d5l_scores": eq5d5l_data,
                "daily_entries": daily_data,
            }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getPatientDetail: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )

