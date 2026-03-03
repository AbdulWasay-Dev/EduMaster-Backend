#!/usr/bin/env python3
"""
Debug script to check chunks in database
"""
import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.supabase_client import get_supabase_service

async def check_chunks():
    """Check what chunks exist in the database"""
    print("🔍 Checking chunks in database...")
    
    supabase = get_supabase_service()
    
    try:
        # Get all chunks
        response = supabase.service_client.table("doc_chunks").select("*").limit(5).execute()
        
        if response.data:
            print(f"✅ Found {len(response.data)} chunks (showing first 5)")
            for i, chunk in enumerate(response.data):
                print(f"\nChunk {i+1}:")
                print(f"  - ID: {chunk.get('id')}")
                print(f"  - Subject ID: {chunk.get('subject_id')}")
                print(f"  - Document ID: {chunk.get('document_id')}")
                
                # Check which text field exists
                if 'text' in chunk:
                    print(f"  - Text (first 100 chars): {chunk['text'][:100]}...")
                elif 'chunk_text' in chunk:
                    print(f"  - Chunk Text (first 100 chars): {chunk['chunk_text'][:100]}...")
                else:
                    print(f"  - No text field found! Available fields: {list(chunk.keys())}")
                
                # Check embedding field
                if 'embedding' in chunk:
                    print(f"  - Has embedding: Yes (type: {type(chunk['embedding'])})")
                elif 'chunk_embedding' in chunk:
                    print(f"  - Has chunk_embedding: Yes (type: {type(chunk['chunk_embedding'])})")
                else:
                    print(f"  - No embedding field found!")
        else:
            print("❌ No chunks found in database")
            
            # Check if documents exist
            docs_response = supabase.service_client.table("documents").select("*").execute()
            if docs_response.data:
                print(f"📄 Found {len(docs_response.data)} documents:")
                for doc in docs_response.data:
                    print(f"  - {doc.get('filename', 'Unknown')} (Status: {doc.get('processing_status', 'Unknown')})")
            else:
                print("📄 No documents found either")
                
    except Exception as e:
        print(f"❌ Error checking chunks: {e}")

if __name__ == "__main__":
    asyncio.run(check_chunks())
