"""
Main FastAPI application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from src.config import settings
from src.database.connection import init_database, is_initialized
from src.routes import health, patients, weekly, daily, monthly, eq5d5l, questionnaire, hospitals, doctors, steps, registry


# Create FastAPI app
app = FastAPI(
    title="LARS Backend API",
    description="Backend API for LARS (Low Anterior Resection Syndrome) patient tracking",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)

# Compress JSON responses over 1 KB (doctor patient list and detail shrink about 10x)
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Initialize database
init_database()

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(patients.router, tags=["Patients"])
app.include_router(weekly.router, tags=["Weekly"])
app.include_router(daily.router, tags=["Daily"])
app.include_router(monthly.router, tags=["Monthly"])
app.include_router(eq5d5l.router, tags=["EQ-5D-5L"])
app.include_router(questionnaire.router, tags=["Questionnaire"])
app.include_router(hospitals.router, tags=["Hospitals"])
app.include_router(doctors.router, tags=["Doctors"])
app.include_router(steps.router, tags=["Steps"])
app.include_router(registry.router, tags=["Registry"])

