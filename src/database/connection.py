"""
Database connection management
"""
import os
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.config import settings
from src.utils.url_builder import build_async_url, normalize_database_url


# Global database objects
engine: Optional[AsyncEngine] = None
async_session: Optional[sessionmaker] = None


def init_database() -> bool:
    """
    Initialize database connection
    
    Returns:
        True if initialization successful, False otherwise
    """
    global engine, async_session
    
    database_url = settings.DATABASE_URL
    if not database_url:
        print("Warning: DATABASE_URL not set, database features will be unavailable")
        return False
    
    try:
        # Normalize URL for connection pooling
        database_url = normalize_database_url(database_url)
        async_database_url = build_async_url(database_url)
        
        ssl_required = (
            "sslmode=require" in database_url.lower() or 
            settings.SUPABASE_SSLMODE == "require"
        )
        
        # Optimized connection args for reliability
        connect_args = {
            "server_settings": {
                "application_name": "lars_backend",
                "tcp_keepalives_idle": "600",
                "tcp_keepalives_interval": "30",
                "tcp_keepalives_count": "3",
            },
            "command_timeout": 60,  # Timeout for SQL commands (60 seconds)
            "timeout": 20,  # Connection timeout (20 seconds)
        }
        
        if ssl_required:
            # Minimal SSL config - just require SSL, don't verify cert (faster)
            # Supabase pooler doesn't need cert verification
            connect_args["ssl"] = True
        
        # Optimized pool settings for reliability with multiple concurrent users
        engine = create_async_engine(
            async_database_url,
            pool_pre_ping=True,  # Enable pre-ping to detect dead connections
            pool_size=10,  # Increased pool size for concurrent requests
            max_overflow=20,  # Allow more overflow for peak loads
            pool_recycle=3600,  # Recycle every hour
            pool_timeout=30,  # Longer timeout to wait for available connection
            connect_args=connect_args,
            max_identifier_length=128,
            echo=False,
            pool_reset_on_return="commit",  # Faster connection return
        )
        
        async_session = sessionmaker(
            bind=engine,
            expire_on_commit=False,
            class_=AsyncSession
        )
        
        print("Database engine initialized successfully")
        return True
        
    except Exception as e:
        print(f"Warning: Failed to initialize database engine: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_session() -> Optional[sessionmaker]:
    """
    Get database session maker
    
    Returns:
        Session maker or None if not initialized
    """
    return async_session


def is_initialized() -> bool:
    """
    Check if database is initialized
    
    Returns:
        True if initialized, False otherwise
    """
    return engine is not None and async_session is not None

