#!/usr/bin/env python3
"""
Quick test for registration endpoint
"""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_registration():
    """Test registration endpoint with a simple request"""
    print("👤 Testing registration endpoint...")
    
    data = {
        "email": "test@example.com",
        "password": "test123",
        "full_name": "Test User",
        "role": "teacher"
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/register",
            json=data,
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        
        if response.status_code == 201:
            print("✅ Registration endpoint is working!")
            return True
        else:
            print(f"❌ Registration failed: {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Registration endpoint error: {e}")
        return False

def test_login():
    """Test login endpoint"""
    print("\n🔐 Testing login endpoint...")
    
    data = {
        "email": "test@example.com",
        "password": "test123"
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/auth/login",
            json=data,
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
        
        if response.status_code == 200:
            print("✅ Login endpoint is working!")
            return response.json().get("access_token")
        else:
            print(f"❌ Login failed: {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Login endpoint error: {e}")
        return None

if __name__ == "__main__":
    print("🚀 Quick API Test")
    print("=" * 30)
    
    # Test registration
    if test_registration():
        # Test login
        token = test_login()
        if token:
            print(f"\n🎉 Success! Token: {token[:20]}...")
        else:
            print("\n❌ Login failed")
    else:
        print("\n❌ Registration failed")
