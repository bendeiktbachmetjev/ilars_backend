# LARS Backend - Application Structure

## Architecture Overview

This backend follows a clean, modular architecture with separation of concerns:

```
app/
├── __init__.py
├── main.py              # FastAPI application entry point
├── config.py            # Application configuration
├── models/              # Pydantic models for request/response validation
│   ├── __init__.py
│   └── schemas.py
├── routes/              # API endpoints organized by domain
│   ├── __init__.py
│   ├── health.py        # Health check endpoints
│   ├── patients.py      # Patient management endpoints
│   ├── weekly.py        # Weekly questionnaire endpoints
│   ├── daily.py         # Daily questionnaire endpoints
│   ├── monthly.py       # Monthly questionnaire endpoints
│   ├── eq5d5l.py        # EQ-5D-5L questionnaire endpoints
│   └── questionnaire.py # Questionnaire logic endpoints
├── services/            # Business logic layer
│   ├── __init__.py
│   └── patient_service.py
├── database/            # Database connection and utilities
│   ├── __init__.py
│   ├── connection.py    # Database connection management
│   └── queries.py       # Query utilities with retry logic
└── utils/               # Utility functions
    ├── __init__.py
    ├── url_builder.py   # Database URL utilities
    └── validators.py    # Input validation utilities
```

## Key Principles

1. **Separation of Concerns**: Routes handle HTTP, services handle business logic, database handles data access
2. **Single Responsibility**: Each module has a clear, focused purpose
3. **Dependency Injection**: Services and utilities are injected where needed
4. **Error Handling**: Consistent error handling across all layers
5. **Type Safety**: Pydantic models ensure type validation

## Running the Application

The application is started via `startup.py` which uses:
```python
from src.main import app
uvicorn.run(app, host=host, port=port)
```

## Backward Compatibility

The old `app.py` file in the root directory is now a thin re-export wrapper:
```python
from src.main import app
```

This ensures backward compatibility while using the new modular structure internally.

## Migration from Old Structure

The old monolithic `app.py` file has been refactored into this modular structure. All endpoints remain functional with the same API contracts. The old `app.py` now simply re-exports from `src.main` for compatibility.

