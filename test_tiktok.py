"""
Verification Test Script for TikTok Automation Integration
"""
import sys
import os
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from loguru import logger

# Ensure current directory is in PYTHONPATH
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from config.settings import TIKTOK_TOKEN_PATH
from tiktok.auth import (
    save_token_data,
    load_token_data,
    get_tiktok_token,
    refresh_access_token,
    TikTokAuthError
)
from tiktok.uploader import (
    generate_tiktok_metadata,
    is_configured,
    get_tiktok_status,
    upload_to_tiktok
)


def test_metadata_generation():
    logger.info("Testing TikTok metadata generation...")
    meta = generate_tiktok_metadata(
        surah_name_ar="الإخلاص",
        surah_name_en="Al-Ikhlas",
        surah_num=112,
        start_ayah=1,
        end_ayah=4,
        reciter_name_ar="الشيخ مشاري العفاسي"
    )
    
    assert "الإخلاص" in meta["caption"], "Arabic Surah name should be present in caption"
    assert "Al-Ikhlas" in meta["caption"], "English Surah name should be present in caption"
    assert "112" in meta["caption"], "Surah number should be present in caption"
    assert "مشاري العفاسي" in meta["caption"], "Reciter name should be present in caption"
    assert "#Quran" in meta["caption"], "Tags should be present in caption"
    assert meta["description"] == "Surah Al-Ikhlas Ayah 1-4", "Description format mismatch"
    logger.success("TikTok metadata generation test passed.")


def test_token_save_and_load():
    logger.info("Testing TikTok token serialization and deserialization...")
    test_path = Path(TIKTOK_TOKEN_PATH).with_name("test_token_tiktok.json")
    
    token_payload = {
        "access_token": "mock_access_token_123",
        "refresh_token": "mock_refresh_token_456",
        "expires_in": 3600,
        "refresh_expires_in": 86400
    }
    
    # Temporarily patch token path to test file
    with patch("tiktok.auth.TIKTOK_TOKEN_PATH", test_path):
        save_token_data(token_payload)
        
        # Verify file creation
        assert test_path.exists(), "Token JSON file was not created"
        
        loaded = load_token_data()
        assert loaded is not None, "Failed to load token data"
        assert loaded["access_token"] == "mock_access_token_123"
        assert loaded["refresh_token"] == "mock_refresh_token_456"
        assert loaded["expires_at"] > time.time(), "expires_at timestamp was not calculated properly"
        
        # Test get_tiktok_token with valid token
        token = get_tiktok_token()
        assert token == "mock_access_token_123", f"Expected mock_access_token_123, got {token}"
        
        # Clean up test token file
        if test_path.exists():
            test_path.unlink()
            
    logger.success("TikTok token save and load tests passed.")


@patch("requests.post")
def test_token_refresh(mock_post):
    logger.info("Testing token refresh API invocation...")
    
    # Mock token refresh response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "refreshed_access_token",
        "refresh_token": "new_refresh_token",
        "expires_in": 3600
    }
    mock_post.return_value = mock_response
    
    test_path = Path(TIKTOK_TOKEN_PATH).with_name("test_token_tiktok.json")
    
    with patch("tiktok.auth.TIKTOK_TOKEN_PATH", test_path):
        with patch("tiktok.auth.TIKTOK_CLIENT_KEY", "dummy_key"):
            with patch("tiktok.auth.TIKTOK_CLIENT_SECRET", "dummy_secret"):
                res = refresh_access_token("mock_old_refresh_token")
                assert res is not None, "Refresh token call returned None"
                assert res["access_token"] == "refreshed_access_token"
                
                # Check cache was updated
                loaded = load_token_data()
                assert loaded["access_token"] == "refreshed_access_token"
                
                # Clean up
                if test_path.exists():
                    test_path.unlink()
                    
    logger.success("Token refresh test passed.")


@patch("requests.post")
@patch("requests.put")
def test_direct_upload_flow(mock_put, mock_post):
    logger.info("Testing video uploading REST request flow...")
    
    # 1. Mock video init POST call
    mock_init_response = MagicMock()
    mock_init_response.status_code = 200
    mock_init_response.json.return_value = {
        "data": {
            "publish_id": "v_publish_999",
            "upload_url": "https://upload.tiktok.com/dummy_put_url?auth=123"
        },
        "error": {
            "code": "ok",
            "message": ""
        }
    }
    mock_post.return_value = mock_init_response
    
    # 2. Mock video media data PUT call
    mock_put_response = MagicMock()
    mock_put_response.status_code = 201
    mock_put_response.text = "Uploaded"
    mock_put.return_value = mock_put_response
    
    # Create a small temporary test video file
    dummy_video = Path("dummy_test_video.mp4")
    dummy_video.write_bytes(b"DUMMY_VIDEO_CONTENT_12345")
    
    # Set up dummy access token
    with patch("tiktok.uploader.get_tiktok_token", return_value="dummy_token"):
        res = upload_to_tiktok(
            video_path=dummy_video,
            metadata={"caption": "Test Quran recitation video"}
        )
        
        # Verify result status
        assert res is not None
        assert res["status"] == "uploaded"
        assert res["publish_id"] == "v_publish_999"
        
        # Verify POST payload and headers
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://open.tiktokapis.com/v2/post/publish/video/init/"
        assert kwargs["headers"]["Authorization"] == "Bearer dummy_token"
        assert kwargs["json"]["source_info"]["video_size"] == 25
        assert kwargs["json"]["source_info"]["total_chunk_count"] == 1
        
        # Verify PUT body and headers
        mock_put.assert_called_once()
        put_args, put_kwargs = mock_put.call_args
        assert put_args[0] == "https://upload.tiktok.com/dummy_put_url?auth=123"
        assert put_kwargs["headers"]["Content-Range"] == "bytes 0-24/25"
        assert put_kwargs["headers"]["Content-Length"] == "25"
        assert put_kwargs["data"] == b"DUMMY_VIDEO_CONTENT_12345"
        
    # Clean up test video file
    if dummy_video.exists():
        dummy_video.unlink()
        
    logger.success("TikTok direct upload flow test passed.")


def run_all_tests():
    logger.info("Starting TikTok integration test suite...")
    
    test_metadata_generation()
    test_token_save_and_load()
    test_token_refresh()
    test_direct_upload_flow()
    
    logger.success("ALL TIKTOK INTEGRATION VERIFICATION TESTS COMPLETED SUCCESSFULLY!")


if __name__ == "__main__":
    run_all_tests()
