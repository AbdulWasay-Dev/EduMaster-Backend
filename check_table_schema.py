#!/usr/bin/env python3
"""
Check the actual schema of the teachers table
"""

from services.supabase_client import get_supabase_service

def check_table_schema():
    """Check the actual schema of the teachers table"""
    print("🔍 Checking teachers table schema...")
    
    try:
        supabase = get_supabase_service()
        
        # Try to get table info
        result = supabase.client.table("teachers").select("*").limit(1).execute()
        print(f"✅ Table accessible. Found {len(result.data)} records.")
        
        if result.data:
            print("📋 Sample record structure:")
            for key, value in result.data[0].items():
                print(f"  {key}: {type(value).__name__}")
        else:
            print("📋 Table is empty, trying to insert a test record to see structure...")
            
            # Try to insert with different field names to see what works
            test_data_variants = [
                {"email": "test1@example.com", "name": "Test User", "role": "teacher", "hashed_password": "test_hash"},
                {"email": "test2@example.com", "full_name": "Test User", "role": "teacher", "hashed_password": "test_hash"},
                {"email": "test3@example.com", "teacher_name": "Test User", "role": "teacher", "hashed_password": "test_hash"}
            ]
            
            for i, test_data in enumerate(test_data_variants):
                try:
                    result = supabase.client.table("teachers").insert(test_data).execute()
                    if result.data:
                        print(f"✅ Variant {i+1} worked: {list(test_data.keys())}")
                        # Clean up
                        supabase.client.table("teachers").delete().eq("email", test_data["email"]).execute()
                        break
                except Exception as e:
                    print(f"❌ Variant {i+1} failed: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error checking table schema: {e}")
        return False

def main():
    """Main function"""
    print("🚀 Teachers Table Schema Check")
    print("=" * 35)
    
    check_table_schema()

if __name__ == "__main__":
    main()
