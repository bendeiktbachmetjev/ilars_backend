"""
Context manager for Row Level Security (RLS) PostgreSQL integration.
"""
from contextlib import asynccontextmanager
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from src.database.queries import execute_with_retry

@asynccontextmanager
async def set_db_context(
    session: AsyncSession, 
    role: str, 
    user_id: Optional[str] = None, 
    doctor_id: Optional[str] = None, 
    hospital_id: Optional[str] = None
):
    """
    Sets PostgreSQL session variables for Row Level Security (RLS).
    Using standard set_config with bind params to be safe and compatible w/ asyncpg.
    """
    try:
        await execute_with_retry(
            session,
            text("""
                SELECT 
                    set_config('app.current_role', :role, false),
                    set_config('app.current_user_id', :user_id, false),
                    set_config('app.doctor_id', :doctor_id, false),
                    set_config('app.hospital_id', :hospital_id, false);
            """).bindparams(
                role=role,
                user_id=user_id or '',
                doctor_id=doctor_id or '',
                hospital_id=hospital_id or ''
            )
        )
        yield session
    finally:
        # Reset to safe defaults to avoid bleeding across connections.
        # Wrapped in try/except: if the body raised and left the transaction in an
        # aborted state, this reset would itself fail with InFailedSQLTransactionError
        # and MASK the original error. Suppressing it lets the real error propagate.
        # (On the success path the reset runs normally.)
        try:
            await execute_with_retry(
                session,
                text("""
                    SELECT
                        set_config('app.current_role', 'none', false),
                        set_config('app.current_user_id', '', false),
                        set_config('app.doctor_id', '', false),
                        set_config('app.hospital_id', '', false);
                """)
            )
        except Exception:
            pass

# Helper function
async def apply_system_context(session: AsyncSession):
    """Helper to quickly run queries as system (e.g. auth lookups)"""
    await execute_with_retry(
        session, 
        text("SELECT set_config('app.current_role', 'system', false);")
    )
