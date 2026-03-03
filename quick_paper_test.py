#!/usr/bin/env python3
"""
Quick test for paper generation
"""
import requests
import json

BASE_URL = "http://localhost:8000/api/v1"

def quick_test():
    """Quick test of paper generation"""
    print("🧪 Quick Paper Generation Test")
    
    # Login
    login_data = {"email": "user1@example.com", "password": "password123"}
    response = requests.post(f"{BASE_URL}/auth/login", json=login_data)
    
    if response.status_code != 200:
        print(f"❌ Login failed: {response.text}")
        return
    
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✅ Login successful")
    
    # Get subjects
    response = requests.get(f"{BASE_URL}/subjects", headers=headers)
    if response.status_code != 200:
        print(f"❌ Failed to get subjects: {response.text}")
        return
    
    subjects = response.json()
    if not subjects:
        print("❌ No subjects found")
        return
    
    subject_id = subjects[0]["id"]
    print(f"✅ Using subject: {subjects[0]['name']}")
    
    # Generate paper
    paper_data = {
        "subject_id": subject_id,
        "title": "Test Paper",
        "question_count": 5,
        "question_types": ["mcq", "short_answer"],
        "difficulty_level": "medium"
    }
    
    print("🔄 Generating paper...")
    response = requests.post(f"{BASE_URL}/papers/generate", json=paper_data, headers=headers)
    
    if response.status_code == 200:
        paper = response.json()
        print(f"✅ Paper generated successfully!")
        print(f"   - ID: {paper['id']}")
        print(f"   - Questions: {len(paper['questions'])}")
        print(f"   - Total Marks: {paper['total_marks']}")
        
        # Show first question
        if paper['questions']:
            q1 = paper['questions'][0]
            print(f"\n📝 Sample Question:")
            print(f"   Q1. {q1.get('question_text', 'No text')}")
            if q1.get('question_type') == 'mcq' and q1.get('options'):
                for i, opt in enumerate(q1['options']):
                    print(f"      {chr(65+i)}) {opt}")
            print(f"   Answer: {q1.get('correct_answer', 'No answer')}")
    else:
        print(f"❌ Paper generation failed: {response.text}")

if __name__ == "__main__":
    quick_test()
