"""
Database Initialization - Centralized schema creation for all modules.
"""
from loguru import logger

from database.models import Base as CoreBase, get_engine
from documentary.models import Base as DocBase


def init_all_databases():
    """
    Initialize all database schemas across the application.
    This ensures all tables (Reels and Documentary) are created 
    before the application logic tries to query them.
    """
    engine = get_engine()
    
    # Create Core tables (VerseProgress, ReelHistory, AppSettings)
    CoreBase.metadata.create_all(bind=engine)
    
    # Create Documentary tables (SeerahEpisode, EpisodeScript, etc.)
    DocBase.metadata.create_all(bind=engine)
    
    logger.info("All database tables initialized successfully.")

if __name__ == "__main__":
    init_all_databases()
