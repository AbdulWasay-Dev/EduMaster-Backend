#!/usr/bin/env python3
"""
Setup database schema in Supabase
"""

import os
import sys
from services.supabase_client import get_supabase_service

def setup_database():
    """Setup database schema in Supabase"""
    print("🗄️ Setting up EduMaster database schema in Supabase...")
    
    try:
        supabase = get_supabase_service()
        
        # Read the schema file
        with open('docs/simple_database_schema.sql', 'r') as f:
            schema_sql = f.read()
        
        print("📝 Executing database schema...")
        
        # Execute the schema
        result = supabase.client.rpc('exec_sql', {'sql': schema_sql}).execute()
        
        if result.data:
            print("✅ Database schema setup completed successfully!")
            return True
        else:
            print("❌ Database schema setup failed!")
            return False
            
    except Exception as e:
        print(f"❌ Error setting up database: {e}")
        print("\n🔧 Manual setup required:")
        print("1. Go to your Supabase dashboard")
        print("2. Navigate to SQL Editor")
        print("3. Copy and paste the contents of 'docs/simple_database_schema.sql'")
        print("4. Execute the SQL")
        return False

def test_database_connection():
    """Test database connection and basic operations"""
    print("\n🔍 Testing database connection...")
    
    try:
        supabase = get_supabase_service()
        
        # Test basic connection
        result = supabase.client.table("teachers").select("count").execute()
        print("✅ Database connection successful!")
        
        # Test table existence
        tables = ["teachers", "subjects", "documents", "doc_chunks", "papers", "questions"]
        for table in tables:
            try:
                supabase.client.table(table).select("*").limit(1).execute()
                print(f"✅ Table '{table}' exists and accessible")
            except Exception as e:
                print(f"❌ Table '{table}' not accessible: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Database connection test failed: {e}")
        return False

def main():
    """Main setup function"""
    print("🚀 EduMaster Database Setup")
    print("=" * 40)
    
    # Test connection first
    if not test_database_connection():
        print("\n❌ Database connection failed. Please check your Supabase credentials.")
        return
    
    # Setup schema
    if setup_database():
        print("\n🎉 Database setup completed successfully!")
        print("\n📋 Next steps:")
        print("1. Test user registration")
        print("2. Test user login")
        print("3. Start using the application")
    else:
        print("\n⚠️ Database setup failed. Please set up the schema manually.")

if __name__ == "__main__":
    main()
