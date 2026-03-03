"""
Example usage of the enhanced grading system with Mistral OCR
"""
import asyncio
import base64
import os
from typing import List

# Example of how to use the new grading system

async def example_single_image_grading():
    """Example: Grade a single handwritten answer sheet"""
    
    # 1. Prepare your image (convert to base64)
    image_path = "path/to/your/answer_sheet.jpg"
    
    # Convert image to base64
    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    # 2. Call the grading API
    from services.answer_sheet_grading import get_answer_sheet_grading_service
    
    grading_service = get_answer_sheet_grading_service()
    
    result = await grading_service.process_answer_sheet(
        paper_id="your-paper-id",
        student_id="your-student-id", 
        answer_sheet_image=base64_image,
        grading_mode="auto",  # or "semi_auto", "manual"
        strictness="medium"   # or "lenient", "strict"
    )
    
    if result:
        print(f"✅ Grading completed!")
        print(f"Submission ID: {result['submission_id']}")
        print(f"Total Score: {result['total_score']}")
        print(f"Grade Percentage: {result['grade_percentage']}%")
        print(f"Feedback: {result['feedback']}")
        print(f"OCR Confidence: {result['ocr_confidence']}")
    else:
        print("❌ Grading failed")


async def example_multiple_image_grading():
    """Example: Grade multiple pages of handwritten answer sheets"""
    
    # 1. Prepare multiple images
    image_paths = [
        "path/to/page1.jpg",
        "path/to/page2.jpg", 
        "path/to/page3.jpg"
    ]
    
    base64_images = []
    for image_path in image_paths:
        with open(image_path, "rb") as image_file:
            image_bytes = image_file.read()
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            base64_images.append(base64_image)
    
    # 2. Call the multiple image grading API
    from services.answer_sheet_grading import get_answer_sheet_grading_service
    
    grading_service = get_answer_sheet_grading_service()
    
    result = await grading_service.process_multiple_answer_sheets(
        paper_id="your-paper-id",
        student_id="your-student-id",
        answer_sheet_images=base64_images,
        grading_mode="auto",
        strictness="medium"
    )
    
    if result:
        print(f"✅ Multiple image grading completed!")
        print(f"Submission ID: {result['submission_id']}")
        print(f"Images Processed: {result['images_processed']}")
        print(f"Total Score: {result['total_score']}")
        print(f"Grade Percentage: {result['grade_percentage']}%")
        print(f"Overall OCR Confidence: {result['ocr_confidence']}")
        
        # Show individual OCR results
        for i, ocr_result in enumerate(result['individual_ocr_results']):
            print(f"Page {i+1} OCR Confidence: {ocr_result['confidence']}")
    else:
        print("❌ Multiple image grading failed")


async def example_direct_ocr_usage():
    """Example: Use OCR service directly for text extraction"""
    
    from services.ocr_service import get_ocr_service
    
    ocr_service = get_ocr_service()
    
    # Method 1: From image URL
    image_url = "https://example.com/your-image.jpg"
    result = await ocr_service.extract_text_from_image_url(image_url)
    
    if result:
        print(f"✅ OCR from URL successful!")
        print(f"Extracted text: {result['text']}")
        print(f"Confidence: {result['confidence']}")
    
    # Method 2: From base64 image
    image_path = "path/to/your/image.jpg"
    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    result = await ocr_service.extract_text_from_base64(base64_image)
    
    if result:
        print(f"✅ OCR from base64 successful!")
        print(f"Extracted text: {result['text']}")
        print(f"Confidence: {result['confidence']}")
    
    # Method 3: Process multiple images
    images_data = [
        {"id": "page1", "base64": base64_image},
        {"id": "page2", "base64": base64_image}  # Same image for demo
    ]
    
    results = await ocr_service.process_multiple_images(images_data)
    
    if results:
        combined_result = results[0]
        print(f"✅ Multiple image OCR successful!")
        print(f"Total images: {combined_result['total_images']}")
        print(f"Processed images: {combined_result['processed_images']}")
        print(f"Combined text length: {len(combined_result['combined_text'])}")
        print(f"Overall confidence: {combined_result['overall_confidence']}")


async def example_api_usage():
    """Example: How to call the API endpoints"""
    
    import requests
    import json
    
    # Example API call for single image grading
    api_url = "http://localhost:8000/api/v1/grading/upload-answer-sheet"
    
    headers = {
        "Authorization": "Bearer your-jwt-token",
        "Content-Type": "application/json"
    }
    
    # Prepare image
    image_path = "path/to/answer_sheet.jpg"
    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    payload = {
        "paper_id": "your-paper-id",
        "student_id": "your-student-id",
        "answer_sheet_image": base64_image,
        "grading_mode": "auto",
        "strictness": "medium"
    }
    
    # Make API call
    response = requests.post(api_url, headers=headers, json=payload)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ API call successful!")
        print(f"Submission ID: {result['submission_id']}")
        print(f"Total Score: {result['total_score']}")
        print(f"Grade Percentage: {result['grade_percentage']}%")
    else:
        print(f"❌ API call failed: {response.status_code}")
        print(f"Error: {response.text}")
    
    # Example API call for multiple images
    api_url_multiple = "http://localhost:8000/api/v1/grading/upload-multiple-answer-sheets"
    
    # Prepare multiple images
    image_paths = ["page1.jpg", "page2.jpg", "page3.jpg"]
    base64_images = []
    
    for image_path in image_paths:
        with open(image_path, "rb") as image_file:
            image_bytes = image_file.read()
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            base64_images.append(base64_image)
    
    payload_multiple = {
        "paper_id": "your-paper-id",
        "student_id": "your-student-id",
        "answer_sheet_images": base64_images,
        "grading_mode": "auto",
        "strictness": "medium"
    }
    
    response = requests.post(api_url_multiple, headers=headers, json=payload_multiple)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Multiple image API call successful!")
        print(f"Images Processed: {result.get('images_processed', 0)}")
        print(f"Total Score: {result['total_score']}")
    else:
        print(f"❌ Multiple image API call failed: {response.status_code}")


def setup_environment():
    """Setup instructions for the enhanced grading system"""
    
    print("🚀 Enhanced Grading System Setup Instructions")
    print("=" * 50)
    
    print("\n1. Environment Variables Required:")
    print("   - MISTRAL_API_KEY: Your Mistral API key for OCR")
    print("   - GOOGLE_API_KEY: Your Google API key for LLM grading")
    print("   - SUPABASE_URL: Your Supabase project URL")
    print("   - SUPABASE_ANON_KEY: Your Supabase anonymous key")
    
    print("\n2. Install Dependencies:")
    print("   pip install mistralai google-generativeai fastapi supabase")
    
    print("\n3. Database Setup:")
    print("   - Run the enhanced_grading_schema.sql to update your database")
    print("   - This adds new tables for image processing and detailed grading")
    
    print("\n4. API Endpoints Available:")
    print("   - POST /api/v1/grading/upload-answer-sheet")
    print("   - POST /api/v1/grading/upload-multiple-answer-sheets")
    print("   - POST /api/v1/grading/upload-multiple-files")
    print("   - GET /api/v1/grading/{submission_id}/result")
    
    print("\n5. Features:")
    print("   ✅ Mistral OCR for handwritten text recognition")
    print("   ✅ Multiple image processing")
    print("   ✅ AI-powered grading with Gemini")
    print("   ✅ Detailed grading results and feedback")
    print("   ✅ Confidence scoring")
    print("   ✅ Audit trail and analytics")
    
    print("\n6. Usage Examples:")
    print("   - See example_grading_usage.py for code examples")
    print("   - Run test_enhanced_grading.py to test the system")


if __name__ == "__main__":
    print("Enhanced Grading System Examples")
    print("=" * 40)
    
    # Show setup instructions
    setup_environment()
    
    # Uncomment to run examples (requires proper setup)
    # asyncio.run(example_single_image_grading())
    # asyncio.run(example_multiple_image_grading())
    # asyncio.run(example_direct_ocr_usage())
    # asyncio.run(example_api_usage())
