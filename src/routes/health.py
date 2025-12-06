"""
Health check endpoints
"""
from fastapi import APIRouter
from src.database.connection import is_initialized

router = APIRouter()


@router.get("/healthz")
async def healthcheck():
    """Health check endpoint"""
    db_status = "ok" if is_initialized() else "not_configured"
    return {"status": "ok", "database": db_status}

