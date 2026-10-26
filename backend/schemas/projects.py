from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime
from typing import List

MAX_OBJECTIVES = 10
MAX_OBJECTIVE_LEN = 500

def clean_objectives(value: List[str]) -> List[str]:
    value = list(dict.fromkeys(o.strip() for o in value if o.strip()))  # no blanks or repeats
    if len(value) > MAX_OBJECTIVES:
        raise ValueError(f"At most {MAX_OBJECTIVES} objectives")
    if any(len(o) > MAX_OBJECTIVE_LEN for o in value):
        raise ValueError(f"Each objective must be at most {MAX_OBJECTIVE_LEN} characters")
    return value

# 1. Validation for CREATING a project (Input)
class ProjectCreate(BaseModel):
    name: str
    objectives: List[str] = Field(default_factory=list)
    is_private: bool = False

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project name is required")
        return value

    @field_validator("objectives")
    @classmethod
    def check_objectives(cls, value: List[str]) -> List[str]:
        return clean_objectives(value)

class ProjectObjectives(BaseModel):
    objectives: List[str] = Field(default_factory=list)

    @field_validator("objectives")
    @classmethod
    def check_objectives(cls, value: List[str]) -> List[str]:
        return clean_objectives(value)

class ProjectShare(BaseModel):
    emails: List[EmailStr] = Field(default_factory=list, max_length=50)

# 2. Validation for READING a project (Output)
class ProjectResponse(BaseModel):
    id: int
    name: str
    objectives: List[str] = []
    is_private: bool = False
    locked: bool = False  # private, and this session cannot unlock its key
    is_owner: bool = False
    shared_with: List[str] = []  # emails; only filled in for the owner
    created_at: datetime

    @classmethod
    def for_user(cls, project, user) -> "ProjectResponse":
        from utils.keys import project_key
        is_owner = project.owner_id == user.id
        return cls(
            id=project.id,
            name=project.name,
            objectives=project.objectives or [],
            is_private=project.is_private,
            locked=project.is_private and project_key(project.id) is None,
            is_owner=is_owner,
            shared_with=[u.email for u in project.shared_with] if is_owner else [],
            created_at=project.created_at,
        )
