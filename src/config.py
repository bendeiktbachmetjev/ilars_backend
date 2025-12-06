"""
Application configuration
"""
import os
from typing import Optional


class Settings:
    """Application settings"""
    
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL", "")
    SUPABASE_SSLMODE: Optional[str] = os.getenv("SUPABASE_SSLMODE")
    
    # CORS settings
    CORS_ORIGINS: list = ["*"]  # Allow all origins for doctor interface
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list = ["*"]
    CORS_ALLOW_HEADERS: list = ["*"]


settings = Settings()

