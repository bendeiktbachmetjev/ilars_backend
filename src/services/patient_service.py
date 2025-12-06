"""
Patient service - business logic for patient operations
"""
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.queries import execute_with_retry


class PatientService:
    """Service for patient-related operations"""
    
    @staticmethod
    async def get_or_create_patient(session: AsyncSession, patient_code: str) -> str:
        """
        Get or create patient by code
        
        Args:
            session: Database session
            patient_code: Patient code
            
        Returns:
            Patient ID (UUID as string)
        """
        result = await execute_with_retry(
            session,
            text("""
                INSERT INTO patients (patient_code)
                VALUES (:code)
                ON CONFLICT (patient_code) DO UPDATE SET patient_code = EXCLUDED.patient_code
                RETURNING id
            """).bindparams(code=patient_code)
        )
        
        if result is None:
            raise Exception("Failed to get or create patient")
        
        return str(result.first()[0])
    
    @staticmethod
    async def get_patient_id(session: AsyncSession, patient_code: str) -> Optional[str]:
        """
        Get patient ID by code
        
        Args:
            session: Database session
            patient_code: Patient code
            
        Returns:
            Patient ID or None if not found
        """
        result = await execute_with_retry(
            session,
            text("SELECT id FROM patients WHERE patient_code = :code").bindparams(code=patient_code)
        )
        
        if result is None:
            return None
        
        row = result.first()
        return str(row[0]) if row else None

