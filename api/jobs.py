# api/jobs.py
import json
from pathlib import Path
from .config import JOB_DIR

def job_path(job_id: str) -> Path:
    return JOB_DIR / job_id

def write_meta(job_id: str, meta: dict):
    p = job_path(job_id)
    p.mkdir(parents=True, exist_ok=True)
    (p / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

def read_meta(job_id: str) -> dict:
    p = job_path(job_id)
    m = p / "meta.json"
    if not m.exists():
        return None
    return json.loads(m.read_text(encoding="utf-8"))

def meta_exists(job_id: str) -> bool:
    return (job_path(job_id) / "meta.json").exists()
