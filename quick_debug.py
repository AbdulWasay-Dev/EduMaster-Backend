#!/usr/bin/env python3
"""
Quick debug with timeout
"""
import requests
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "http://localhost:8010/api/v1"

def test_with_timeout():
    """Test with timeout to avoid hanging"""
    print("🧪 Quick Paper Generation Test with Timeout")
    
    # Create session with timeout
    session = requests.Session()
    session.timeout = 30  # 30 second timeout
    
    try:
        # Login
        print("1. Logging in...")
        login_data = {"email": "user1@example.com", "password": "string1"}
        response = session.post(f"{BASE_URL}/auth/login", json=login_data, timeout=10)
        
        if response.status_code != 200:
            print(f"❌ Login failed: {response.text}")
            return
        
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("✅ Login successful")
        
        # Test RAG first (simpler)
        print("2. Testing RAG query...")
        rag_data = {
            "question": "What is CS 6035?",
            "subject_id": "9949b9f8-1804-4747-9601-fd69c5630344"
        }
        
        response = session.post(f"{BASE_URL}/rag/query", json=rag_data, headers=headers, timeout=15)
        if response.status_code == 200:
            rag_result = response.json()
            print(f"✅ RAG works! Answer: {rag_result.get('answer', '')[:100]}...")
        else:
            print(f"❌ RAG failed: {response.status_code} - {response.text}")
            return
        
        # Now try paper generation with very small request
        print("3. Testing paper generation (small)...")
        paper_data = {
            "subject_id": "9949b9f8-1804-4747-9601-fd69c5630344",
            "title": "Quick Test",
            "question_count": 2,  # Very small
            "question_types": ["mcq"],
            "difficulty_level": "easy"
        }
        
        response = session.post(f"{BASE_URL}/papers/generate", json=paper_data, headers=headers, timeout=60)
        
        if response.status_code == 200:
            paper = response.json()
            print(f"✅ Paper generated!")
            print(f"   Questions: {len(paper['questions'])}")
            if paper['questions']:
                q1 = paper['questions'][0]
                print(f"   Sample: {q1.get('question_text', 'No text')[:50]}...")
        else:
            print(f"❌ Paper generation failed: {response.status_code}")
            try:
                error = response.json()
                print(f"   Error: {error}")
            except:
                print(f"   Raw: {response.text}")
                
    except requests.exceptions.Timeout:
        print("⏰ Request timed out - there's a performance issue")
    except requests.exceptions.ConnectionError:
        print("🔌 Connection error - is the server running?")
    except Exception as e:
        print(f"💥 Error: {e}")

if __name__ == "__main__":
    test_with_timeout()
