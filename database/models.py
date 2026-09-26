"""
Database Models - SQLite models for tracking verse progress and reel history
"""
import datetime
from pathlib import Path
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Float, Boolean, CheckConstraint, inspect, text
from sqlalchemy.orm import sessionmaker, Session, declarative_base

from config.settings import DATABASE_PATH

# Create base class for models
Base = declarative_base()

# Database engine (will be created on first use)
_engine = None
_SessionLocal = None


class RetryingSession(Session):
    """
    SQLAlchemy session class that automatically retries commits on SQLite lock/busy errors.
    """
    def commit(self):
        import time
        import sqlite3
        from sqlalchemy.exc import OperationalError
        from loguru import logger
        
        max_retries = 4
        initial_backoff = 0.05
        backoff_factor = 2.0
        retries = 0
        backoff = initial_backoff
        
        # rollback expires dirty objects and expunges new ones. Capture the intended
        # write before flushing so a lock retry replays the transaction, not an
        # inactive Session. Unique constraints still arbitrate competing writers.
        added = list(self.new)
        changed = [(obj, {a.key: getattr(obj, a.key) for a in inspect(obj).mapper.column_attrs})
                   for obj in self.dirty]
        deleted = list(self.deleted)
        while True:
            try:
                super().commit()
                return
            except OperationalError as e:
                self.rollback()
                is_locked = False
                orig = getattr(e, 'orig', None)
                if orig and isinstance(orig, sqlite3.OperationalError) and "locked" in str(orig).lower():
                    is_locked = True
                elif "locked" in str(e).lower() or "busy" in str(e).lower():
                    is_locked = True
                
                if is_locked and retries < max_retries:
                    retries += 1
                    logger.warning(
                        f"Database is locked/busy. Retrying transaction commit ({retries}/{max_retries}) "
                        f"in {backoff:.2f}s..."
                    )
                    time.sleep(backoff)
                    backoff *= backoff_factor
                    for obj in added:
                        self.add(obj)
                    for obj, values in changed:
                        for key, value in values.items():
                            setattr(obj, key, value)
                    for obj in deleted:
                        self.delete(obj)
                else:
                    logger.error("Database lock retry attempts exhausted or non-lock error occurred.")
                    raise e


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        # Ensure directory exists
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        _engine = create_engine(
            f"sqlite:///{DATABASE_PATH}",
            connect_args={
                "check_same_thread": False,
                "timeout": 0.25  # bounded writer waits; transaction retry handles contention
            },
            echo=False
        )
    return _engine


def get_db_session() -> Session:
    """Get a new database session."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            class_=RetryingSession,
            autocommit=False,
            autoflush=False,
            bind=get_engine()
        )
    return _SessionLocal()



def init_database():
    """Initialize the database and create tables."""
    engine = get_engine()
    tables=set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        has_legacy_state=any(connection.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar()>0
                             for table in ('verse_progress','reel_history') if table in tables)
        marker=connection.execute(text("SELECT value FROM app_settings WHERE key='publication_cursor_verified'")).scalar() if 'app_settings' in tables else None
    if 'publishing_jobs' in tables and not {'shorts_rotation', 'shorts_cycle'} <= {c['name'] for c in inspect(engine).get_columns('publishing_jobs')}:
        import sqlite3
        backup_path = DATABASE_PATH.with_suffix('.pre-shorts-rotation.sqlite')
        if not backup_path.exists():
            source = engine.raw_connection()
            try:
                with sqlite3.connect(backup_path) as backup:
                    source.driver_connection.backup(backup)
            finally:
                source.close()
    if has_legacy_state and marker is None:
        import sqlite3
        backup_path=DATABASE_PATH.with_suffix('.pre-safety-migration.sqlite')
        if not backup_path.exists():
            source=engine.raw_connection()
            try:
                with sqlite3.connect(backup_path) as backup:
                    source.driver_connection.backup(backup)
            finally:
                source.close()
    # Back up an existing old schema before migration. The SQLite backup API
    # copies a consistent image; never rewrite a user's backup or discard rows.
    if 'video_analytics' in inspect(engine).get_table_names():
        old_columns={c['name'] for c in inspect(engine).get_columns('video_analytics')}
        backup_path=DATABASE_PATH.with_suffix('.pre-safety-migration.sqlite')
        if 'private_metrics_verified' not in old_columns and not backup_path.exists():
            import sqlite3
            source=engine.raw_connection()
            try:
                with sqlite3.connect(backup_path) as backup:
                    source.driver_connection.backup(backup)
            finally:
                source.close()
    Base.metadata.create_all(bind=engine)
    # Existing databases retain their rows. Do not silently pick one of several
    # journey cursors; this needs deliberate recovery by the owner.
    with engine.begin() as connection:
        connection.execute(text("INSERT OR IGNORE INTO app_settings(key,value) VALUES('publication_cursor_verified',:value)"),
                           {'value':'false' if has_legacy_state else 'true'})
        count = connection.execute(text("SELECT COUNT(*) FROM verse_progress")).scalar()
        if count > 1:
            raise RuntimeError("Multiple journey cursors exist; recover from backup before publishing")
        connection.execute(text("""CREATE TRIGGER IF NOT EXISTS verse_progress_singleton
            BEFORE INSERT ON verse_progress WHEN EXISTS(SELECT 1 FROM verse_progress)
            BEGIN SELECT RAISE(ABORT, 'only one journey cursor is allowed'); END"""))
        columns = {c['name'] for c in inspect(connection).get_columns('video_analytics')}
        if 'private_metrics_verified' not in columns:
            for name, declaration in [('metrics_source', "VARCHAR(30) DEFAULT 'legacy_unverified'"),
                                      ('observed_at', 'DATETIME'),
                                      ('private_metrics_verified', 'BOOLEAN DEFAULT 0')]:
                if name not in columns:
                    connection.execute(text(f'ALTER TABLE video_analytics ADD COLUMN {name} {declaration}'))
            # Old defaults were fabricated, not measurements. SQLite permits NULL
            # in these old columns. Preserve counts and attribution/history.
            connection.execute(text('UPDATE video_analytics SET retention_rate=NULL, ctr=NULL'))
        job_columns={c['name'] for c in inspect(connection).get_columns('publishing_jobs')}
        for name,declaration in [('finalized','BOOLEAN DEFAULT 0'),('metadata_json','TEXT'),('manifest','TEXT'),('surah_end','INTEGER'),
                                 ('shorts_rotation','BOOLEAN NOT NULL DEFAULT 0'),('shorts_cycle','INTEGER')]:
            if name not in job_columns:
                connection.execute(text(f'ALTER TABLE publishing_jobs ADD COLUMN {name} {declaration}'))


class VerseProgress(Base):
    """
    Tracks the current position in the Quran journey.
    Only one row should exist in this table.
    """
    __tablename__ = "verse_progress"
    __table_args__ = (CheckConstraint('current_surah >= 1 AND current_surah <= 114'),
                      CheckConstraint('current_ayah >= 1'),)
    
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


class SurahShortsProgress(Base):
    """Independent continuation position for each surah in the Shorts rotation."""
    __tablename__ = 'surah_shorts_progress'
    __table_args__ = (CheckConstraint('surah >= 1 AND surah <= 114'),
                      CheckConstraint('next_ayah >= 1'), CheckConstraint('cycle >= 0'))
    surah = Column(Integer, primary_key=True)
    next_ayah = Column(Integer, nullable=False, default=1)
    cycle = Column(Integer, nullable=False, default=0)


class LongformHistory(Base):
    """
    Records all compiled long-form videos with their details and upload status.
    """
    __tablename__ = "longform_history"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(Text, nullable=False)  # e.g. "Surah Al-Baqarah | Complete Recitation"
    surah_start = Column(Integer, nullable=False)  # First surah in compilation
    surah_end = Column(Integer, nullable=False)    # Last surah in compilation
    ayah_start = Column(Integer, nullable=True)    # Starting ayah (if partial)
    ayah_end = Column(Integer, nullable=True)      # Ending ayah (if partial)
    num_clips = Column(Integer, default=0)         # Number of source shorts
    source_clip_ids = Column(Text, nullable=True)  # JSON list of YouTube video IDs
    duration_seconds = Column(Integer, default=0)
    video_path = Column(Text, nullable=True)
    background_video_id = Column(String(50), nullable=True)  # Pexels video ID used
    reciter_key = Column(String(50), nullable=True)          # Reciter key used
    youtube_id = Column(String(50), nullable=True)
    youtube_url = Column(Text, nullable=True)
    status = Column(String(20), default="compiled")  # compiled, uploaded, failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    uploaded_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<LongformHistory(surahs={self.surah_start}-{self.surah_end}, status={self.status})>"


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


class VideoAnalytics(Base):
    """
    Tracks historical performance metrics of uploaded videos for self-optimization.
    """
    __tablename__ = "video_analytics"
    
    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(String(50), unique=True, index=True, nullable=False)
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    retention_rate = Column(Float, nullable=True, default=None)
    ctr = Column(Float, nullable=True, default=None)
    metrics_source = Column(String(30), default='manual')
    observed_at = Column(DateTime, default=datetime.datetime.utcnow)
    private_metrics_verified = Column(Boolean, nullable=False, default=False)
    engagement_rate = Column(Float, default=0.0)   # e.g., 0.35 for 35% (likes + comments) / views
    surah = Column(Integer, nullable=False)
    reciter_key = Column(String(50), nullable=False)
    video_type = Column(String(20), nullable=False) # short, long
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    def __repr__(self):
        return f"<VideoAnalytics(video_id={self.video_id}, views={self.views}, engagement={self.engagement_rate:.1%})>"


class ABTest(Base):
    """
    Tracks active/completed A/B experiments conducted by the growth engine.
    """
    __tablename__ = "ab_test"
    
    id = Column(Integer, primary_key=True, index=True)
    experiment_name = Column(String(100), nullable=False)
    variable_type = Column(String(50), nullable=False)   # reciter, ayah_length, thumbnail_style
    video_id_a = Column(String(50), nullable=False)
    video_id_b = Column(String(50), nullable=False)
    winner_id = Column(String(50), nullable=True)
    status = Column(String(20), default="active")         # active, completed
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<ABTest(name={self.experiment_name}, status={self.status})>"


class PublishingJob(Base):
    """Durable content reservation, final review and remote transfer receipt."""
    __tablename__ = 'publishing_jobs'
    surah_end = Column(Integer, nullable=True)
    id = Column(String(36), primary_key=True)
    idempotency_key = Column(String(200), unique=True, nullable=False)
    surah = Column(Integer, nullable=True)
    start_ayah = Column(Integer, nullable=True)
    end_ayah = Column(Integer, nullable=True)
    reciter_key = Column(String(50), nullable=True)
    sequential = Column(Integer, nullable=False, default=0)
    shorts_rotation = Column(Boolean, nullable=False, default=False)
    shorts_cycle = Column(Integer, nullable=True)
    status = Column(String(30), nullable=False, default='reserved')
    finalized = Column(Boolean, nullable=False, default=False)
    video_path = Column(Text, nullable=True)
    package_hash = Column(String(64), nullable=True)
    metadata_json = Column(Text, nullable=True)
    manifest = Column(Text, nullable=True)
    approval = Column(Text, nullable=True)
    receipts = Column(Text, nullable=False, default='{}')
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)




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


# Schema creation is explicit. Importing models must never mutate an existing DB.
