"""
Database Models - SQLite models for tracking verse progress and reel history
"""
import datetime
from pathlib import Path
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from config.settings import DATABASE_PATH

# Create base class for models
Base = declarative_base()

# Database engine (will be created on first use)
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        # Ensure directory exists
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        _engine = create_engine(
            f"sqlite:///{DATABASE_PATH}",
            connect_args={"check_same_thread": False},
            echo=False
        )
    return _engine


def get_db_session() -> Session:
    """Get a new database session."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine()
        )
    return _SessionLocal()


def init_database():
    """Initialize the database and create tables."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


class VerseProgress(Base):
    """
    Tracks the current position in the Quran journey.
    Only one row should exist in this table.
    """
    __tablename__ = "verse_progress"
    
    id = Column(Integer, primary_key=True, index=True)
    current_surah = Column(Integer, default=1, nullable=False)
    current_ayah = Column(Integer, default=1, nullable=False)
    total_reels_generated = Column(Integer, default=0, nullable=False)
    last_updated = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow
    )
    
    def __repr__(self):
        return f"<VerseProgress(surah={self.current_surah}, ayah={self.current_ayah})>"


class ReelHistory(Base):
    """
    Records all generated reels with their details and upload status.
    """
    __tablename__ = "reel_history"
    
    id = Column(Integer, primary_key=True, index=True)
    surah = Column(Integer, nullable=False)
    start_ayah = Column(Integer, nullable=False)
    end_ayah = Column(Integer, nullable=False)
    reciter_key = Column(String(50), nullable=False)
    reciter_name = Column(String(100))
    video_path = Column(Text)
    youtube_id = Column(String(50), nullable=True)
    youtube_url = Column(Text, nullable=True)
    status = Column(String(20), default="generated")  # generated, uploaded, failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    uploaded_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<ReelHistory(surah={self.surah}, ayahs={self.start_ayah}-{self.end_ayah}, status={self.status})>"
    
    @property
    def verse_range_str(self) -> str:
        """Get verse range as a string."""
        if self.start_ayah == self.end_ayah:
            return str(self.start_ayah)
        return f"{self.start_ayah}-{self.end_ayah}"


class AppSettings(Base):
    """
    Stores persistent application settings.
    Key-value store for various configurations.
    """
    __tablename__ = "app_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)
    updated_at = Column(
        DateTime,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow
    )
    
    def __repr__(self):
        return f"<AppSettings(key={self.key})>"


# Utility functions for settings
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a setting value by key."""
    session = get_db_session()
    try:
        setting = session.query(AppSettings).filter_by(key=key).first()
        return setting.value if setting else default
    finally:
        session.close()


def set_setting(key: str, value: str) -> None:
    """Set a setting value."""
    session = get_db_session()
    try:
        setting = session.query(AppSettings).filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = AppSettings(key=key, value=value)
            session.add(setting)
        session.commit()
    finally:
        session.close()


# Initialize database on module import
init_database()
