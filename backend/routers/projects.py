from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session
from typing import List

# Import your database and models
from database import get_db
from models import Project, User

# Import schemas (Ensure you created schemas/projects.py as discussed)
from schemas.projects import ProjectCreate, ProjectResponse, ProjectShare
from services.privacy import delete_project

# Import security dependency
from utils.dependencies import find_user_by_email, get_current_user, log_activity


# Define the Router
router = APIRouter(
    prefix="/projects",  # This sets the URL to /api/projects (if included with /api prefix)
    tags=["Projects"]
)


def visible_projects(db: Session, user: User):
    """Shared projects, plus private ones the user owns or was given access to."""
    return db.query(Project).filter(or_(
        Project.is_private == False,  # noqa: E712
        Project.owner_id == user.id,
        Project.shared_with.any(User.id == user.id),
    ))


def require_project_access(db: Session, user: User, name: str) -> None:
    """Refuse a private project the user cannot see, as if it did not exist."""
    project = db.query(Project).filter(Project.name == name).first()
    if project and not project.can_access(user):
        raise HTTPException(status_code=404, detail="Project not found")


def _visible_project(db: Session, user: User, project_id: int) -> Project:
    project = visible_projects(db, user).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# 1. GET ALL PROJECTS (Used by User Demo & Admin Dashboard)
@router.get("", response_model=List[ProjectResponse])
def get_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Projects this user can see. Admins do not see other people's private projects."""
    return [ProjectResponse.for_user(p, current_user) for p in visible_projects(db, current_user).all()]

# 2. CREATE PROJECT (Used by Admin Dashboard)
@router.post("", response_model=ProjectResponse)
def create_project(
    project: ProjectCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Admins create shared projects; project managers create private ones."""
    if project.is_private and not current_user.has_permission("create_private_projects"):
        raise HTTPException(status_code=403, detail="You cannot create private projects")
    if not project.is_private and not current_user.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Check for duplicate name
    existing_project = db.query(Project).filter(Project.name == project.name).first()
    if existing_project:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project with this name already exists"
        )

    new_project = Project(name=project.name, objectives=project.objectives,
                          is_private=project.is_private, owner_id=current_user.id)
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    log_activity(db, current_user.id, "project_created", request.client.host, None,
                 {"project": new_project.name, "private": new_project.is_private})
    return ProjectResponse.for_user(new_project, current_user)

# 3. SHARE A PRIVATE PROJECT (owner only)
@router.put("/{project_id}/shares", response_model=ProjectResponse)
def share_project(
    project_id: int,
    share: ProjectShare,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Replace the list of people a private project is shared with."""
    project = _visible_project(db, current_user, project_id)
    if not project.is_private or project.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can share a private project")

    users = []
    for email in share.emails:
        user = find_user_by_email(db, email)
        if not user:
            raise HTTPException(status_code=404, detail=f"No user with email {email}")
        if user.id != current_user.id and user not in users:
            users.append(user)

    project.shared_with = users
    db.commit()
    log_activity(db, current_user.id, "project_shared", request.client.host, None,
                 {"project": project.name, "shared_with": [u.email for u in users]})
    return ProjectResponse.for_user(project, current_user)

# 4. DELETE PROJECT (Used by Admin Dashboard)
@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Admins delete shared projects; only the owner deletes a private one."""
    project = _visible_project(db, current_user, project_id)
    allowed = project.owner_id == current_user.id if project.is_private else current_user.has_role("admin")
    if not allowed:
        raise HTTPException(status_code=403, detail="You cannot delete this project")

    name = project.name
    delete_project(db, project)
    log_activity(db, current_user.id, "project_deleted", request.client.host, None, {"project": name})
    return {"message": "Project deleted successfully"}
