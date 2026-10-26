from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime
from typing import Optional, List
import csv
import io
import json

from database import get_db
from models import User, ActivityLog
from schemas.auth import ActivityLogResponse, ActivityLogStats, activity_log_to_response
from utils.dependencies import get_current_user, get_admin_user

router = APIRouter(prefix="/activity-logs", tags=["Activity Logs"])


def _csv_safe(row: list) -> list:
    """Neutralize spreadsheet formulas in exported cells. User agents and
    logged URLs are user-controlled, and Excel evaluates cells starting
    with = + - @ (or a tab / carriage return)."""
    return [
        f"'{value}" if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
        for value in row
    ]

@router.get("/me", response_model=List[ActivityLogResponse])
def get_my_activity(
    action: Optional[str] = Query(None, description="Filter by action type"),
    start_date: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date (ISO format)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get current user's activity logs with filters"""
    
    query = db.query(ActivityLog).filter(ActivityLog.user_id == current_user.id)
    
    # Apply filters
    if action:
        query = query.filter(ActivityLog.action == action)
    
    if start_date:
        query = query.filter(ActivityLog.created_at >= start_date)
    
    if end_date:
        query = query.filter(ActivityLog.created_at <= end_date)
    
    # Order by newest first
    query = query.order_by(desc(ActivityLog.created_at))
    
    # Pagination
    activities = query.offset(offset).limit(limit).all()
    
    # Use helper function
    return [activity_log_to_response(log) for log in activities]

@router.get("/me/export")
def export_my_activity(
    action: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Export current user's activity to CSV"""
    
    query = db.query(ActivityLog).filter(ActivityLog.user_id == current_user.id)
    
    if action:
        query = query.filter(ActivityLog.action == action)
    if start_date:
        query = query.filter(ActivityLog.created_at >= start_date)
    if end_date:
        query = query.filter(ActivityLog.created_at <= end_date)
    
    activities = query.order_by(desc(ActivityLog.created_at)).all()
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow(['Date', 'Action', 'IP Address', 'User Agent', 'Details'])
    
    # Data
    for log in activities:
        writer.writerow(_csv_safe([
            log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.action,
            log.ip_address,
            log.user_agent or 'N/A',
            json.dumps(log.extra_data) if log.extra_data else 'N/A'
        ]))
    
    # Return CSV
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=activity_log_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )

@router.get("/me/stats", response_model=ActivityLogStats)
def get_my_activity_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get activity statistics for current user"""
    
    # Total activities
    total = db.query(func.count(ActivityLog.id)).filter(
        ActivityLog.user_id == current_user.id
    ).scalar()
    
    # Unique actions
    unique_actions = db.query(ActivityLog.action).filter(
        ActivityLog.user_id == current_user.id
    ).distinct().all()
    
    # Date range
    first_activity = db.query(func.min(ActivityLog.created_at)).filter(
        ActivityLog.user_id == current_user.id
    ).scalar()
    
    last_activity = db.query(func.max(ActivityLog.created_at)).filter(
        ActivityLog.user_id == current_user.id
    ).scalar()
    
    # Top actions (count by action type)
    top_actions = db.query(
        ActivityLog.action,
        func.count(ActivityLog.id).label('count')
    ).filter(
        ActivityLog.user_id == current_user.id
    ).group_by(ActivityLog.action).order_by(desc('count')).limit(5).all()
    
    return ActivityLogStats(
        total_activities=total,
        unique_actions=[action[0] for action in unique_actions],
        date_range={
            "first": first_activity.isoformat() if first_activity else None,
            "last": last_activity.isoformat() if last_activity else None
        },
        top_actions=[
            {"action": action, "count": count}
            for action, count in top_actions
        ]
    )

# Admin endpoints
@router.get("/all", response_model=List[ActivityLogResponse])
def get_all_activity(
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    action: Optional[str] = Query(None, description="Filter by action type"),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get all users' activity logs - Admin only"""
    
    query = db.query(ActivityLog).join(User, ActivityLog.user_id == User.id, isouter=True)
    
    # Apply filters
    if user_id:
        query = query.filter(ActivityLog.user_id == user_id)
    
    if action:
        query = query.filter(ActivityLog.action == action)
    
    if start_date:
        query = query.filter(ActivityLog.created_at >= start_date)
    
    if end_date:
        query = query.filter(ActivityLog.created_at <= end_date)
    
    # Order and paginate
    activities = query.order_by(desc(ActivityLog.created_at)).offset(offset).limit(limit).all()
    return [activity_log_to_response(log, admin_view=True) for log in activities]

@router.get("/all/export")
def export_all_activity(
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Export all users' activity to CSV - Admin only"""
    
    query = db.query(ActivityLog).join(User, ActivityLog.user_id == User.id, isouter=True)
    
    if user_id:
        query = query.filter(ActivityLog.user_id == user_id)
    if action:
        query = query.filter(ActivityLog.action == action)
    if start_date:
        query = query.filter(ActivityLog.created_at >= start_date)
    if end_date:
        query = query.filter(ActivityLog.created_at <= end_date)
    
    activities = query.order_by(desc(ActivityLog.created_at)).all()
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Headers
    writer.writerow(['Date', 'User Email', 'User Name', 'Action'])
    
    # Data
    for log in activities:
        writer.writerow(_csv_safe([
            log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.user.email if log.user else 'System',
            log.user.name if log.user else 'System',
            log.action,
        ]))
    
    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=all_activity_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )

@router.get("/actions")
def get_available_actions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of all available action types"""
    actions = db.query(ActivityLog.action).distinct().all()
    return {"actions": [action[0] for action in actions]}