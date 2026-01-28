"""
Database connection and setup
SQLite database with SQLAlchemy
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base

# Database file path - SQLite file in the project root
DATABASE_URL = "sqlite:///./futmob.db"

# Create engine with echo=False (set to True for SQL debugging)
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Needed for SQLite
    echo=False  # Set to True to see SQL queries
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """
    Initialize database - create all tables
    Safe to call multiple times (won't recreate existing tables)
    """
    Base.metadata.create_all(bind=engine)
    print(f"Database initialized at: {DATABASE_URL}")


def get_db():
    """
    Get database session - use in FastAPI dependencies
    Yields a session and closes it when done
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session():
    """
    Get a database session for scripts
    Remember to close() when done
    """
    return SessionLocal()
