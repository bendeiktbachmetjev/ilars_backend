"""
Validation utilities
"""
from typing import Optional
from fastapi import HTTPException


def validate_patient_code(patient_code: Optional[str]) -> str:
    """
    Validate and normalize patient code
    
    Args:
        patient_code: Patient code to validate
        
    Returns:
        Normalized patient code
        
    Raises:
        HTTPException: If patient code is invalid
    """
    if not patient_code:
        raise HTTPException(status_code=400, detail="Missing X-Patient-Code header")
    
    patient_code = patient_code.strip().upper()
    
    if not patient_code or len(patient_code) < 4 or len(patient_code) > 64:
        raise HTTPException(status_code=400, detail="Invalid patient code format")
    
    return patient_code


def validate_period(period: str) -> str:
    """
    Validate time period parameter
    
    Args:
        period: Period to validate (weekly, monthly, yearly)
        
    Returns:
        Validated period
        
    Raises:
        HTTPException: If period is invalid
    """
    if period not in ["weekly", "monthly", "yearly"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid period. Must be 'weekly', 'monthly', or 'yearly'"
        )
    return period

