from sqlalchemy import Column, Integer, String, DateTime, JSON
from datetime import datetime, timezone  # <--- 1. Import timezone
from database import Base

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    # Comms campaign objectives, one string each; comments are scored against them.
    objectives = Column(JSON, nullable=False, default=list)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
