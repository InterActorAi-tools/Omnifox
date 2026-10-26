"""Stats of one upload to a project, kept for the project's trends.

Only counts and percentages (no comments or file names), so they outlive the
30-day retention of the results themselves.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from database import Base
from utils.crypto import EncryptedJSON


class ProjectSnapshot(Base):
    __tablename__ = "project_snapshots"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(255), nullable=True, index=True)
    # {"total_comments", "sentiment_counts", "objectives": [{"objective", "relevant_comments", "supports", "percent_met"}]}
    stats = Column(EncryptedJSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
