"""Configuration management using Pydantic Settings.

Loads environment variables from .env file and provides defaults for development.
Also supports agent configuration from YAML files with environment variable overrides.
"""

import logging
import os
import socket
from pathlib import Path
from uuid import uuid4

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Config(BaseSettings):
    """Application configuration loaded from environment variables.

    All critical settings have defaults suitable for local development.
    Production deployments should override via environment.

    Also loads agent-specific settings from ~/.chiffon/agent.yml or /etc/chiffon/agent.yml.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

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

    # Desktop Agent: Heartbeat Settings
    heartbeat_interval_seconds: int = 30
    """How often to send status updates (seconds)."""

    heartbeat_timeout_seconds: int = 90
    """Mark agent offline after this many seconds without heartbeat."""

    # Desktop Agent: GPU Detection
    gpu_detection_timeout_seconds: int = 5
    """Max time to wait for GPU detection tools (nvidia-smi, pynvml)."""

    # Desktop Agent: Identification
    agent_id: str = ""
    """Agent unique identifier. Leave blank for auto-generate from hostname."""

    agent_pool_name: str = "desktop_pool_1"
    """Agent pool name for scheduling grouping."""

    # Application
    APP_NAME: str = "Chiffon Agent Deploy"
    """Application name for branding."""

    # Database Session (for testing and agent use)
    db_session: object = None
    """Database session for agent operations (used in testing)."""

    def __init__(self, **data) -> None:
        """Initialize config with environment and file-based overrides.

        Loads agent settings from:
        1. ~/.chiffon/agent.yml (user home)
        2. /etc/chiffon/agent.yml (system)
        3. Environment variables (CHIFFON_* prefix)
        """
        super().__init__(**data)
        self._load_agent_config()

    def _load_agent_config(self) -> None:
        """Load agent configuration from YAML file with env var overrides."""
        # Try to load from user home first, then system
        config_paths = [
            Path.home() / ".chiffon" / "agent.yml",
            Path("/etc/chiffon/agent.yml"),
        ]

        config_file_path = None
        for path in config_paths:
            if path.exists():
                config_file_path = path
                break

        # Load from file if found
        if config_file_path:
            try:
                with open(config_file_path) as f:
                    file_config = yaml.safe_load(f) or {}
                    logger.info(f"Loaded agent config from {config_file_path}")

                    # Apply file config to instance
                    if "heartbeat_interval_seconds" in file_config:
                        self.heartbeat_interval_seconds = file_config["heartbeat_interval_seconds"]

                    if "heartbeat_timeout_seconds" in file_config:
                        self.heartbeat_timeout_seconds = file_config["heartbeat_timeout_seconds"]

                    if "gpu_detection_timeout_seconds" in file_config:
                        self.gpu_detection_timeout_seconds = file_config[
                            "gpu_detection_timeout_seconds"
                        ]

                    if "agent_id" in file_config and file_config["agent_id"]:
                        self.agent_id = file_config["agent_id"]

                    if "agent_pool_name" in file_config:
                        self.agent_pool_name = file_config["agent_pool_name"]

            except (OSError, yaml.YAMLError) as e:
                logger.warning(f"Failed to load agent config from {config_file_path}: {e}")

        # Environment variable overrides (CHIFFON_* prefix takes precedence)
        if os.getenv("CHIFFON_HEARTBEAT_INTERVAL"):
            try:
                self.heartbeat_interval_seconds = int(os.getenv("CHIFFON_HEARTBEAT_INTERVAL"))
            except ValueError:
                logger.warning(
                    f"Invalid CHIFFON_HEARTBEAT_INTERVAL value: {os.getenv('CHIFFON_HEARTBEAT_INTERVAL')}"
                )

        if os.getenv("CHIFFON_HEARTBEAT_TIMEOUT"):
            try:
                self.heartbeat_timeout_seconds = int(os.getenv("CHIFFON_HEARTBEAT_TIMEOUT"))
            except ValueError:
                logger.warning(
                    f"Invalid CHIFFON_HEARTBEAT_TIMEOUT value: {os.getenv('CHIFFON_HEARTBEAT_TIMEOUT')}"
                )

        if os.getenv("CHIFFON_GPU_TIMEOUT"):
            try:
                self.gpu_detection_timeout_seconds = int(os.getenv("CHIFFON_GPU_TIMEOUT"))
            except ValueError:
                logger.warning(
                    f"Invalid CHIFFON_GPU_TIMEOUT value: {os.getenv('CHIFFON_GPU_TIMEOUT')}"
                )

        if os.getenv("CHIFFON_AGENT_ID"):
            self.agent_id = os.getenv("CHIFFON_AGENT_ID")

        if os.getenv("CHIFFON_POOL_NAME"):
            self.agent_pool_name = os.getenv("CHIFFON_POOL_NAME")

        # Auto-generate agent_id from hostname if not set
        if not self.agent_id:
            hostname = socket.gethostname()
            self.agent_id = f"{hostname}-{str(uuid4())[:8]}"
            logger.info(f"Auto-generated agent_id from hostname: {self.agent_id}")

        logger.info(
            f"Agent config loaded: "
            f"heartbeat={self.heartbeat_interval_seconds}s, "
            f"timeout={self.heartbeat_timeout_seconds}s, "
            f"gpu_timeout={self.gpu_detection_timeout_seconds}s, "
            f"pool={self.agent_pool_name}"
        )
