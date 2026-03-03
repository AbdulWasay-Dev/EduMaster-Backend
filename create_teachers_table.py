#!/usr/bin/env python3
"""
Create teachers table in Supabase
"""

from services.supabase_client import get_supabase_service

def create_teachers_table():
    """Create teachers table in Supabase"""
    print("🗄️ Creating teachers table in Supabase...")
    
    try:
        supabase = get_supabase_service()
        
        # SQL to create teachers table
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS teachers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'teacher' CHECK (role IN ('teacher', 'admin')),
            hashed_password TEXT NOT NULL,
            profile_image_url TEXT,
            school_name TEXT,
            department TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_teachers_email ON teachers(email);
        """
        
        print("📝 Executing SQL to create teachers table...")
        
        # Execute the SQL
        result = supabase.client.rpc('exec_sql', {'sql': create_table_sql}).execute()
        
        print("✅ Teachers table created successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error creating teachers table: {e}")
        print("\n🔧 Let's try a different approach...")
        
        # Try to test if table already exists
        try:
            supabase = get_supabase_service()
            result = supabase.client.table("teachers").select("*").limit(1).execute()
            print("✅ Teachers table already exists and is accessible!")
            return True
        except Exception as e2:
            print(f"❌ Teachers table doesn't exist: {e2}")
            return False

def test_teachers_table():
    """Test teachers table operations"""
    print("\n🔍 Testing teachers table...")
    
    try:
        supabase = get_supabase_service()
        
        # Test select
        result = supabase.client.table("teachers").select("*").limit(5).execute()
        print(f"✅ Table accessible. Found {len(result.data)} existing teachers.")
        
        # Test insert (will be rolled back)
        test_data = {
            "email": "test@example.com",
            "full_name": "Test User",
            "role": "teacher",
            "hashed_password": "test_hash"
        }
        
        insert_result = supabase.client.table("teachers").insert(test_data).execute()
        if insert_result.data:
            print("✅ Insert operation successful!")
            
            # Clean up test data
            supabase.client.table("teachers").delete().eq("email", "test@example.com").execute()
            print("✅ Test data cleaned up!")
        
        return True
        
    except Exception as e:
        print(f"❌ Teachers table test failed: {e}")
        return False

def main():
    """Main function"""
    print("🚀 Teachers Table Setup")
    print("=" * 30)
    
    # Create table
    if create_teachers_table():
        # Test table
        if test_teachers_table():
            print("\n🎉 Teachers table is ready!")
            print("\n📋 You can now:")
            print("1. Register new users")
            print("2. Login with existing users")
            print("3. Test the authentication system")
        else:
            print("\n❌ Teachers table test failed!")
    else:
        print("\n❌ Failed to create teachers table!")

if __name__ == "__main__":
    main()
