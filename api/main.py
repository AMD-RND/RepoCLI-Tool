from .share import router as share_router, SHARE_PATH
from fastapi.responses import FileResponse
# api/main.py
import os
import uuid
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import JOB_DIR, SYNC_ROW_LIMIT, GITHUB_DEFAULT_TOKEN
from .jobs import write_meta, read_meta, job_path, summary_path, csv_path, meta_exists
from .workers import run_job_sync, run_job_background
from .auth import require_api_key
from cli_tool.utils import load_commits_from_csv, save_results_json, save_results_csv

app = FastAPI(title="Repo Diff Bot API")
app.include_router(share_router, prefix=SHARE_PATH)

# CORS - allow all for local/dev. Narrow in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Health endpoints
@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/readyz")
def readyz():
    # simple ready check: JOB_DIR exists
    return {"ready": JOB_DIR.exists()}

@app.post("/upload", dependencies=[Depends(require_api_key)])
async def upload_file(
    file: UploadFile = File(...),
    github_token: Optional[str] = Form(None),
):
    """
    Upload CSV file as multipart/form-data. CSV must have headers:
    repo_url,old_commit,new_commit
    If rows <= SYNC_ROW_LIMIT -> processed synchronously and returns finished job_id.
    Otherwise returns queued job_id.
    """
    # save uploaded file temporarily in JOB_DIR
    contents = await file.read()
    tmp_name = f"upload_{uuid.uuid4().hex}.csv"
    tmp_path = JOB_DIR / tmp_name
    tmp_path.write_bytes(contents)

    # parse CSV to commits
    try:
        commits = load_commits_from_csv(str(tmp_path))
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {e}")

    # determine token
    github_token = github_token or GITHUB_DEFAULT_TOKEN

    # small job -> process synchronously
    if len(commits) <= SYNC_ROW_LIMIT:
        job_id = uuid.uuid4().hex
        job_folder = job_path(job_id)
        job_folder.mkdir(parents=True, exist_ok=True)
        write_meta(job_id, {"job_id": job_id, "status": "running", "count_pending": len(commits)})

        try:
            results = run_job_sync(job_id, commits, github_token)
            tmp_path.unlink(missing_ok=True)
            return JSONResponse(status_code=200, content={"job_id": job_id, "status": "finished", "count": len(results)})
        except Exception as e:
            write_meta(job_id, {"job_id": job_id, "status": "failed", "error": str(e)})
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=str(e))

    # otherwise queue background job
    job_id = uuid.uuid4().hex
    job_folder = job_path(job_id)
    job_folder.mkdir(parents=True, exist_ok=True)
    write_meta(job_id, {"job_id": job_id, "status": "queued", "count_pending": len(commits)})

    # start background thread
    run_job_background(job_id, commits, github_token)
    tmp_path.unlink(missing_ok=True)
    return JSONResponse(status_code=202, content={"job_id": job_id, "status": "queued", "count": len(commits)})

@app.get("/summary", dependencies=[Depends(require_api_key)])
def get_summary(job_id: str):
    """
    Return the summary JSON for a finished job_id.
    If job is queued/running, returns 202 with status.
    """
    if not meta_exists(job_id):
        raise HTTPException(status_code=404, detail="job_id not found")

    meta = read_meta(job_id)
    status = meta.get("status", "unknown")
    if status != "finished":
        return JSONResponse(status_code=202, content={"job_id": job_id, "status": status})

    summary_file = summary_path(job_id)
    if not summary_file.exists():
        raise HTTPException(status_code=500, detail="summary missing for finished job")

    data = json.loads(summary_file.read_text(encoding="utf-8"))
    return JSONResponse(status_code=200, content={"job_id": job_id, "status": "finished", "results": data})

@app.get("/repo/{repo_name}", dependencies=[Depends(require_api_key)])
def get_repo(job_id: str, repo_name: str):
    """
    Return single repo summary for a given job_id and repo_name.
    Matches on 'repo' field (short name) or URL suffix.
    """
    if not meta_exists(job_id):
        raise HTTPException(status_code=404, detail="job_id not found")

    summary_file = summary_path(job_id)
    if not summary_file.exists():
        meta = read_meta(job_id)
        return JSONResponse(status_code=202, content={"job_id": job_id, "status": meta.get("status", "queued")})

    results = json.loads(summary_file.read_text(encoding="utf-8"))
    for r in results:
        # repo field or trailing url match
        if r.get("repo") == repo_name or (r.get("url") and r["url"].rstrip("/").endswith(repo_name)):
            return JSONResponse(status_code=200, content=r)

    raise HTTPException(status_code=404, detail="repo not found in job results")

# Serve summary.csv for a job
@app.get("/jobs/{job_id}/summary.csv")
def download_csv(job_id: str):
    path = csv_path(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="csv not found")
    return FileResponse(path, media_type="text/csv", filename=f"{job_id}_summary.csv")
