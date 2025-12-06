#!/usr/bin/env python3
"""Startup script for Railway deployment - reads PORT from environment."""
import os
import sys

def main():
    # Read PORT from environment, default to 8000
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    
    # Import uvicorn
    import uvicorn
    
    # Ensure current directory is in Python path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    
    # Use new modular structure (src/main.py)
    # app.py is now just a re-export for backward compatibility
    from src.main import app as fastapi_app
    print("Starting LARS Backend with modular architecture")
    uvicorn.run(fastapi_app, host=host, port=port)

if __name__ == "__main__":
    main()

