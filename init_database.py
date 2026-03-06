"""
Database initialization script for EduMaster Backend (PostgreSQL + ChromaDB)
Run this script to set up the PostgreSQL database and ChromaDB.

You can also just start the server (python main.py) – it will auto-create
the database and all tables on first launch.
"""
import asyncio
import sys
import os

# Ensure the backend directory is on sys.path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def init_database():
    """Initialize the database using DatabaseService (same schema as the running app)"""
    from services.database import DatabaseService
    
    db = DatabaseService()
    print("🗄️  Initializing EduMaster database...")

    try:
        await db.initialize()
        print("✅ Database & ChromaDB initialised successfully!")
        
        # List created tables for confirmation
        async with db.connection() as conn:
            tables = await conn.fetch("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
            print(f"\n📋 Tables in database ({len(tables)}):")
            for t in tables:
                print(f"   - {t['table_name']}")
        
        await db.close()
        print("\n🎉 Done!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(init_database())