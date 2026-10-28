"""Configuration for OmniFox, read from environment variables (and a local .env file)."""
import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from typing import List

# Load environment variables from a local .env file when running outside Docker.
# In containers, env vars are injected by docker-compose and this is a no-op.
load_dotenv()

class Settings(BaseSettings):
    """Application settings with production optimizations"""
    
    # API Keys
    gemini_api_key: str = ""
    exportcomments_api_key: str = ""
    # The ExportComments key is shared with OmniCat (5 jobs at once on our plan).
    exportcomments_max_concurrent: int = 2

    # Auth
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./omnifox.db")
    jwt_secret_key: str = ""
    # Fernet key(s) for personal data at rest. Comma-separated: the first
    # encrypts, all decrypt (lets you rotate keys).
    data_encryption_key: str = ""
    jwt_algorithm: str = "HS256"
    # L1: 15-minute access tokens. The refresh-token rotation flow (H1)
    # automatically extends the session as long as the user is active,
    # so the visible UX impact is zero - what changes is the window
    # during which a stolen access token can be replayed.
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    google_client_id: str = ""
    resend_api_key: str = ""

    # Public base URL of the frontend. Used to build user-visible links
    # (invitation links, password-reset links). Must be https in
    # production. Previously these were derived from the `Origin` request
    # header (H12 - phishing primitive) or hardcoded to staging (M11) -
    # both wrong. Set this per-environment via FRONTEND_URL.
    frontend_url: str = ""
    
    # FastAPI Settings
    app_title: str = "OMNIFOX"
    app_version: str = "3.1.0"  
    debug: bool = False
    
    # CORS Settings - overridden at runtime by the CORS_ORIGINS env var
    # (comma-separated list). The defaults below cover local dev only.
    cors_origins: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]
    
    # File Storage
    upload_folder: str = "uploads"
    max_file_size: int = 50 * 1024 * 1024  # 50MB

    # Gemini API Settings
    gemini_model: str = "gemini-3.1-flash-lite"  # Primary model
    gemini_fallback_model: str = "gemini-2.5-flash"  # Fallback model
    
    # Performance Settings
    max_concurrent_requests: int = 100  # Paid tier: increased for throughput
    max_workers: int = 20
    request_timeout: int = 120  # seconds; per Gemini HTTP call (summaries can be large)

    def __init__(self, **kwargs):
        # Pydantic auto-binds `CORS_ORIGINS` as JSON for a List[str] field, which
        # breaks our comma-separated convention. Hide it from Pydantic, then
        # parse it ourselves below.
        cors_env = os.environ.pop("CORS_ORIGINS", "").strip()

        super().__init__(**kwargs)

        # Load API keys from environment
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "")
        self.exportcomments_api_key = os.getenv("EXPORTCOMMENTS_API_KEY", "")
        
        # Load auth settings from environment
        self.jwt_secret_key = os.getenv("JWT_SECRET_KEY", "")
        self.data_encryption_key = os.getenv("DATA_ENCRYPTION_KEY", "")
        self.google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        self.resend_api_key = os.getenv("RESEND_API_KEY", "")
        self.frontend_url = os.getenv("FRONTEND_URL", "").rstrip("/")

        # Load other environment variables
        self.debug = os.getenv("DEBUG", "False").lower() == "true"

        # CORS origins from env (comma-separated, captured above before
        # super().__init__). Falls back to the dev defaults on the class.
        if cors_env:
            self.cors_origins = [origin.strip() for origin in cors_env.split(",") if origin.strip()]
        
        environment = os.getenv("ENVIRONMENT", "development").lower()
        if environment == "production":
            self.debug = False
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode"""
        return not self.debug
    
    class Config:
        # No env_file: load_dotenv() above already loads .env, and pydantic
        # reading it again would parse a comma-separated CORS_ORIGINS as JSON.
        case_sensitive = False
        extra = "ignore"

settings = Settings()

# Validate required settings
if not settings.gemini_api_key:
    raise ValueError("Gemini API key not found. Set the `GEMINI_API_KEY` environment variable (or define it in .env for local dev).")

if not settings.exportcomments_api_key:
    raise ValueError("ExportComments API key not found. Set the `EXPORTCOMMENTS_API_KEY` environment variable (or define it in .env for local dev).")

if not settings.jwt_secret_key:
    raise ValueError("JWT signing key not found. Set the `JWT_SECRET_KEY` environment variable (or define it in .env for local dev). Use a high-entropy random value, e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`.")

if not settings.data_encryption_key:
    raise ValueError("DATA_ENCRYPTION_KEY is not set. Generate one with `python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` and keep it safe: data encrypted with it cannot be read without it.")

# FRONTEND_URL drives every user-visible link the backend sends (invite
# emails, password-reset emails). If unset, invitations get phishable
# defaults (H12) and reset emails point at staging (M11). Hard-fail at
# boot so the misconfiguration is loud.
if not settings.frontend_url:
    raise ValueError("FRONTEND_URL is not set. This must be the public https URL of the frontend (e.g. https://omnifox.example.com).")
if settings.is_production and not settings.frontend_url.startswith("https://"):
    raise ValueError("FRONTEND_URL must use https:// in production.")

# Create necessary directories
Path(settings.upload_folder).mkdir(exist_ok=True)

# Export commonly used values
UPLOAD_FOLDER = settings.upload_folder
GEMINI_API_KEY = settings.gemini_api_key
EXPORTCOMMENTS_API_KEY = settings.exportcomments_api_key
EXPORTCOMMENTS_MAX_CONCURRENT = settings.exportcomments_max_concurrent
GEMINI_MODEL = settings.gemini_model
GEMINI_FALLBACK_MODEL = settings.gemini_fallback_model
