"""
TikTok Authentication - OAuth2 flow for TikTok Content Posting API v2
"""
import os
import json
import time
import urllib.parse
import http.server
import socketserver
import requests
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any
from loguru import logger

from config.settings import TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_TOKEN_PATH, TIKTOK_REDIRECT_URI


class TikTokAuthError(Exception):
    """Custom exception for TikTok authentication errors"""
    pass


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """HTTP Handler to capture the authorization code from redirect."""
    
    def log_message(self, format, *args):
        # Suppress server logging to keep CLI output clean
        pass
        
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed_url.query)
        code = params.get('code')
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        
        if code:
            self.server.auth_code = code[0]
            success_html = """
            <html>
                <body style="font-family: Arial, sans-serif; text-align: center; padding-top: 50px; background-color: #f9f9f9;">
                    <div style="display: inline-block; padding: 30px; background: white; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                        <h1 style="color: #4CAF50; margin-bottom: 10px;">✅ Authentication Successful!</h1>
                        <p style="color: #555; font-size: 16px;">You have successfully authorized Quran Reels Maker for TikTok posting.</p>
                        <p style="color: #777; font-size: 14px;">You can now close this tab and return to the console.</p>
                    </div>
                </body>
            </html>
            """
            self.wfile.write(success_html.encode('utf-8'))
        else:
            fail_html = """
            <html>
                <body style="font-family: Arial, sans-serif; text-align: center; padding-top: 50px; background-color: #f9f9f9;">
                    <div style="display: inline-block; padding: 30px; background: white; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                        <h1 style="color: #f44336; margin-bottom: 10px;">❌ Authentication Failed</h1>
                        <p style="color: #555; font-size: 16px;">No authorization code was found in the redirect callback.</p>
                    </div>
                </body>
            </html>
            """
            self.wfile.write(fail_html.encode('utf-8'))


def run_callback_server(port: int = 8080) -> Optional[str]:
    """Start a temporary server to receive the authorization code redirect."""
    # Custom TCPServer with allow_reuse_address set to True
    class ReuseAddrTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    try:
        server = ReuseAddrTCPServer(('127.0.0.1', port), CallbackHandler)
        server.auth_code = None
        
        # Handle exactly one request (the redirect back from TikTok)
        server.handle_request()
        server.server_close()
        return server.auth_code
    except Exception as e:
        logger.error(f"Failed to run OAuth callback server: {e}")
        return None


def save_token_data(token_data: Dict[str, Any]) -> None:
    """Save token data to JSON token file."""
    path = Path(TIKTOK_TOKEN_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Store expiration timestamp
    if 'expires_in' in token_data:
        token_data['expires_at'] = int(time.time()) + int(token_data['expires_in'])
    if 'refresh_expires_in' in token_data:
        token_data['refresh_expires_at'] = int(time.time()) + int(token_data['refresh_expires_in'])
        
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(token_data, f, indent=2)
    logger.debug(f"Saved TikTok token details to {path.name}")


def load_token_data() -> Optional[Dict[str, Any]]:
    """Load token details from cache."""
    path = Path(TIKTOK_TOKEN_PATH)
    if not path.exists():
        return None
        
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read TikTok token file: {e}")
        return None


def refresh_access_token(refresh_token: str) -> Optional[Dict[str, Any]]:
    """Refresh the access token using a refresh token."""
    if not TIKTOK_CLIENT_KEY or not TIKTOK_CLIENT_SECRET:
        logger.error("TikTok Client Key or Secret missing. Cannot refresh token.")
        return None
        
    logger.info("Refreshing expired TikTok access token...")
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "client_key": TIKTOK_CLIENT_KEY,
        "client_secret": TIKTOK_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if 'access_token' in data:
                save_token_data(data)
                logger.success("TikTok access token refreshed successfully.")
                return data
            else:
                logger.error(f"Unexpected token response structure: {data}")
        else:
            logger.error(f"Failed token refresh endpoint HTTP {response.status_code}: {response.text}")
    except Exception as e:
        logger.error(f"Error during TikTok token refresh: {e}")
        
    return None


def get_tiktok_token() -> Optional[str]:
    """
    Get a valid TikTok access token, refreshing if it has expired.
    
    Returns:
        String access token or None if unavailable/unauthorized.
    """
    token_data = load_token_data()
    if not token_data:
        # Check if we can fallback to env variable
        token_env = os.getenv("TIKTOK_ACCESS_TOKEN")
        if token_env:
            logger.debug("Using TikTok access token from environment variables")
            return token_env
        return None
        
    # Check expiry (with 5-minute safety margin)
    expires_at = token_data.get('expires_at', 0)
    if time.time() + 300 >= expires_at:
        refresh_token = token_data.get('refresh_token')
        if refresh_token:
            refreshed = refresh_access_token(refresh_token)
            if refreshed:
                return refreshed.get('access_token')
        logger.warning("TikTok access token has expired and cannot be refreshed.")
        return None
        
    return token_data.get('access_token')


def authenticate_interactive() -> Optional[str]:
    """
    Start OAuth2 flow. Opens browser to request user authorization,
    spins up callback server, captures authorization code, and requests token.
    """
    if not TIKTOK_CLIENT_KEY or not TIKTOK_CLIENT_SECRET:
        raise TikTokAuthError(
            "TikTok credentials missing! Please configure TIKTOK_CLIENT_KEY "
            "and TIKTOK_CLIENT_SECRET in your environment or .env file."
        )
        
    redirect_uri = TIKTOK_REDIRECT_URI
    scope = "video.publish,video.upload"
    
    # TikTok authorize URL
    auth_params = {
        "client_key": TIKTOK_CLIENT_KEY,
        "scope": scope,
        "response_type": "code",
        "redirect_uri": redirect_uri
    }
    auth_url = f"https://www.tiktok.com/v2/auth/authorize/?{urllib.parse.urlencode(auth_params)}"
    
    logger.info("Opening TikTok authorization page in your browser...")
    webbrowser.open(auth_url)
    
    print("\n" + "="*75)
    print("📢 TIKTOK AUTHENTICATION REDIRECT")
    print("="*75)
    print("TikTok strictly requires an HTTPS redirect. When you click 'Authorize' in your")
    print("browser, it will redirect to an error page (e.g. 'This site can't be reached').")
    print("THIS IS NORMAL and expected.")
    print("\n👉 Please copy the FULL URL from your browser's address bar (it contains '?code=xxx')")
    print("   and paste it below.")
    print("="*75 + "\n")
    
    auth_code = None
    try:
        user_input = input("Paste the redirect URL or code here: ").strip()
        if user_input:
            if "code=" in user_input:
                parsed = urllib.parse.urlparse(user_input)
                params = urllib.parse.parse_qs(parsed.query)
                auth_code = params.get('code', [None])[0]
            else:
                auth_code = user_input
    except KeyboardInterrupt:
        raise TikTokAuthError("Authentication cancelled by user.")
        
    if not auth_code:
        logger.info("No manual input received. Falling back to local port listener...")
        auth_code = run_callback_server(port=8080)
        
    if not auth_code:
        raise TikTokAuthError("Failed to obtain authorization code.")
        
    logger.info("Exchanging authorization code for token details...")
    url = "https://open.tiktokapis.com/v2/oauth/token/"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }
    payload = {
        "client_key": TIKTOK_CLIENT_KEY,
        "client_secret": TIKTOK_CLIENT_SECRET,
        "code": auth_code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri
    }
    
    try:
        response = requests.post(url, headers=headers, data=payload, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if 'access_token' in data:
                save_token_data(data)
                logger.success("TikTok integration successfully authenticated!")
                return data.get('access_token')
            else:
                raise TikTokAuthError(f"OAuth response missing access token: {data}")
        else:
            raise TikTokAuthError(f"HTTP {response.status_code} exchanging token: {response.text}")
    except Exception as e:
        logger.error(f"TikTok authentication failed: {e}")
        raise TikTokAuthError(f"Authentication flow failed: {e}") from e
