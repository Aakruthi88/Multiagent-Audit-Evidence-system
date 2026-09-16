import os
from pathlib import Path
from typing import List, Union
from pydantic_settings import BaseSettings
from pydantic import ConfigDict, Field, field_validator


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    PROJECT_NAME: str = "Multi-Agent Audit Evidence Assistant"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = Field(
        default="sqlite:///./audit_db.db",
        description="PostgreSQL or SQLite database connection URL"
    )
    
    # LLM Services
    GEMINI_API_KEY: str = Field(default="", description="Google Gemini API Key")
    GEMINI_MODEL: str = Field(default="gemini-3.6-flash", description="Google Gemini Model")

    OPENROUTER_API_KEY: str = Field(default="", description="OpenRouter API Key")
    OPENROUTER_MODEL: str = Field(default="meta-llama/llama-3.1-8b-instruct:free", description="Primary OpenRouter Model (free tier)")
    OPENROUTER_BASE_URL: str = Field(default="https://openrouter.ai/api/v1", description="OpenRouter Base URL")
    
    OLLAMA_HOST: str = Field(default="http://localhost:11434", description="Ollama local host URL")
    OLLAMA_MODEL: str = Field(default="qwen2.5:3b", description="Ollama model fallback")
    
    # Storage
    STORAGE_DIR: Path = Field(
        default=Path("./storage"),
        description="Directory to store uploaded PDF files"
    )
    
    # Security
    SECRET_KEY: str = Field(
        default=os.getenv("SECRET_KEY", "deloitte_audit_system_super_secure_jwt_secret_key_2026"),
        description="JWT secret key"
    )
    ALGORITHM: str = Field(default="HS256", description="JWT Algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    
    # CORS Origins (no wildcard in production)
    CORS_ORIGINS: List[str] = Field(
        default=[
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ],
        description="Allowed CORS origins"
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)


settings = Settings()

# Ensure storage directory exists
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
