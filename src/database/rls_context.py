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
    Using standard SET, but we explicitly reset it to 'none' on exit to prevent connection pooling leaks.
    """
    try:
        commands = [f"SET app.current_role = '{role}'"]
        commands.append(f"SET app.current_user_id = '{user_id or ''}'")
        commands.append(f"SET app.doctor_id = '{doctor_id or ''}'")
        commands.append(f"SET app.hospital_id = '{hospital_id or ''}'")
            
        sql_command = "; ".join(commands) + ";"
        await execute_with_retry(session, text(sql_command))
        yield session
    finally:
        # Reset to safe defaults to avoid bleeding across connections
        await execute_with_retry(
            session, 
            text("""
                SET app.current_role = 'none';
                SET app.current_user_id = '';
                SET app.doctor_id = '';
                SET app.hospital_id = '';
            """)
        )

# Helper function
async def apply_system_context(session: AsyncSession):
    """Helper to quickly run queries as system (e.g. auth lookups)"""
    await execute_with_retry(session, text("SET app.current_role = 'system';"))
