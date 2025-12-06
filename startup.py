#!/usr/bin/env python3
"""Startup script for Railway deployment - reads PORT from environment."""
import os
import sys

def main():
    # Read PORT from environment, default to 8000
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    
    # Import uvicorn and run the app
    import uvicorn
    # Use old app.py structure (app:app) for production stability
    # New modular structure in app/ folder can be enabled later
    uvicorn.run("app:app", host=host, port=port)

if __name__ == "__main__":
    main()

