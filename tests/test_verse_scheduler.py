"""
Tests for core.verse_scheduler module
"""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

# We need to mock the database before importing the module
@pytest.fixture(autouse=True)
def mock_database(mocker):
    """Mock database operations for all tests"""
    # Mock the init_database call
    mocker.patch('database.models.init_database')
    

class TestIsFriday:
    """Tests for is_friday function"""
    
    def test_friday_returns_true(self, mocker):
        """Should return True on Friday"""
        from core.verse_scheduler import is_friday
        
        # Mock datetime to return a Friday (weekday() == 4)
        mock_datetime = mocker.patch('core.verse_scheduler.datetime')
        mock_now = MagicMock()
        mock_now.weekday.return_value = 4  # Friday
        mock_datetime.now.return_value = mock_now
        
        assert is_friday() == True
    
    def test_saturday_returns_false(self, mocker):
        """Should return False on Saturday"""
        from core.verse_scheduler import is_friday
        
        mock_datetime = mocker.patch('core.verse_scheduler.datetime')
        mock_now = MagicMock()
        mock_now.weekday.return_value = 5  # Saturday
        mock_datetime.now.return_value = mock_now
        
        assert is_friday() == False


class TestGetFridayVerses:
    """Tests for get_friday_verses function"""
    
    def test_returns_surah_18(self):
        """Should always return Surah 18 (Al-Kahf)"""
        from core.verse_scheduler import get_friday_verses
        
        surah, start, end = get_friday_verses()
        assert surah == 18
    
    def test_verse_range_is_valid(self):
        """Verse range should be within Al-Kahf (1-110)"""
        from core.verse_scheduler import get_friday_verses
        
        surah, start, end = get_friday_verses()
        assert start >= 1
        assert end <= 110
        assert start <= end


class TestVerseSchedulerError:
    """Tests for VerseSchedulerError exception"""
    
    def test_exception_can_be_raised(self):
        """VerseSchedulerError should be raisable"""
        from core.verse_scheduler import VerseSchedulerError
        
        with pytest.raises(VerseSchedulerError):
            raise VerseSchedulerError("Test error message")


class TestSetProgress:
    """Tests for set_progress function validation"""
    
    def test_invalid_surah_raises_error(self, mocker):
        """Should raise error for invalid surah number"""
        from core.verse_scheduler import set_progress, VerseSchedulerError
        
        with pytest.raises(VerseSchedulerError, match="Invalid surah"):
            set_progress(0, 1)  # surah 0 is invalid
        
        with pytest.raises(VerseSchedulerError, match="Invalid surah"):
            set_progress(115, 1)  # surah 115 is invalid
    
    def test_invalid_ayah_raises_error(self, mocker):
        """Should raise error for invalid ayah number"""
        from core.verse_scheduler import set_progress, VerseSchedulerError
        
        # Al-Fatihah only has 7 ayahs
        with pytest.raises(VerseSchedulerError, match="Invalid ayah"):
            set_progress(1, 0)  # ayah 0 is invalid
        
        with pytest.raises(VerseSchedulerError, match="Invalid ayah"):
            set_progress(1, 10)  # ayah 10 exceeds Fatihah's 7 verses
