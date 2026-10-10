"""
Patient service - business logic for patient operations
"""
from typing import Optional, List, Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.queries import execute_with_retry
from src.database.rls_context import set_db_context


class PatientService:
    """Service for patient-related operations"""
    
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
        async with set_db_context(session, role='system'):
            result = await execute_with_retry(
                session,
                text("SELECT id FROM patients WHERE patient_code = :code").bindparams(code=patient_code)
            )
        
        if result is None:
            return None
        
        row = result.first()
        return str(row[0]) if row else None

