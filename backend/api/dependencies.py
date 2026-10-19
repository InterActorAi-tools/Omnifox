"""FastAPI dependencies for Omnicat."""
from services.processing import ProcessingService


def get_processing_service() -> ProcessingService:
    """Get processing service"""
    return ProcessingService()
