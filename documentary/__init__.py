"""Reusable documentary helpers; no complete episode generation/publishing entry point."""
AVAILABLE = False
UNAVAILABLE_REASON = "Documentary episode generation is incomplete: script, API client, media manifest and approval gates are not implemented."

def require_available():
    raise RuntimeError(UNAVAILABLE_REASON)
