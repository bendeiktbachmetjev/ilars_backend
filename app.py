"""
Legacy app.py - re-exports from new modular structure for backward compatibility.

This file exists for backward compatibility. The actual application is now in src/main.py
with a clean modular architecture:
- src/models/ - Pydantic models
- src/routes/ - API endpoints organized by domain
- src/services/ - Business logic
- src/database/ - Database connection and utilities
- src/utils/ - Utility functions

To use the new structure directly, import from src.main instead:
    from src.main import app
"""

# Re-export app from new modular structure
from src.main import app

# Re-export models for backward compatibility (if needed by external code)
from src.models.schemas import (
    WeeklyPayload,
    DailyPayload,
    MonthlyPayload,
    Eq5d5lPayload
)

__all__ = ['app', 'WeeklyPayload', 'DailyPayload', 'MonthlyPayload', 'Eq5d5lPayload']
