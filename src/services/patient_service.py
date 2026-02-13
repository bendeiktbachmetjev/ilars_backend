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
    async def get_or_create_patient(
        session: AsyncSession, 
        patient_code: str,
        doctor_id: str = None,
        hospital_id: str = None
    ) -> str:
        """
        Get or create patient by code, optionally linking to doctor and hospital
        
        Args:
            session: Database session
            patient_code: Patient code
            doctor_id: Optional doctor ID who created this patient
            hospital_id: Optional hospital ID where patient was treated
            
        Returns:
            Patient ID (UUID as string)
        """
        # If patient exists, update doctor_id and hospital_id if provided
        # If patient doesn't exist, create with doctor_id and hospital_id
        result = await execute_with_retry(
            session,
            text("""
                INSERT INTO patients (patient_code, doctor_id, hospital_id)
                VALUES (:code, 
                        CASE WHEN :doctor_id IS NOT NULL AND :doctor_id != '' THEN CAST(:doctor_id AS uuid) ELSE NULL END,
                        CASE WHEN :hospital_id IS NOT NULL AND :hospital_id != '' THEN CAST(:hospital_id AS uuid) ELSE NULL END)
                ON CONFLICT (patient_code) DO UPDATE SET
                    doctor_id = COALESCE(EXCLUDED.doctor_id, patients.doctor_id),
                    hospital_id = COALESCE(EXCLUDED.hospital_id, patients.hospital_id)
                RETURNING id
            """).bindparams(
                code=patient_code,
                doctor_id=doctor_id or None,
                hospital_id=hospital_id or None
            )
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

