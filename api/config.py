# api/config.py
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
# default jobs directory (project-root/jobs) but can be overridden via env
JOB_DIR = Path(os.getenv("JOB_DIR", str(BASE_DIR.parent / "jobs")))
JOB_DIR.mkdir(parents=True, exist_ok=True)

# If CSV rows <= SYNC_ROW_LIMIT, we process synchronously (blocking)
SYNC_ROW_LIMIT = int(os.getenv("SYNC_ROW_LIMIT", "20"))

# Optional API key for simple auth; if not set, auth is no-op
API_KEY = os.getenv("API_KEY", None)

# Optional default GitHub token used when clients don't pass one
GITHUB_DEFAULT_TOKEN = os.getenv("GITHUB_TOKEN", None)
