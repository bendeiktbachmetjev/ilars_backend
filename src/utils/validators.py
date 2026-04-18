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
        period: Period to validate. Allowed values:
            - "weekly"    (7 days)
            - "monthly"   (30 days)
            - "3months"   (90 days)
            - "6months"   (180 days)
            - "yearly"    (365 days)

    Returns:
        Validated period

    Raises:
        HTTPException: If period is invalid
    """
    allowed = ["weekly", "monthly", "3months", "6months", "yearly"]
    if period not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period. Must be one of: {', '.join(allowed)}"
        )
    return period

