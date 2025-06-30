import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


# PUBLIC_INTERFACE
def get_database_url():
    """Get the database URL from environment variables."""
    default_url = (
        "postgresql://postgres:ClashRoyale@db.uujtmzkpxvpkhpprtjjv."
        "supabase.co:5432/postgres"
    )
    return os.getenv("SUPABASE_DB_URL", default_url)


# Create database engine
DATABASE_URL = get_database_url()
engine = create_engine(DATABASE_URL, echo=True)


# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class for models
Base = declarative_base()


# PUBLIC_INTERFACE
def get_db():
    """
    Dependency to get database session.
    Used in FastAPI route dependencies.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# PUBLIC_INTERFACE
def create_tables():
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)
