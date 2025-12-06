"""
Database query utilities with retry logic
"""
import asyncio
from typing import Optional, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def execute_with_retry(
    session: AsyncSession,
    query: Any,
    max_retries: int = 3,
    initial_delay: float = 0.5
) -> Optional[Any]:
    """
    Execute query with retry logic for transient database errors
    
    Args:
        session: Database session
        query: SQLAlchemy query object
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries (exponential backoff)
        
    Returns:
        Query result or None if pool exhausted
    """
    last_error = None
    
    for attempt in range(max_retries):
        try:
            result = await session.execute(query)
            return result
        except Exception as e:
            error_str = str(e)
            error_type = type(e).__name__
            last_error = e
            
            # Identify error types
            is_pool_error = (
                "MaxClientsInSessionMode" in error_str or
                "max clients reached" in error_str.lower() or
                "connection pool" in error_str.lower()
            )
            
            is_connection_error = (
                "connection" in error_str.lower() and (
                    "closed" in error_str.lower() or
                    "lost" in error_str.lower() or
                    "reset" in error_str.lower()
                )
            )
            
            is_timeout = (
                error_type == "TimeoutError" or
                "timeout" in error_str.lower() or
                "CancelledError" in error_type
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
    
    # This shouldn't be reached, but just in case
    if last_error:
        raise last_error
    raise Exception("execute_with_retry completed without result or error")

