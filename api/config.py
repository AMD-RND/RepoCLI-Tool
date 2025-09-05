# api/config.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
JOB_DIR = Path(os.getenv("JOB_DIR", str(BASE_DIR.parent / "jobs")))
JOB_DIR.mkdir(parents=True, exist_ok=True)

SYNC_ROW_LIMIT = int(os.getenv("SYNC_ROW_LIMIT", "20"))
API_KEY = os.getenv("API_KEY", None)   # optional API key for auth
GITHUB_DEFAULT_TOKEN = os.getenv("GITHUB_TOKEN", None)
