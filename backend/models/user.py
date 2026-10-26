from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base
from utils.crypto import EncryptedText
from models.role import user_roles  # Import the association table

class User(Base):
    __tablename__ = "users"
    
    # Primary fields
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    
    # Authentication methods
    hashed_password = Column(String(255), nullable=True)
    google_id = Column(String(255), unique=True, nullable=True, index=True)
    auth_provider = Column(String(20), default="email")
    
    # Profile
    name = Column(String(255), nullable=True)
    picture_url = Column(Text, nullable=True)
    
    # Email verification
    email_verified = Column(Boolean, default=False)
    verification_token = Column(String(255), unique=True, nullable=True)
    verification_token_expires = Column(DateTime(timezone=True), nullable=True)

    # --- ADD THESE TWO LINES ---
    reset_token_hash = Column(String(255), unique=True, nullable=True, index=True)
    reset_token_expires = Column(DateTime(timezone=True), nullable=True)
    
    # 2FA
    two_factor_secret = Column(EncryptedText, nullable=True)
    two_factor_enabled = Column(Boolean, default=False)
    backup_codes = Column(Text, nullable=True)

    # Personal key for private projects (utils/keys.py): an X25519 key pair whose
    # private half is locked with the password, and again with a recovery code.
    public_key = Column(String(64), nullable=True)
    private_key_enc = Column(Text, nullable=True)
    private_key_recovery = Column(Text, nullable=True)
    key_salt = Column(String(64), nullable=True)
    
    # Security
    is_active = Column(Boolean, default=True)
    # 🔥 REMOVE is_admin - we'll use roles instead
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
    
    # 🔥 NEW: Relationships
    roles = relationship("Role", secondary=user_roles, back_populates="users")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    activity_logs = relationship("ActivityLog", back_populates="user", cascade="all, delete-orphan")

    # One account per email whatever the letter case (migration 0005).
    __table_args__ = (Index("ux_users_email_lower", func.lower(email), unique=True),)
    
    # 🔥 NEW: Helper methods
    def has_role(self, role_name: str) -> bool:
        """Check if user has a specific role"""
        return any(role.name == role_name for role in self.roles)
    
    def has_permission(self, permission_name: str) -> bool:
        """Check if user has a specific permission"""
        for role in self.roles:
            if any(perm.name == permission_name for perm in role.permissions):
                return True
        return False
    
    def get_role_names(self) -> list[str]:
        """Get list of role names"""
        return [role.name for role in self.roles]
    
    def get_permission_names(self) -> list[str]:
        """Get list of all permissions from all roles"""
        permissions = set()
        for role in self.roles:
            for perm in role.permissions:
                permissions.add(perm.name)
        return list(permissions)
    
    def __repr__(self):
        return f"<User {self.email}>"