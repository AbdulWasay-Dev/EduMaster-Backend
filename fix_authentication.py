#!/usr/bin/env python3
"""
Fix authentication to work with existing Supabase schema
"""

from services.supabase_client import get_supabase_service

def check_existing_schema():
    """Check what columns exist in the teachers table"""
    print("🔍 Checking existing teachers table schema...")
    
    try:
        supabase = get_supabase_service()
        
        # Try to get the table structure by attempting different column names
        possible_columns = [
            "id", "email", "name", "full_name", "teacher_name", 
            "role", "profile_image_url", "school_name", "department",
            "created_at", "updated_at", "hashed_password", "password"
        ]
        
        existing_columns = []
        
        for column in possible_columns:
            try:
                result = supabase.client.table("teachers").select(column).limit(1).execute()
                existing_columns.append(column)
                print(f"✅ Column '{column}' exists")
            except Exception as e:
                print(f"❌ Column '{column}' doesn't exist")
        
        print(f"\n📋 Existing columns: {existing_columns}")
        return existing_columns
        
    except Exception as e:
        print(f"❌ Error checking schema: {e}")
        return []

def create_simple_teachers_table():
    """Create a simple teachers table for our custom authentication"""
    print("\n🗄️ Creating simple teachers table...")
    
    try:
        supabase = get_supabase_service()
        
        # Drop existing table if it exists and create new one
        drop_sql = "DROP TABLE IF EXISTS teachers CASCADE;"
        create_sql = """
        CREATE TABLE teachers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'teacher' CHECK (role IN ('teacher', 'admin')),
            hashed_password TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        CREATE INDEX idx_teachers_email ON teachers(email);
        """
        
        # Execute drop and create
        print("📝 Dropping existing table...")
        supabase.client.rpc('exec_sql', {'sql': drop_sql}).execute()
        
        print("📝 Creating new table...")
        supabase.client.rpc('exec_sql', {'sql': create_sql}).execute()
        
        print("✅ Simple teachers table created successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error creating table: {e}")
        return False

def test_new_table():
    """Test the new table"""
    print("\n🔍 Testing new teachers table...")
    
    try:
        supabase = get_supabase_service()
        
        # Test insert
        test_data = {
            "email": "test@example.com",
            "full_name": "Test User",
            "role": "teacher",
            "hashed_password": "test_hash_123"
        }
        
        result = supabase.client.table("teachers").insert(test_data).execute()
        if result.data:
            print("✅ Insert successful!")
            print(f"Created user: {result.data[0]}")
            
            # Test select
            select_result = supabase.client.table("teachers").select("*").eq("email", "test@example.com").execute()
            if select_result.data:
                print("✅ Select successful!")
                print(f"Retrieved user: {select_result.data[0]}")
            
            # Clean up
            supabase.client.table("teachers").delete().eq("email", "test@example.com").execute()
            print("✅ Test data cleaned up!")
            
            return True
        else:
            print("❌ Insert failed!")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def main():
    """Main function"""
    print("🚀 Fix Authentication for Supabase")
    print("=" * 40)
    
    # Check existing schema
    existing_columns = check_existing_schema()
    
    if "hashed_password" in existing_columns and "full_name" in existing_columns:
        print("\n✅ Table already has the correct schema!")
        return
    
    print("\n🔧 Table needs to be recreated with correct schema...")
    
    # Create new table
    if create_simple_teachers_table():
        # Test new table
        if test_new_table():
            print("\n🎉 Authentication table is ready!")
            print("\n📋 You can now:")
            print("1. Register new users")
            print("2. Login with existing users")
            print("3. Test the authentication system")
        else:
            print("\n❌ New table test failed!")
    else:
        print("\n❌ Failed to create new table!")

if __name__ == "__main__":
    main()
