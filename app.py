import os
import json
import traceback
import asyncio
from typing import Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


# Pydantic модели - точно как отправляет frontend
class WeeklyPayload(BaseModel):
    flatus_control: int
    liquid_stool_leakage: int
    bowel_frequency: int
    repeat_bowel_opening: int
    urgency_to_toilet: int
    entry_date: Optional[str] = None
    raw_data: Optional[dict] = None

class DailyPayload(BaseModel):
    entry_date: Optional[str] = None
    bristol_scale: Optional[int] = None
    food_consumption: Optional[dict] = None  # Map<String, int> - будет распарсено в отдельные колонки
    drink_consumption: Optional[dict] = None  # Map<String, int> - будет распарсено в отдельные колонки
    raw_data: Optional[dict] = None  # Содержит: stool_count, pads_used, urgency, night_stools, leakage, incomplete_evacuation, bloating, impact_score, activity_interfere

class MonthlyPayload(BaseModel):
    entry_date: Optional[str] = None
    qol_score: Optional[int] = None
    raw_data: Optional[dict] = None  # Содержит: avoid_travel, avoid_social, embarrassed, worry_notice, depressed, control, satisfaction

class Eq5d5lPayload(BaseModel):
    mobility: int
    self_care: int
    usual_activities: int
    pain_discomfort: int
    anxiety_depression: int
    health_vas: Optional[int] = None  # 0..100 Visual Analogue Scale for health today
    entry_date: Optional[str] = None
    raw_data: Optional[dict] = None


app = FastAPI()

# CORS middleware for web interface
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for doctor interface
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_async_url(sync_url: str) -> str:
    """Конвертирует postgres:// в postgresql+asyncpg:// и убирает sslmode из URL"""
    if not sync_url:
        return sync_url
    parts = urlsplit(sync_url)
    scheme = parts.scheme
    
    if "+" in scheme:
        base_scheme = scheme.split("+")[0]
    else:
        base_scheme = scheme
    
    if base_scheme.startswith("postgres"):
        # Убираем sslmode из query параметров (asyncpg не поддерживает в URL)
        from urllib.parse import parse_qsl, urlencode
        query_pairs = dict(parse_qsl(parts.query, keep_blank_values=True))
        query_pairs.pop("sslmode", None)
        new_query = urlencode(query_pairs) if query_pairs else ""
        
        new_scheme = "postgresql+asyncpg"
        new_parts = (new_scheme, parts.netloc, parts.path, new_query, parts.fragment)
        from urllib.parse import urlunsplit
        return urlunsplit(new_parts)
    return sync_url


# Инициализация базы данных
DATABASE_URL = os.getenv("DATABASE_URL", "")
engine: AsyncEngine = None
async_session = None

if DATABASE_URL:
    try:
        # ПРОСТОЕ РЕШЕНИЕ: автоматически переключаемся на Session Pooler (порт 5432)
        # Transaction Pooler (порт 6543) не поддерживает prepared statements
        # Заменяем :6543 на :5432 если используется pooler
        if ":6543" in DATABASE_URL:
            DATABASE_URL = DATABASE_URL.replace(":6543", ":5432")
            print("Switched from Transaction Pooler (6543) to Session Pooler (5432) for prepared statements support")
        elif ".pooler.supabase.com" in DATABASE_URL and ":5432" not in DATABASE_URL:
            # Если pooler, но порт не указан явно - добавляем 5432
            DATABASE_URL = DATABASE_URL.replace(".pooler.supabase.com", ".pooler.supabase.com:5432")
            print("Added Session Pooler port (5432) for prepared statements support")
        
        ASYNC_DATABASE_URL = _build_async_url(DATABASE_URL)
        ssl_required = "sslmode=require" in DATABASE_URL.lower() or os.getenv("SUPABASE_SSLMODE") == "require"
        
        # Optimized connection args for reliability
        connect_args = {
            "server_settings": {
                "application_name": "lars_backend",
                "tcp_keepalives_idle": "600",
                "tcp_keepalives_interval": "30",
                "tcp_keepalives_count": "3",
            },
            "command_timeout": 60,  # Timeout for SQL commands (60 seconds - longer for complex queries)
            "timeout": 20,  # Connection timeout (20 seconds - enough for Supabase pooler)
        }
        if ssl_required:
            # Minimal SSL config - just require SSL, don't verify cert (faster)
            # Supabase pooler doesn't need cert verification
            connect_args["ssl"] = True  # Simple SSL requirement
        
        # Optimized pool settings for reliability with multiple concurrent users
        engine = create_async_engine(
            ASYNC_DATABASE_URL,
            pool_pre_ping=True,  # Enable pre-ping to detect dead connections
            pool_size=10,  # Increased pool size for concurrent requests
            max_overflow=20,  # Allow more overflow for peak loads
            pool_recycle=3600,  # Recycle every hour (Supabase connections are stable)
            pool_timeout=30,  # Longer timeout to wait for available connection
            connect_args=connect_args,
            max_identifier_length=128,
            echo=False,
            pool_reset_on_return="commit",  # Faster connection return
        )
        
        async_session = sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
        print("Database engine initialized successfully")
    except Exception as e:
        print(f"Warning: Failed to initialize database engine: {e}")
        traceback.print_exc()


@app.get("/healthz")
async def healthcheck():
    db_status = "ok" if engine else "not_configured"
    return {"status": "ok", "database": db_status}


@app.post("/sendWeekly")
async def send_weekly(payload: WeeklyPayload, x_patient_code: Optional[str] = Header(None)):
    if not x_patient_code:
        raise HTTPException(status_code=400, detail="Missing X-Patient-Code header")
    patient_code = x_patient_code.strip().upper()
    if not patient_code or len(patient_code) < 4 or len(patient_code) > 64:
        raise HTTPException(status_code=400, detail="Invalid patient code format")

    if not async_session:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        async with async_session() as session:
            async with session.begin():
                # Создать или получить patient_id
                res = await session.execute(
                    text("""
                        INSERT INTO patients (patient_code)
                        VALUES (:code)
                        ON CONFLICT (patient_code) DO UPDATE SET patient_code = EXCLUDED.patient_code
                        RETURNING id
                    """).bindparams(code=patient_code)
                )
                patient_id = res.first()[0]

                # Сохранить weekly entry
                # Вычисляем total_score из raw_data если есть
                total_score = None
                if payload.raw_data and "total_score" in payload.raw_data:
                    total_score = payload.raw_data["total_score"]
                
                res2 = await session.execute(
                    text("""
                        INSERT INTO weekly_entries (
                            patient_id, entry_date,
                            flatus_control, liquid_stool_leakage, bowel_frequency,
                            repeat_bowel_opening, urgency_to_toilet, total_score
                        ) VALUES (
                            :patient_id,
                            COALESCE(CAST(:entry_date AS DATE), CURRENT_DATE),
                            :flatus_control, :liquid_stool_leakage, :bowel_frequency,
                            :repeat_bowel_opening, :urgency_to_toilet, :total_score
                        )
                        ON CONFLICT (patient_id, entry_date) DO UPDATE SET
                            flatus_control = EXCLUDED.flatus_control,
                            liquid_stool_leakage = EXCLUDED.liquid_stool_leakage,
                            bowel_frequency = EXCLUDED.bowel_frequency,
                            repeat_bowel_opening = EXCLUDED.repeat_bowel_opening,
                            urgency_to_toilet = EXCLUDED.urgency_to_toilet,
                            total_score = EXCLUDED.total_score
                        RETURNING id
                    """)
                    .bindparams(
                        patient_id=patient_id,
                        entry_date=payload.entry_date,
                        flatus_control=payload.flatus_control,
                        liquid_stool_leakage=payload.liquid_stool_leakage,
                        bowel_frequency=payload.bowel_frequency,
                        repeat_bowel_opening=payload.repeat_bowel_opening,
                        urgency_to_toilet=payload.urgency_to_toilet,
                        total_score=total_score,
                    )
                )
                row2 = res2.first()
        return {"status": "ok", "id": str(row2[0])}
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in sendWeekly: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500, 
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


@app.post("/sendDaily")
async def send_daily(payload: DailyPayload, x_patient_code: Optional[str] = Header(None)):
    if not x_patient_code:
        raise HTTPException(status_code=400, detail="Missing X-Patient-Code header")
    patient_code = x_patient_code.strip().upper()
    if not patient_code or len(patient_code) < 4 or len(patient_code) > 64:
        raise HTTPException(status_code=400, detail="Invalid patient code format")

    if not async_session:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        async with async_session() as session:
            async with session.begin():
                res = await session.execute(
                    text("""
                        INSERT INTO patients (patient_code)
                        VALUES (:code)
                        ON CONFLICT (patient_code) DO UPDATE SET patient_code = EXCLUDED.patient_code
                        RETURNING id
                    """).bindparams(code=patient_code)
                )
                patient_id = res.first()[0]

                # Парсим raw_data в отдельные поля
                # Frontend sends: stool_count, pads_used, urgency ('Yes'/'No'), 
                # night_stools ('Yes'/'No'), leakage ('None'/'Liquid'/'Solid'),
                # incomplete_evacuation ('Yes'/'No'), bloating (double), 
                # impact_score (double), activity_interfere (double)
                raw = payload.raw_data or {}
                stool_count = raw.get("stool_count", 0)
                pads_used = raw.get("pads_used", 0)
                urgency = raw.get("urgency", "No")
                night_stools = raw.get("night_stools", "No")
                leakage = raw.get("leakage", "None")
                # Validate leakage value matches frontend options
                if leakage not in ("None", "Liquid", "Solid"):
                    print(f"Warning: Invalid leakage value '{leakage}', defaulting to 'None'")
                    leakage = "None"
                incomplete_evacuation = raw.get("incomplete_evacuation", "No")
                bloating = raw.get("bloating", 0.0)
                impact_score = raw.get("impact_score", 0.0)
                activity_interfere = raw.get("activity_interfere", 0.0)
                
                # Парсим food_consumption Map в отдельные колонки
                # Frontend sends keys: 'vegetables_all_types', 'root_vegetables', 
                # 'whole_grains', 'whole_grain_bread', 'nuts_and_seeds', 'legumes',
                # 'fruits_with_skin', 'berries_any', 'soft_fruits_without_skin', 
                # 'muesli_and_bran_cereals'
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
                
                # Парсим drink_consumption Map в отдельные колонки
                # Frontend sends keys: 'water', 'coffee', 'tea', 'alcohol',
                # 'carbonated_drinks', 'juices', 'dairy_drinks', 'energy_drinks'
                drink = payload.drink_consumption or {}
                drink_water = drink.get("water", 0)
                drink_coffee = drink.get("coffee", 0)
                drink_tea = drink.get("tea", 0)
                drink_alcohol = drink.get("alcohol", 0)
                drink_carbonated = drink.get("carbonated_drinks", 0)
                drink_juices = drink.get("juices", 0)
                drink_dairy = drink.get("dairy_drinks", 0)
                drink_energy = drink.get("energy_drinks", 0)
                
                res2 = await session.execute(
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
                    """)
                    .bindparams(
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
                row2 = res2.first()
        return {"status": "ok", "id": str(row2[0])}
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in sendDaily: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500, 
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


@app.post("/sendMonthly")
async def send_monthly(payload: MonthlyPayload, x_patient_code: Optional[str] = Header(None)):
    if not x_patient_code:
        raise HTTPException(status_code=400, detail="Missing X-Patient-Code header")
    patient_code = x_patient_code.strip().upper()
    if not patient_code or len(patient_code) < 4 or len(patient_code) > 64:
        raise HTTPException(status_code=400, detail="Invalid patient code format")

    if not async_session:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        async with async_session() as session:
            async with session.begin():
                res = await session.execute(
                    text("""
                        INSERT INTO patients (patient_code)
                        VALUES (:code)
                        ON CONFLICT (patient_code) DO UPDATE SET patient_code = EXCLUDED.patient_code
                        RETURNING id
                    """).bindparams(code=patient_code)
                )
                patient_id = res.first()[0]

                # Парсим raw_data в отдельные поля
                raw = payload.raw_data or {}
                avoid_travel = raw.get("avoid_travel", 1.0)
                avoid_social = raw.get("avoid_social", 1.0)
                embarrassed = raw.get("embarrassed", 1.0)
                worry_notice = raw.get("worry_notice", 1.0)
                depressed = raw.get("depressed", 1.0)
                control = raw.get("control", 0.0)
                satisfaction = raw.get("satisfaction", 0.0)
                
                res2 = await session.execute(
                    text("""
                        INSERT INTO monthly_entries (
                            patient_id, entry_date, qol_score,
                            avoid_travel, avoid_social, embarrassed, worry_notice,
                            depressed, control, satisfaction
                        ) VALUES (
                            :patient_id,
                            COALESCE(CAST(:entry_date AS DATE), CURRENT_DATE),
                            :qol_score,
                            :avoid_travel, :avoid_social, :embarrassed, :worry_notice,
                            :depressed, :control, :satisfaction
                        )
                        ON CONFLICT (patient_id, entry_date) DO UPDATE SET
                            qol_score = EXCLUDED.qol_score,
                            avoid_travel = EXCLUDED.avoid_travel,
                            avoid_social = EXCLUDED.avoid_social,
                            embarrassed = EXCLUDED.embarrassed,
                            worry_notice = EXCLUDED.worry_notice,
                            depressed = EXCLUDED.depressed,
                            control = EXCLUDED.control,
                            satisfaction = EXCLUDED.satisfaction
                        RETURNING id
                    """)
                    .bindparams(
                        patient_id=patient_id,
                        entry_date=payload.entry_date,
                        qol_score=payload.qol_score,
                        avoid_travel=avoid_travel,
                        avoid_social=avoid_social,
                        embarrassed=embarrassed,
                        worry_notice=worry_notice,
                        depressed=depressed,
                        control=control,
                        satisfaction=satisfaction,
                    )
                )
                row2 = res2.first()
        return {"status": "ok", "id": str(row2[0])}
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in sendMonthly: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500, 
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


@app.post("/sendEq5d5l")
async def send_eq5d5l(payload: Eq5d5lPayload, x_patient_code: Optional[str] = Header(None)):
    if not x_patient_code:
        raise HTTPException(status_code=400, detail="Missing X-Patient-Code header")
    patient_code = x_patient_code.strip().upper()
    if not patient_code or len(patient_code) < 4 or len(patient_code) > 64:
        raise HTTPException(status_code=400, detail="Invalid patient code format")

    if not async_session:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        async with async_session() as session:
            async with session.begin():
                res = await session.execute(
                    text("""
                        INSERT INTO patients (patient_code)
                        VALUES (:code)
                        ON CONFLICT (patient_code) DO UPDATE SET patient_code = EXCLUDED.patient_code
                        RETURNING id
                    """).bindparams(code=patient_code)
                )
                patient_id = res.first()[0]

                # Extract health VAS from payload or raw_data if provided
                health_vas = payload.health_vas
                if health_vas is None and payload.raw_data is not None:
                    hv = payload.raw_data.get("health_vas")
                    if isinstance(hv, (int, float)):
                        try:
                            health_vas = int(hv)
                        except Exception:
                            health_vas = None

                res2 = await session.execute(
                    text("""
                        INSERT INTO eq5d5l_entries (
                            patient_id, entry_date,
                            mobility, self_care, usual_activities,
                            pain_discomfort, anxiety_depression, health_vas
                        ) VALUES (
                            :patient_id,
                            COALESCE(CAST(:entry_date AS DATE), CURRENT_DATE),
                            :mobility, :self_care, :usual_activities,
                            :pain_discomfort, :anxiety_depression, :health_vas
                        )
                        ON CONFLICT (patient_id, entry_date) DO UPDATE SET
                            mobility = EXCLUDED.mobility,
                            self_care = EXCLUDED.self_care,
                            usual_activities = EXCLUDED.usual_activities,
                            pain_discomfort = EXCLUDED.pain_discomfort,
                            anxiety_depression = EXCLUDED.anxiety_depression,
                            health_vas = EXCLUDED.health_vas
                        RETURNING id
                    """)
                    .bindparams(
                        patient_id=patient_id,
                        entry_date=payload.entry_date,
                        mobility=payload.mobility,
                        self_care=payload.self_care,
                        usual_activities=payload.usual_activities,
                        pain_discomfort=payload.pain_discomfort,
                        anxiety_depression=payload.anxiety_depression,
                        health_vas=health_vas,
                    )
                )
                row2 = res2.first()
        return {"status": "ok", "id": str(row2[0])}
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in sendEq5d5l: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500, 
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


async def _execute_with_retry(session, query, max_retries=3, initial_delay=0.5):
    """Execute query with retry logic for transient errors"""
    last_error = None
    for attempt in range(max_retries):
        try:
            result = await session.execute(query)
            return result
        except Exception as e:
            error_str = str(e)
            error_type = type(e).__name__
            last_error = e
            
            # Identify different error types
            is_pool_error = (
                "MaxClientsInSessionMode" in error_str or 
                "max clients reached" in error_str.lower() or
                "pool" in error_str.lower() or
                "connection" in error_str.lower() and "unavailable" in error_str.lower()
            )
            
            is_timeout = (
                error_type == "TimeoutError" or 
                "timeout" in error_str.lower() or
                "CancelledError" in error_type or
                "asyncio.TimeoutError" in error_type
            )
            
            is_connection_error = (
                "connection" in error_str.lower() and (
                    "closed" in error_str.lower() or
                    "lost" in error_str.lower() or
                    "reset" in error_str.lower()
                )
            )
            
            # Log the error
            print(f"Database error on attempt {attempt + 1}/{max_retries}: {error_type}: {error_str[:200]}")
            
            # Retry on pool errors and connection errors (transient)
            if (is_pool_error or is_connection_error) and attempt < max_retries - 1:
                # Exponential backoff: 0.5s, 1s, 2s
                delay = initial_delay * (2 ** attempt)
                print(f"Retrying after {delay}s...")
                await asyncio.sleep(delay)
                continue
            
            # For timeouts, retry once more with longer delay
            if is_timeout and attempt < max_retries - 1:
                delay = initial_delay * (2 ** attempt) * 2  # Longer delay for timeouts
                print(f"Timeout detected, retrying after {delay}s...")
                await asyncio.sleep(delay)
                continue
            
            # Don't retry on other errors (syntax errors, constraint violations, etc.)
            if not (is_pool_error or is_timeout or is_connection_error):
                print(f"Non-retryable error: {error_type}: {error_str[:200]}")
                raise
            
            # If we're on the last attempt, raise the error
            if attempt == max_retries - 1:
                print(f"Max retries reached, failing with: {error_type}: {error_str[:200]}")
                raise
    
    # This shouldn't be reached, but just in case - raise the last error
    if last_error:
        raise last_error
    # If we somehow got here without an error, something is wrong
    raise Exception("_execute_with_retry completed without result or error")


@app.get("/getLarsData")
async def get_lars_data(
    period: str,  # "weekly", "monthly", or "yearly"
    x_patient_code: Optional[str] = Header(None)
):
    """
    Get LARS score data for a patient grouped by time period.
    Returns data points with entry_date and total_score for the specified period.
    Optimized: combines patient lookup and data query in single SQL.
    """
    if not x_patient_code:
        raise HTTPException(status_code=400, detail="Missing X-Patient-Code header")
    patient_code = x_patient_code.strip().upper()
    if not patient_code or len(patient_code) < 4 or len(patient_code) > 64:
        raise HTTPException(status_code=400, detail="Invalid patient code format")

    if not async_session:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    # Validate period
    if period not in ["weekly", "monthly", "yearly"]:
        raise HTTPException(status_code=400, detail="Invalid period. Must be 'weekly', 'monthly', or 'yearly'")
    
    try:
        async with async_session() as session:
            # Optimized: Get patient_id and data in ONE query using JOIN
            if period == "weekly":
                query = text("""
                    SELECT 
                        DATE_TRUNC('week', we.entry_date) as period_start,
                        AVG(we.total_score)::INTEGER as avg_score,
                        MIN(we.entry_date) as first_entry_date
                    FROM weekly_entries we
                    INNER JOIN patients p ON p.id = we.patient_id
                    WHERE p.patient_code = :code
                        AND we.total_score IS NOT NULL
                    GROUP BY DATE_TRUNC('week', we.entry_date)
                    ORDER BY period_start DESC
                    LIMIT 5
                """)
            elif period == "monthly":
                query = text("""
                    SELECT 
                        DATE_TRUNC('month', we.entry_date) as period_start,
                        AVG(we.total_score)::INTEGER as avg_score,
                        MIN(we.entry_date) as first_entry_date
                    FROM weekly_entries we
                    INNER JOIN patients p ON p.id = we.patient_id
                    WHERE p.patient_code = :code
                        AND we.total_score IS NOT NULL
                        AND we.entry_date >= CURRENT_DATE - INTERVAL '6 months'
                    GROUP BY DATE_TRUNC('month', we.entry_date)
                    ORDER BY period_start ASC
                """)
            else:  # yearly
                query = text("""
                    SELECT 
                        DATE_TRUNC('year', we.entry_date) as period_start,
                        AVG(we.total_score)::INTEGER as avg_score,
                        MIN(we.entry_date) as first_entry_date
                    FROM weekly_entries we
                    INNER JOIN patients p ON p.id = we.patient_id
                    WHERE p.patient_code = :code
                        AND we.total_score IS NOT NULL
                        AND we.entry_date >= CURRENT_DATE - INTERVAL '5 years'
                    GROUP BY DATE_TRUNC('year', we.entry_date)
                    ORDER BY period_start ASC
                """)
            
            # Execute with retry logic
            try:
                result = await _execute_with_retry(session, query.bindparams(code=patient_code))
                if result is None:
                    # This shouldn't happen with new retry logic, but keep for safety
                    print("WARNING: _execute_with_retry returned None unexpectedly")
                    return JSONResponse(
                        status_code=503,
                        content={"status": "error", "detail": "Database connection timeout, please try again"}
                    )
                rows = result.fetchall()
            except Exception as query_error:
                # If retry logic failed, log and return 503
                error_msg = str(query_error)
                error_type = type(query_error).__name__
                print(f"Query execution failed after retries: {error_type}: {error_msg[:200]}")
                return JSONResponse(
                    status_code=503,
                    content={
                        "status": "error", 
                        "detail": f"Database error: {error_type}. Please try again.",
                        "error_type": error_type
                    }
                )
            
            # Reverse if ordered DESC to get chronological order
            if period == "weekly" and rows:
                rows = list(reversed(rows))
            
            data = []
            for idx, row in enumerate(rows, start=1):
                data.append({
                    "index": idx,
                    "date": row[2].isoformat() if row[2] else None,  # first_entry_date
                    "score": row[1] if row[1] is not None else None  # avg_score
                })
            
            return {"status": "ok", "data": data}
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getLarsData: {error_type}: {error_msg}")
        traceback.print_exc()
        
        # Return empty data instead of error for connection issues
        if ("MaxClientsInSessionMode" in error_msg or 
            "max clients reached" in error_msg.lower() or
            "TimeoutError" in error_type or
            "timeout" in error_msg.lower() or
            "CancelledError" in error_type):
            print(f"Connection issue in getLarsData, returning empty data: {error_type}")
            return {"status": "ok", "data": []}
        
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )

@app.get("/getNextQuestionnaire")
async def get_next_questionnaire(x_patient_code: Optional[str] = Header(None)):
    """
    Determine which questionnaire should be filled today based on:
    - EQ-5D-5L: at 2 weeks, 1 month, 3 months, 6 months, 12 months after patient registration
    - Weekly (LARS): once per week (every 7 days)
    - Monthly: once per month (~30 days), but on a different day of week than weekly
    - Daily: if no mandatory questionnaires are due
    
    Returns questionnaire type: "daily", "weekly", "monthly", "eq5d5l", or null if all done.
    """
    if not x_patient_code:
        raise HTTPException(status_code=400, detail="Missing X-Patient-Code header")
    patient_code = x_patient_code.strip().upper()
    if not patient_code or len(patient_code) < 4 or len(patient_code) > 64:
        raise HTTPException(status_code=400, detail="Invalid patient code format")

    if not async_session:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        from datetime import datetime, date, timedelta
        
        async with async_session() as session:
            today = date.today()
            
            # Optimized: Get all patient data and last completion dates in ONE query
            # Use retry logic for connection pool issues
            try:
                patient_res = await _execute_with_retry(
                    session,
                    text("""
                        SELECT 
                            p.id,
                            p.created_at::DATE as patient_created_date,
                            (SELECT MAX(entry_date) FROM weekly_entries WHERE patient_id = p.id) as last_weekly_date,
                            (SELECT MAX(entry_date) FROM monthly_entries WHERE patient_id = p.id) as last_monthly_date,
                            (SELECT MAX(entry_date) FROM eq5d5l_entries WHERE patient_id = p.id) as last_eq5d5l_date,
                            (SELECT MAX(entry_date) FROM daily_entries WHERE patient_id = p.id) as last_daily_date
                        FROM patients p
                        WHERE p.patient_code = :code
                    """).bindparams(code=patient_code)
                )
                if patient_res is None:
                    # This shouldn't happen with new retry logic, but keep for safety
                    print("WARNING: _execute_with_retry returned None in getNextQuestionnaire")
                    return {
                        "status": "ok",
                        "questionnaire_type": "daily",
                        "is_today_filled": False,
                        "reason": "Unable to determine questionnaire (database timeout)"
                    }
                patient_row = patient_res.first()
            except Exception as query_error:
                # If query failed after retries, return default response
                error_msg = str(query_error)
                error_type = type(query_error).__name__
                print(f"Query execution failed in getNextQuestionnaire: {error_type}: {error_msg[:200]}")
                return {
                    "status": "ok",
                    "questionnaire_type": "daily",
                    "is_today_filled": False,
                    "reason": f"Unable to determine questionnaire (database error: {error_type})"
                }
            
            # If patient doesn't exist, suggest first questionnaire (weekly) - patient will be created when they submit
            if not patient_row:
                return {
                    "status": "ok",
                    "questionnaire_type": "weekly",
                    "is_today_filled": False,
                    "reason": "Welcome! Please start with your first weekly questionnaire (LARS)"
                }
            
            patient_id = patient_row[0]
            patient_created_date = patient_row[1] if patient_row[1] is not None else None
            last_weekly_date = patient_row[2] if patient_row[2] is not None else None
            last_monthly_date = patient_row[3] if patient_row[3] is not None else None
            last_eq5d5l_date = patient_row[4] if patient_row[4] is not None else None
            last_daily_date = patient_row[5] if patient_row[5] is not None else None
            
            # Determine next questionnaire using priority logic
            questionnaire_type = None
            reason = None
            
            # Priority 1: EQ-5D-5L (quality of life) - scheduled milestones
            # Optimized: Check all milestones in one query
            if patient_created_date:
                days_since_start = (today - patient_created_date).days
                eq5d5l_milestones = [14, 30, 90, 180, 365]  # 2 weeks, 1 month, 3 months, 6 months, 12 months
                
                # Build list of milestone dates to check
                milestones_to_check = []
                for milestone_days in eq5d5l_milestones:
                    milestone_date = patient_created_date + timedelta(days=milestone_days)
                    # Only consider milestones that are due (within 3 days before to 7 days after)
                    if today >= milestone_date - timedelta(days=3) and days_since_start >= milestone_days - 3:
                        milestones_to_check.append((milestone_days, milestone_date))
                
                # Check all milestones in one query if there are any to check
                if milestones_to_check:
                    # Build date ranges for all milestones
                    date_ranges = []
                    for milestone_days, milestone_date in milestones_to_check:
                        window_start = milestone_date - timedelta(days=3)
                        window_end = milestone_date + timedelta(days=7)
                        date_ranges.append((milestone_days, milestone_date, window_start, window_end))
                    
                    # Get all eq5d5l entries in the relevant date range
                    if date_ranges:
                        min_date = min(range_item[2] for range_item in date_ranges)
                        max_date = max(range_item[3] for range_item in date_ranges)
                        
                        check_res = await _execute_with_retry(
                            session,
                            text("""
                                SELECT entry_date
                                FROM eq5d5l_entries
                                WHERE patient_id = :patient_id
                                    AND entry_date >= :min_date
                                    AND entry_date <= :max_date
                            """).bindparams(
                                patient_id=patient_id,
                                min_date=min_date,
                                max_date=max_date
                            )
                        )
                        if check_res is None:
                            # Skip milestone check if pool exhausted
                            filled_dates = set()
                        else:
                            filled_dates = {row[0] for row in check_res.fetchall()}
                        
                        # Find first unfilled milestone
                        for milestone_days, milestone_date, window_start, window_end in date_ranges:
                            milestone_filled = any(
                                window_start <= filled_date <= window_end 
                                for filled_date in filled_dates
                            )
                            
                            if not milestone_filled:
                                questionnaire_type = "eq5d5l"
                                reason = f"EQ-5D-5L milestone at {milestone_days} days ({'due' if days_since_start >= milestone_days else 'upcoming'})"
                                break  # Found next uncompleted milestone, stop checking
            
            # Priority 2: Weekly (LARS) - once per week
            if not questionnaire_type:
                if last_weekly_date:
                    days_since_weekly = (today - last_weekly_date).days
                    if days_since_weekly >= 7:
                        questionnaire_type = "weekly"
                        reason = "Weekly questionnaire due (7 days passed)"
                else:
                    # Never filled weekly - make it due
                    questionnaire_type = "weekly"
                    reason = "First weekly questionnaire"
            
            # Priority 3: Monthly - once per month, but avoid same day as weekly
            if not questionnaire_type:
                if last_monthly_date:
                    days_since_monthly = (today - last_monthly_date).days
                    if days_since_monthly >= 28:  # ~4 weeks, slightly less than 30 to allow flexibility
                        # Check if weekly is also due today - if so, weekly has priority
                        weekly_due_today = False
                        if last_weekly_date:
                            days_since_weekly = (today - last_weekly_date).days
                            if days_since_weekly >= 7:
                                weekly_due_today = True
                        
                        if not weekly_due_today:
                            # Weekly is not due today, so monthly can be shown
                            questionnaire_type = "monthly"
                            reason = "Monthly questionnaire due (28+ days passed)"
                        # If weekly is also due, it will take priority (already checked above)
                else:
                    # Never filled monthly - but check if we should prioritize weekly first
                    weekly_due = False
                    if last_weekly_date:
                        days_since_weekly = (today - last_weekly_date).days
                        if days_since_weekly >= 7:
                            weekly_due = True
                    
                    if not weekly_due:
                        # Weekly is not due, can show monthly
                        questionnaire_type = "monthly"
                        reason = "First monthly questionnaire"
                    # If weekly is due, it will take priority (already checked above)
            
            # Priority 4: Daily - if no mandatory questionnaires are due
            if not questionnaire_type:
                if last_daily_date:
                    if (today - last_daily_date).days >= 1:
                        questionnaire_type = "daily"
                        reason = "Daily questionnaire available"
                else:
                    questionnaire_type = "daily"
                    reason = "First daily questionnaire"
            
            # Check if today's questionnaire is already filled
            # Optimized: Check in one query using UNION
            is_today_filled = False
            if questionnaire_type:
                try:
                    table_map = {
                        "weekly": "weekly_entries",
                        "monthly": "monthly_entries",
                        "eq5d5l": "eq5d5l_entries",
                        "daily": "daily_entries"
                    }
                    table_name = table_map.get(questionnaire_type)
                    if table_name:
                        check = await _execute_with_retry(
                            session,
                            text(f"SELECT COUNT(*) FROM {table_name} WHERE patient_id = :pid AND entry_date = :today")
                            .bindparams(pid=patient_id, today=today)
                        )
                        if check is not None:
                            check_row = check.first()
                            is_today_filled = check_row[0] > 0 if check_row else False
                except Exception as check_error:
                    # If check fails, assume not filled
                    print(f"Warning: Failed to check if today's questionnaire is filled: {check_error}")
                    is_today_filled = False
            
            return {
                "status": "ok",
                "questionnaire_type": questionnaire_type,
                "is_today_filled": is_today_filled,
                "reason": reason
            }
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getNextQuestionnaire: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


@app.get("/getPatients")
async def get_patients():
    """
    Get list of all patients for doctor interface.
    Returns patient codes and basic info (no PII).
    """
    if not async_session:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        async with async_session() as session:
            result = await _execute_with_retry(
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
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getPatients: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )


@app.get("/getPatientDetail")
async def get_patient_detail(patient_code: str = Query(..., description="Patient code")):
    """
    Get detailed patient data for charts and graphs.
    Returns LARS scores, EQ-5D-5L scores, daily entries with food/drink consumption.
    """
    patient_code = patient_code.strip().upper()
    if not patient_code or len(patient_code) < 4 or len(patient_code) > 64:
        raise HTTPException(status_code=400, detail="Invalid patient code format")

    if not async_session:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        async with async_session() as session:
            # Get patient_id
            patient_res = await _execute_with_retry(
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
            lars_res = await _execute_with_retry(
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
            eq5d5l_res = await _execute_with_retry(
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
            daily_res = await _execute_with_retry(
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
        error_msg = str(e)
        error_type = type(e).__name__
        print(f"Error in getPatientDetail: {error_type}: {error_msg}")
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": error_msg, "error_type": error_type}
        )

