from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import List

MAX_OBJECTIVES = 10
MAX_OBJECTIVE_LEN = 500

# 1. Validation for CREATING a project (Input)
class ProjectCreate(BaseModel):
    name: str
    objectives: List[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Project name is required")
        return value

    @field_validator("objectives")
    @classmethod
    def clean_objectives(cls, value: List[str]) -> List[str]:
        value = list(dict.fromkeys(o.strip() for o in value if o.strip()))  # no blanks or repeats
        if len(value) > MAX_OBJECTIVES:
            raise ValueError(f"At most {MAX_OBJECTIVES} objectives")
        if any(len(o) > MAX_OBJECTIVE_LEN for o in value):
            raise ValueError(f"Each objective must be at most {MAX_OBJECTIVE_LEN} characters")
        return value

# 2. Validation for READING a project (Output)
class ProjectResponse(BaseModel):
    id: int
    name: str
    objectives: List[str] = []
    created_at: datetime

    class Config:
        from_attributes = True
