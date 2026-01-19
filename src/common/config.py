"""Configuration management using Pydantic Settings.

Loads environment variables from .env file and provides defaults for development.
"""

from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """Application configuration loaded from environment variables.

    All critical settings have defaults suitable for local development.
    Production deployments should override via environment.
    """

    # Database
    DATABASE_URL: str = "postgresql://agent:password@localhost:5432/agent_deploy"
    """PostgreSQL connection string for state persistence."""

    # RabbitMQ
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"
    """RabbitMQ connection string for message bus."""

    # API Keys
    ANTHROPIC_API_KEY: str = ""
    """Anthropic Claude API key (optional, uses LiteLLM if configured)."""

    OPENAI_API_KEY: str = ""
    """OpenAI API key (optional, uses LiteLLM if configured)."""

    # LiteLLM
    LITELLM_MASTER_KEY: str = "dev-key-for-local-testing"
    """Master key for LiteLLM service access."""

    LITELLM_URL: str = "http://localhost:8001"
    """LiteLLM service URL for LLM API access."""

    # Ollama (local LLM)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    """Ollama service URL for local model inference."""

    # Logging
    LOG_LEVEL: str = "INFO"
    """Python logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""

    # Application
    APP_NAME: str = "Chiffon Agent Deploy"
    """Application name for branding."""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
