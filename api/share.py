# api/share.py
import os
import time
import hmac
import hashlib
import base64
from typing import Tuple
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

# endpoint base path (mount in main app)
SHARE_PATH = "/share"
SHARE_SECRET = os.getenv("SHARE_SECRET", None)  # set this in env for security
JOB_DIR = Path(os.getenv("JOB_DIR", str(Path(__file__).resolve().parent.parent / "jobs")))

if not SHARE_SECRET:
    # When not set, create a warning — in production you MUST set SHARE_SECRET
    print("WARNING: SHARE_SECRET not set. Signed links will not be secure. Set SHARE_SECRET env var in production.")

def _hmac_sign(message: bytes) -> bytes:
    key = SHARE_SECRET.encode("utf-8") if SHARE_SECRET else b"default_insecure_key"
    return hmac.new(key, message, hashlib.sha256).digest()

def create_signed_token(job_id: str, ttl_seconds: int = 3600) -> str:
    """
    Returns a URL-safe token encoding job_id and expiry and an HMAC.
    Format: base64url(job_id + '|' + str(expiry) + '|' + hmac)
    """
    expiry = int(time.time()) + int(ttl_seconds)
    payload = f"{job_id}|{expiry}".encode("utf-8")
    sig = _hmac_sign(payload)
    token_bytes = payload + b"|" + sig
    token = base64.urlsafe_b64encode(token_bytes).rstrip(b"=").decode("ascii")
    return token

def verify_token(token: str) -> Tuple[str, int]:
    """
    Verify token and return (job_id, expiry). Raises HTTPException on failure.
    """
    try:
        # decode padding
        padding = '=' * (-len(token) % 4)
        token_bytes = base64.urlsafe_b64decode(token + padding)
        parts = token_bytes.split(b"|", 2)
        if len(parts) != 3:
            raise ValueError("invalid token structure")
        job_id = parts[0].decode("utf-8")
        expiry = int(parts[1].decode("utf-8"))
        sig = parts[2]
        # verify hmac
        payload = f"{job_id}|{expiry}".encode("utf-8")
        expected_sig = _hmac_sign(payload)
        if not hmac.compare_digest(expected_sig, sig):
            raise ValueError("signature mismatch")
        if expiry < int(time.time()):
            raise ValueError("token expired")
        return job_id, expiry
    except Exception as exc:
        raise HTTPException(status_code=403, detail=f"Invalid or expired token: {exc}")

# Router to mount in main app
router = APIRouter()

@router.get("/{token}")
def share_summary(token: str):
    job_id, expiry = verify_token(token)
    summary_file = JOB_DIR / job_id / "summary.json"
    if not summary_file.exists():
        raise HTTPException(status_code=404, detail="summary not found")
    return FileResponse(str(summary_file), media_type="application/json", filename=f"{job_id}_summary.json")
