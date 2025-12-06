"""
Pydantic models for request/response validation
"""
from typing import Optional
from pydantic import BaseModel


class WeeklyPayload(BaseModel):
    """Weekly LARS questionnaire payload"""
    flatus_control: int
    liquid_stool_leakage: int
    bowel_frequency: int
    repeat_bowel_opening: int
    urgency_to_toilet: int
    entry_date: Optional[str] = None
    raw_data: Optional[dict] = None


class DailyPayload(BaseModel):
    """Daily symptom entry payload"""
    entry_date: Optional[str] = None
    bristol_scale: Optional[int] = None
    food_consumption: Optional[dict] = None  # Map<String, int>
    drink_consumption: Optional[dict] = None  # Map<String, int>
    raw_data: Optional[dict] = None  # Contains: stool_count, pads_used, urgency, etc.


class MonthlyPayload(BaseModel):
    """Monthly QoL questionnaire payload"""
    entry_date: Optional[str] = None
    qol_score: Optional[int] = None
    raw_data: Optional[dict] = None  # Contains: avoid_travel, avoid_social, etc.


class Eq5d5lPayload(BaseModel):
    """EQ-5D-5L questionnaire payload"""
    mobility: int
    self_care: int
    usual_activities: int
    pain_discomfort: int
    anxiety_depression: int
    health_vas: Optional[int] = None  # 0..100 Visual Analogue Scale
    entry_date: Optional[str] = None
    raw_data: Optional[dict] = None

