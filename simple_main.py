"""
Simple FastAPI application for testing
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Create FastAPI app
app = FastAPI(
    title="EduMaster Backend",
    description="Educational RAG System API",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "EduMaster Backend is running!", "status": "success"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "message": "API is working"}

@app.get("/api/v1/test")
async def test_endpoint():
    """Test endpoint"""
    return {"message": "API v1 is working", "data": {"version": "1.0.0"}}

if __name__ == "__main__":
    print("🚀 Starting EduMaster Backend...")
    print("📖 API Documentation: http://localhost:8010/docs")
    print("🔍 Health Check: http://localhost:8010/health")
    uvicorn.run(app, host="0.0.0.0", port=8010, reload=True)
