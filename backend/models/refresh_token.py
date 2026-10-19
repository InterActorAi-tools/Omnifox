from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base
from utils.crypto import EncryptedText

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    
    device_name = Column(EncryptedText, nullable=True)
    ip_address = Column(EncryptedText, nullable=True)
    user_agent = Column(EncryptedText, nullable=True)
    
    is_revoked = Column(Boolean, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used = Column(DateTime(timezone=True), server_default=func.now())
    
    user = relationship("User", back_populates="refresh_tokens")
    
    def __repr__(self):
        return f"<RefreshToken {self.id} for User {self.user_id}>"