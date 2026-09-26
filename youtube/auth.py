"""
YouTube Authentication - OAuth2 flow for YouTube Data API v3
"""
import os
import json
from pathlib import Path
from typing import Optional
from loguru import logger

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build, Resource

from config.settings import YOUTUBE_CLIENT_SECRETS, YOUTUBE_TOKEN_PATH

# OAuth2 scopes required for uploading videos
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]


class YouTubeAuthError(Exception):
    """Custom exception for YouTube authentication errors"""
    pass


def get_credentials(*, refresh=True) -> Optional[Credentials]:
    """
    Get valid OAuth2 credentials, refreshing if necessary.
    
    Returns:
        Valid credentials or None if not available
    """
    creds = None
    token_path = Path(YOUTUBE_TOKEN_PATH)
    json_token_path = token_path.with_suffix('.json')
    
    # Try loading from JSON first (new format)
    if json_token_path.exists():
        try:
            with open(json_token_path, 'r') as f:
                token_data = json.load(f)
            if not token_data.get('expiry'):
                # Older serialization discarded expiry; force a refresh instead
                # of treating this access token as permanently valid.
                token_data['expiry'] = '1970-01-01T00:00:00Z'
            creds = Credentials.from_authorized_user_info(token_data)
            logger.debug("Loaded credentials from JSON token file")
        except Exception as e:
            logger.warning(f"Failed to load JSON token file: {type(e).__name__}")
            creds = None
    
    # Legacy pickle is intentionally never deserialized in a publishing process.
    # Reauthorize explicitly with setup-youtube to replace that unsafe format.

    # Check if credentials are valid
    if creds and creds.valid:
        return creds
    if creds and not refresh:
        return creds
    
    # Try to refresh expired credentials
    if creds and creds.expired and creds.refresh_token:
        try:
            logger.info("Refreshing expired credentials...")
            creds.refresh(Request())
            save_credentials(creds)
            return creds
        except Exception as e:
            logger.warning(f"Failed to refresh credentials: {type(e).__name__}")
            creds = None
    
    return None


def save_credentials(creds: Credentials) -> None:
    """
    Save credentials to the token file.
    
    Args:
        creds: Credentials to save
    """
    token_path = Path(YOUTUBE_TOKEN_PATH)
    json_token_path = token_path.with_suffix('.json')
    json_token_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Serialize credentials to JSON (more secure than pickle)
    from core.runtime_safety import atomic_write_json
    token_data = json.loads(creds.to_json())
    atomic_write_json(json_token_path, token_data, private=True)
    
    logger.debug(f"Saved credentials to {json_token_path}")


def authenticate_interactive() -> Credentials:
    """
    Perform interactive OAuth2 authentication.
    Opens a browser for the user to authorize the application.
    
    Returns:
        Valid credentials after authentication
        
    Raises:
        YouTubeAuthError: If authentication fails
    """
    client_secrets = Path(YOUTUBE_CLIENT_SECRETS)
    
    if not client_secrets.exists():
        raise YouTubeAuthError(
            f"Client secrets file not found at {client_secrets}\n"
            "Please download your OAuth credentials from Google Cloud Console "
            "and save them as 'client_secrets.json' in the project root."
        )
    
    try:
        logger.info("Starting OAuth2 authentication flow...")
        logger.info("A browser window will open for you to authorize the application.")
        
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secrets),
            scopes=SCOPES
        )
        
        # Run local server for OAuth callback
        creds = flow.run_local_server(
            port=8080,
            prompt='consent',
            success_message="Authentication successful! You can close this window."
        )
        
        # Save for future use
        save_credentials(creds)
        
        logger.success("✅ YouTube authentication successful!")
        return creds
        
    except Exception as e:
        logger.error(f"Authentication failed: {type(e).__name__}")
        raise YouTubeAuthError(f"OAuth2 authentication failed: {type(e).__name__}") from e


def get_authenticated_service(*, interactive: bool = False) -> Resource:
    """
    Get an authenticated YouTube API service.
    Will use existing credentials or prompt for authentication.
    
    Returns:
        Authenticated YouTube API service resource
        
    Raises:
        YouTubeAuthError: If authentication fails
    """
    creds = get_credentials()
    
    if creds is None:
        if not interactive:
            raise YouTubeAuthError('No usable credentials; run setup-youtube explicitly')
        creds = authenticate_interactive()
    
    try:
        service = build('youtube', 'v3', credentials=creds)
        logger.debug("YouTube API service created successfully")
        return service
        
    except Exception as e:
        logger.error(f"Failed to create YouTube service: {type(e).__name__}")
        raise YouTubeAuthError(f"Failed to create YouTube service: {type(e).__name__}") from e


def check_authentication_status() -> dict:
    """
    Check the current authentication status.
    
    Returns:
        Dict with authentication status info
    """
    creds = get_credentials(refresh=False)
    client_secrets_exists = Path(YOUTUBE_CLIENT_SECRETS).exists()
    token_exists = Path(YOUTUBE_TOKEN_PATH).with_suffix('.json').exists()
    
    if creds is None:
        status = "not_authenticated"
        message = "Not authenticated. Run 'python main.py setup-youtube' to authenticate."
    elif creds.expired:
        status = "expired"
        message = "Credentials expired. Will attempt refresh on next use."
    elif creds.valid:
        status = "valid"
        message = "Authenticated and ready to upload."
    else:
        status = "unknown"
        message = "Unknown credential state."
    
    return {
        "status": status,
        "message": message,
        "client_secrets_exists": client_secrets_exists,
        "token_exists": token_exists
    }


def revoke_credentials() -> bool:
    """
    Revoke current credentials and delete the token file.
    
    Returns:
        True if successful, False otherwise
    """
    token_path = Path(YOUTUBE_TOKEN_PATH)
    
    try:
        for candidate in (token_path, token_path.with_suffix('.json'), token_path.with_suffix('.pickle.bak')):
            if candidate.exists():
                candidate.unlink()
        logger.info("Local credentials disconnected; remote authorization is unchanged")
        return True
    except Exception as e:
        logger.error(f"Failed to revoke credentials: {type(e).__name__}")
        return False


def test_authentication() -> bool:
    """
    Test if authentication is working by making a simple API call.
    
    Returns:
        True if authentication works, False otherwise
    """
    try:
        service = get_authenticated_service()
        
        # Try to get channel info (simple read operation)
        response = service.channels().list(
            part='snippet',
            mine=True
        ).execute()
        
        if 'items' in response and len(response['items']) > 0:
            channel = response['items'][0]
            channel_title = channel['snippet']['title']
            logger.success(f"✅ Authentication test passed! Channel: {channel_title}")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Authentication test failed: {type(e).__name__}")
        return False
