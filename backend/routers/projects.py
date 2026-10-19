from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

# Import your database and models
from database import get_db
from models import Project, User

# Import schemas (Ensure you created schemas/projects.py as discussed)
from schemas.projects import ProjectCreate, ProjectResponse

# Import security dependency
from utils.dependencies import get_current_user, get_admin_user

# Define the Router
router = APIRouter(
    prefix="/projects",  # This sets the URL to /api/projects (if included with /api prefix)
    tags=["Projects"]
)

# 1. GET ALL PROJECTS (Used by User Demo & Admin Dashboard)
@router.get("", response_model=List[ProjectResponse])
def get_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Fetch all active projects."""
    return db.query(Project).all()

# 2. CREATE PROJECT (Used by Admin Dashboard)
@router.post("", response_model=ProjectResponse)
def create_project(
    project: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user)
):
    """Create a new project (Admin only)."""

    # Check for duplicate name
    existing_project = db.query(Project).filter(Project.name == project.name).first()
    if existing_project:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Project with this name already exists"
        )

    new_project = Project(name=project.name)
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    return new_project

# 3. DELETE PROJECT (Used by Admin Dashboard)
@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_admin_user)
):
    """Delete a project permanently (Admin only)."""

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    db.delete(project)
    db.commit()
    return {"message": "Project deleted successfully"}