"""
Enhanced analytics routes with date filtering support
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from models import User
from simple_analytics import enhanced_analytics
from utils.dependencies import get_dashboard_user

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/simple-stats")
def get_simple_stats_with_dates(
    start_date: Optional[str] = Query(None, description="Start date in ISO format (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date in ISO format (YYYY-MM-DD)"),
    preset: Optional[str] = Query(None, description="Preset range: last_7_days, last_30_days, last_60_days, last_90_days, this_month, last_month"),
    current_user: User = Depends(get_dashboard_user),
):
    """Get analytics stats with optional date filtering"""
    try:
        # Use preset if provided, otherwise use custom dates
        if preset:
            stats = enhanced_analytics.get_quick_preset_stats(preset)
        else:
            stats = enhanced_analytics.get_project_stats_filtered(start_date, end_date)
        
        return stats
        
    except Exception as e:
        logger.error(f"Error getting analytics stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get analytics")
