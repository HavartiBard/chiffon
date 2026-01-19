"""FastAPI orchestrator application.

Entry point for the Chiffon agent orchestration system.
Provides health checks and serves as the foundation for orchestration routes.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.common.config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Load configuration
config = Config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for application startup and shutdown.

    Startup: Initialize connections and resources.
    Shutdown: Cleanup connections and resources.
    """
    # Startup
    logger.info(f"Starting {config.APP_NAME}")
    logger.info(f"Database: {config.DATABASE_URL}")
    logger.info(f"RabbitMQ: {config.RABBITMQ_URL}")
    logger.info(f"Ollama: {config.OLLAMA_BASE_URL}")
    logger.info(f"LiteLLM: {config.LITELLM_URL}")

    yield

    # Shutdown
    logger.info(f"Shutting down {config.APP_NAME}")


# Create FastAPI app
app = FastAPI(
    title=config.APP_NAME,
    description="Orchestrated AI agents for infrastructure automation",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check endpoint.

    Returns:
        dict: Status of the application and its dependencies.
    """
    return {
        "status": "healthy",
        "service": config.APP_NAME,
        "version": "0.1.0",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
