import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
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
    SECRET_KEY: str = Field(default="supersecretauditkeyday1", description="JWT secret key")
    ALGORITHM: str = Field(default="HS256", description="JWT Algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()

# Ensure storage directory exists
settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
