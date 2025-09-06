# api/auth.py
from fastapi import Header, HTTPException
from .config import API_KEY

def require_api_key(x_api_key: str = Header(None)):
    """
    Simple API key header check. If API_KEY is not set in config,
    this function allows all requests.
    """
    if API_KEY:
        if x_api_key != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid API key")
    return True

