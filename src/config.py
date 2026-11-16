"""
DevResolve AI - Configuration
"""
import os
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # App
    app_url: str = os.getenv("APP_URL", "http://localhost:8000")
    secret_key: str = os.getenv("SECRET_KEY", "change-me-in-production-use-32-chars")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours

    # Database
    database_path: str = os.getenv("DATABASE_PATH", "data/devresolve.db")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/devresolve.db")

    # Google OAuth2
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")

    # Email / SMTP
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_enabled: bool = os.getenv("SMTP_ENABLED", "false").lower() in ("true", "1", "yes")
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    from_email: str = os.getenv("FROM_EMAIL", "noreply@devresolve.ai")

    # Groq
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # Google Embeddings
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
    gemini_embedding_model: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "google")
    embedding_dimension: int = int(os.getenv("EMBEDDING_DIMENSION", "768"))

    # Qdrant
    qdrant_url: str = os.getenv("QDRANT_URL", "")
    qdrant_api_key: str = os.getenv("QDRANT_API_KEY", "")
    qdrant_collection_name: str = os.getenv("QDRANT_COLLECTION_NAME", "devresolve_docs")

    # Self-RAG Controls
    top_k: int = int(os.getenv("TOP_K", "5"))
    max_support_retries: int = int(os.getenv("MAX_SUPPORT_RETRIES", "2"))
    max_retrieval_rewrites: int = int(os.getenv("MAX_RETRIEVAL_REWRITES", "2"))
    max_web_rewrites: int = int(os.getenv("MAX_WEB_REWRITES", "2"))

    # OTP
    otp_expire_minutes: int = int(os.getenv("OTP_EXPIRE_MINUTES", "10"))

    @property
    def database_file(self) -> Path:
        p = Path(self.database_path)
        return p if p.is_absolute() else ROOT / p

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
