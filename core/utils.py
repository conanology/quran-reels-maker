"""
Utility functions for QuranReelsMaker
"""
import time
import functools
from typing import Type, Tuple
from loguru import logger
from requests.exceptions import RequestException


def retry_with_backoff(
    max_retries: int = 3,
    exceptions: Tuple[Type[Exception], ...] = (RequestException,),
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0
):
    """
    Decorator for retrying a function with exponential backoff.
    
    Args:
        max_retries: Maximum number of retry attempts
        exceptions: Tuple of exception types to catch and retry
        initial_delay: Initial delay in seconds before first retry
        backoff_factor: Multiplier for delay after each retry
        
    Returns:
        Decorated function with retry logic
        
    Example:
        @retry_with_backoff(max_retries=3)
        def fetch_data(url):
            return requests.get(url)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(
                            f"{func.__name__} failed after {max_retries + 1} attempts: {e}"
                        )
            
            # Re-raise the last exception if all retries failed
            raise last_exception
        
        return wrapper
    return decorator
