from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base
from utils.crypto import EncryptedJSON, EncryptedText

class ActivityLog(Base):
    __tablename__ = "activity_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    
    action = Column(String, index=True)
    ip_address = Column(EncryptedText, nullable=True)
    user_agent = Column(EncryptedText, nullable=True)
    extra_data = Column(EncryptedJSON, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    
    user = relationship("User", back_populates="activity_logs")

    __table_args__ = (
        Index("ix_activity_logs_user_id_created_at", "user_id", "created_at"),
    )
    
    def __repr__(self):
        return f"<ActivityLog {self.action} by User {self.user_id}>"
    
    def to_dict(self):
        """Convert to dictionary for serialization"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_email": self.user.email if self.user else "System",
            "user_name": self.user.name if self.user else "System",
            "action": self.action,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "details": self.extra_data,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }