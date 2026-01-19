"""Database connection and session management using SQLAlchemy.

Provides:
- Engine: SQLAlchemy engine for PostgreSQL
- SessionLocal: Session factory for ORM operations
- Base: Declarative base for all ORM models
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import Config

# Initialize configuration
config = Config()

# Create SQLAlchemy engine
engine = create_engine(
    config.DATABASE_URL,
    echo=False,  # Set to True for SQL debugging
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Create declarative base for all models
Base = declarative_base()


def get_db():
    """Dependency injection function for FastAPI endpoints.

    Yields a database session that will be automatically closed.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
