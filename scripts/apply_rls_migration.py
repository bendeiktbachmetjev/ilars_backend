import asyncio
import sys
import os

# Add root directory to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.connection import init_database, get_session
from sqlalchemy import text

async def main():
    print("Initializing Database...")
    if not init_database():
        print("Failed to initialize database")
        return
        
    session_maker = get_session()
    
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migration_rls_setup.sql"), "r") as f:
        sql = f.read()

    print("Running migration...")
    try:
        async with session_maker() as session:
            # Execute the setup script
            await session.execute(text(sql))
            await session.commit()
            print("Successfully applied migration_rls_setup.sql")
    except Exception as e:
        print(f"Error applying migration: {e}")

if __name__ == "__main__":
    asyncio.run(main())
