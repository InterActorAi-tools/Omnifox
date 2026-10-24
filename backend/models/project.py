from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Table
from sqlalchemy.orm import relationship
from datetime import datetime, timezone  # <--- 1. Import timezone
from database import Base
from utils.crypto import EncryptedJSON

# Users a private project is shared with (besides its owner).
project_shares = Table(
    "project_shares",
    Base.metadata,
    Column("project_id", Integer, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    # Comms campaign objectives, one string each; comments are scored against them.
    objectives = Column(EncryptedJSON, nullable=False, default=list)

    # A private project is visible only to its owner and the users it is shared with.
    is_private = Column(Boolean, nullable=False, default=False)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    owner = relationship("User")
    shared_with = relationship("User", secondary=project_shares)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def can_access(self, user) -> bool:
        return not self.is_private or self.owner_id == user.id or user in self.shared_with
