from sqlalchemy import Column, Integer, String, Float, Index
from database import Base


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Float, nullable=False)
    project = Column(String(255), nullable=False)
    client_id = Column(String(255), nullable=False)
    comments_count = Column(Integer, nullable=False)
    operation_type = Column(String(50), nullable=False)

    __table_args__ = (
        Index("ix_usage_records_timestamp", "timestamp"),
        Index("ix_usage_records_project", "project"),
    )