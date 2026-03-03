#!/usr/bin/env python3
"""
Debug script to check paper generation issues
"""
import requests
import json
import sys

BASE_URL = "http://localhost:8000/api/v1"

def debug_paper_generation():
    """Debug paper generation step by step"""
    print("🔍 Debugging Paper Generation Issues")
    print("=" * 50)
    
    # Step 1: Login
    print("\n1️⃣ Logging in...")
    login_data = {"email": "user1@example.com", "password": "string1"}
    response = requests.post(f"{BASE_URL}/auth/login", json=login_data)
    
    if response.status_code != 200:
        print(f"❌ Login failed: {response.text}")
        return False
    
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print("✅ Login successful")
    
    # Step 2: Get subjects
    print("\n2️⃣ Checking subjects...")
    response = requests.get(f"{BASE_URL}/subjects", headers=headers)
    if response.status_code != 200:
        print(f"❌ Failed to get subjects: {response.text}")
        return False
    
    subjects = response.json()
    print(f"✅ Found {len(subjects)} subjects:")
    for subject in subjects:
        print(f"   - {subject['name']} (ID: {subject['id']})")
    
    if not subjects:
        print("❌ No subjects found")
        return False
    
    subject_id = subjects[0]["id"]
    
    # Step 3: Check documents
    print(f"\n3️⃣ Checking documents for subject {subject_id}...")
    response = requests.get(f"{BASE_URL}/documents", params={"subject_id": subject_id}, headers=headers)
    if response.status_code != 200:
        print(f"❌ Failed to get documents: {response.text}")
        return False
    
    documents = response.json()
    print(f"✅ Found {len(documents)} documents:")
    for doc in documents:
        print(f"   - {doc['filename']} (Status: {doc.get('processing_status', 'unknown')})")
    
    if not documents:
        print("❌ No documents found for this subject")
        return False
    
    # Step 4: Check if documents are processed
    processed_docs = [doc for doc in documents if doc.get('processing_status') == 'completed']
    print(f"\n📊 Document processing status:")
    print(f"   - Total documents: {len(documents)}")
    print(f"   - Processed documents: {len(processed_docs)}")
    
    if not processed_docs:
        print("❌ No processed documents found. Documents need to be processed first.")
        return False
    
    # Step 5: Test RAG query first
    print(f"\n4️⃣ Testing RAG query...")
    rag_data = {
        "question": "What are the main topics covered in this subject?",
        "subject_id": subject_id
    }
    response = requests.post(f"{BASE_URL}/rag/query", json=rag_data, headers=headers)
    if response.status_code == 200:
        rag_result = response.json()
        print(f"✅ RAG query successful:")
        print(f"   - Answer length: {len(rag_result.get('answer', ''))}")
        print(f"   - Sources: {len(rag_result.get('sources', []))}")
        print(f"   - Confidence: {rag_result.get('confidence', 0)}")
    else:
        print(f"❌ RAG query failed: {response.text}")
        return False
    
    # Step 6: Try paper generation with minimal parameters
    print(f"\n5️⃣ Testing paper generation...")
    paper_data = {
        "subject_id": subject_id,
        "title": "Debug Test Paper",
        "question_count": 3,  # Start small
        "question_types": ["mcq", "short_answer"],
        "difficulty_level": "easy"
    }
    
    response = requests.post(f"{BASE_URL}/papers/generate", json=paper_data, headers=headers)
    if response.status_code == 200:
        paper = response.json()
        print(f"✅ Paper generation successful!")
        print(f"   - Paper ID: {paper['id']}")
        print(f"   - Questions generated: {len(paper['questions'])}")
        print(f"   - Total marks: {paper['total_marks']}")
        
        # Show first question
        if paper['questions']:
            q1 = paper['questions'][0]
            print(f"\n📝 First question:")
            print(f"   - Text: {q1.get('question_text', 'No text')[:100]}...")
            print(f"   - Type: {q1.get('question_type')}")
            print(f"   - Answer: {q1.get('correct_answer', 'No answer')}")
        
        return True
    else:
        print(f"❌ Paper generation failed:")
        try:
            error_data = response.json()
            print(f"   - Status: {response.status_code}")
            print(f"   - Error: {error_data.get('error', 'Unknown error')}")
            print(f"   - Detail: {error_data.get('detail', 'No details')}")
        except:
            print(f"   - Raw response: {response.text}")
        return False

def check_database_directly():
    """Check database state directly via API"""
    print("\n🔍 Checking Database State")
    print("=" * 30)
    
    # This would require direct database access or special debug endpoints
    print("ℹ️  To check database directly, you would need:")
    print("   - Access to Supabase dashboard")
    print("   - Or create debug endpoints to query doc_chunks table")
    print("   - Check if embeddings are properly stored")

if __name__ == "__main__":
    print("🚀 Starting Paper Generation Debug")
    print("=" * 60)
    
    try:
        success = debug_paper_generation()
        
        if not success:
            print("\n🔧 Troubleshooting Steps:")
            print("1. Ensure documents are uploaded and processed")
            print("2. Check if RAG queries work")
            print("3. Verify embeddings are generated")
            print("4. Check server logs for detailed errors")
            
        check_database_directly()
        
    except Exception as e:
        print(f"\n💥 Debug failed with error: {e}")
        import traceback
        traceback.print_exc()
