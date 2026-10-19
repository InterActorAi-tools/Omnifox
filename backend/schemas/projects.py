from pydantic import BaseModel
from datetime import datetime

# 1. Validation for CREATING a project (Input)
class ProjectCreate(BaseModel):
    name: str

# 2. Validation for READING a project (Output)
class ProjectResponse(BaseModel):
    id: int
    name: str
    created_at: datetime

    class Config:
        from_attributes = True