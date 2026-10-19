"""API router: mounts the upload, task and analytics routers."""
from fastapi import APIRouter
from .upload import router as upload_router
from .tasks import router as tasks_router
from .enhanced_analytics import router as enhanced_analytics_router  # Updated import

# Create a main router that includes all sub-routers
api_router = APIRouter()

# Include all route modules with their prefixes and tags
api_router.include_router(
    upload_router, 
    prefix="/upload", 
    tags=["File Upload"],
    responses={404: {"description": "Not found"}}
)

api_router.include_router(
    tasks_router, 
    prefix="/tasks", 
    tags=["Task Management"],
    responses={404: {"description": "Not found"}}
)

api_router.include_router(
    enhanced_analytics_router,  # Updated router
    prefix="/analytics", 
    tags=["Enhanced Analytics"]
)
