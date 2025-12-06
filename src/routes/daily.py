"""
Daily questionnaire endpoints
"""
from uuid import UUID
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
from sqlalchemy import text

from src.models.schemas import DailyPayload
from src.database.connection import get_session, is_initialized
from src.utils.validators import validate_patient_code
from src.services.patient_service import PatientService

router = APIRouter()


@router.post("/sendDaily")
async def send_daily(payload: DailyPayload, x_patient_code: Optional[str] = Header(None)):
    """Save daily symptom entry"""
    patient_code = validate_patient_code(x_patient_code)
    
    if not is_initialized():
        raise HTTPException(status_code=503, detail="Database not configured")
    
    session_maker = get_session()
    if not session_maker:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        async with session_maker() as session:
            async with session.begin():
                # Get or create patient
                patient_id_str = await PatientService.get_or_create_patient(session, patient_code)
                # Convert string to UUID for proper type handling
                patient_id = UUID(patient_id_str)
                
                # Parse raw_data
                raw = payload.raw_data or {}
                stool_count = raw.get("stool_count", 0)
                pads_used = raw.get("pads_used", 0)
                urgency = raw.get("urgency", "No")
                night_stools = raw.get("night_stools", "No")
                leakage = raw.get("leakage", "None")
                if leakage not in ("None", "Liquid", "Solid"):
                    print(f"Warning: Invalid leakage value '{leakage}', defaulting to 'None'")
                    leakage = "None"
                incomplete_evacuation = raw.get("incomplete_evacuation", "No")
                bloating = raw.get("bloating", 0.0)
                impact_score = raw.get("impact_score", 0.0)
                activity_interfere = raw.get("activity_interfere", 0.0)
                
                # Parse food_consumption
                food = payload.food_consumption or {}
                food_vegetables_all = food.get("vegetables_all_types", 0)
                food_root_vegetables = food.get("root_vegetables", 0)
                food_whole_grains = food.get("whole_grains", 0)
                food_whole_grain_bread = food.get("whole_grain_bread", 0)
                food_nuts_and_seeds = food.get("nuts_and_seeds", 0)
                food_legumes = food.get("legumes", 0)
                food_fruits_with_skin = food.get("fruits_with_skin", 0)
                food_berries = food.get("berries_any", 0)
                food_soft_fruits_no_skin = food.get("soft_fruits_without_skin", 0)
                food_muesli_and_bran = food.get("muesli_and_bran_cereals", 0)
                
                # Parse drink_consumption
                drink = payload.drink_consumption or {}
                drink_water = drink.get("water", 0)
                drink_coffee = drink.get("coffee", 0)
                drink_tea = drink.get("tea", 0)
                drink_alcohol = drink.get("alcohol", 0)
                drink_carbonated = drink.get("carbonated_drinks", 0)
                drink_juices = drink.get("juices", 0)
                drink_dairy = drink.get("dairy_drinks", 0)
                drink_energy = drink.get("energy_drinks", 0)
                
                # Save daily entry
                result = await session.execute(
                    text("""
                        INSERT INTO daily_entries (
                            patient_id, entry_date, bristol_scale,
                            stool_count, pads_used, urgency, night_stools, leakage,
                            incomplete_evacuation, bloating, impact_score, activity_interfere,
                            food_vegetables_all, food_root_vegetables, food_whole_grains,
                            food_whole_grain_bread, food_nuts_and_seeds, food_legumes,
                            food_fruits_with_skin, food_berries, food_soft_fruits_no_skin,
                            food_muesli_and_bran,
                            drink_water, drink_coffee, drink_tea, drink_alcohol,
                            drink_carbonated, drink_juices, drink_dairy, drink_energy
                        ) VALUES (
                            :patient_id,
                            COALESCE(CAST(:entry_date AS DATE), CURRENT_DATE),
                            :bristol_scale,
                            :stool_count, :pads_used, :urgency, :night_stools, :leakage,
                            :incomplete_evacuation, :bloating, :impact_score, :activity_interfere,
                            :food_vegetables_all, :food_root_vegetables, :food_whole_grains,
                            :food_whole_grain_bread, :food_nuts_and_seeds, :food_legumes,
                            :food_fruits_with_skin, :food_berries, :food_soft_fruits_no_skin,
                            :food_muesli_and_bran,
                            :drink_water, :drink_coffee, :drink_tea, :drink_alcohol,
                            :drink_carbonated, :drink_juices, :drink_dairy, :drink_energy
                        )
                        ON CONFLICT (patient_id, entry_date) DO UPDATE SET
                            bristol_scale = EXCLUDED.bristol_scale,
                            stool_count = EXCLUDED.stool_count,
                            pads_used = EXCLUDED.pads_used,
                            urgency = EXCLUDED.urgency,
                            night_stools = EXCLUDED.night_stools,
                            leakage = EXCLUDED.leakage,
                            incomplete_evacuation = EXCLUDED.incomplete_evacuation,
                            bloating = EXCLUDED.bloating,
                            impact_score = EXCLUDED.impact_score,
                            activity_interfere = EXCLUDED.activity_interfere,
                            food_vegetables_all = EXCLUDED.food_vegetables_all,
                            food_root_vegetables = EXCLUDED.food_root_vegetables,
                            food_whole_grains = EXCLUDED.food_whole_grains,
                            food_whole_grain_bread = EXCLUDED.food_whole_grain_bread,
                            food_nuts_and_seeds = EXCLUDED.food_nuts_and_seeds,
                            food_legumes = EXCLUDED.food_legumes,
                            food_fruits_with_skin = EXCLUDED.food_fruits_with_skin,
                            food_berries = EXCLUDED.food_berries,
                            food_soft_fruits_no_skin = EXCLUDED.food_soft_fruits_no_skin,
                            food_muesli_and_bran = EXCLUDED.food_muesli_and_bran,
                            drink_water = EXCLUDED.drink_water,
                            drink_coffee = EXCLUDED.drink_coffee,
                            drink_tea = EXCLUDED.drink_tea,
                            drink_alcohol = EXCLUDED.drink_alcohol,
                            drink_carbonated = EXCLUDED.drink_carbonated,
                            drink_juices = EXCLUDED.drink_juices,
                            drink_dairy = EXCLUDED.drink_dairy,
                            drink_energy = EXCLUDED.drink_energy
                        RETURNING id
                    """).bindparams(
                        patient_id=patient_id,
                        entry_date=payload.entry_date,
                        bristol_scale=payload.bristol_scale,
                        stool_count=stool_count,
                        pads_used=pads_used,
                        urgency=urgency,
                        night_stools=night_stools,
                        leakage=leakage,
                        incomplete_evacuation=incomplete_evacuation,
                        bloating=bloating,
                        impact_score=impact_score,
                        activity_interfere=activity_interfere,
                        food_vegetables_all=food_vegetables_all,
                        food_root_vegetables=food_root_vegetables,
                        food_whole_grains=food_whole_grains,
                        food_whole_grain_bread=food_whole_grain_bread,
                        food_nuts_and_seeds=food_nuts_and_seeds,
                        food_legumes=food_legumes,
                        food_fruits_with_skin=food_fruits_with_skin,
                        food_berries=food_berries,
                        food_soft_fruits_no_skin=food_soft_fruits_no_skin,
                        food_muesli_and_bran=food_muesli_and_bran,
                        drink_water=drink_water,
                        drink_coffee=drink_coffee,
                        drink_tea=drink_tea,
                        drink_alcohol=drink_alcohol,
                        drink_carbonated=drink_carbonated,
                        drink_juices=drink_juices,
                        drink_dairy=drink_dairy,
                        drink_energy=drink_energy,
                    )
                )
                row = result.first()
        return {"status": "ok", "id": str(row[0])}
    except Exception as e:
        import traceback
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in sendDaily: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )

