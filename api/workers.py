# api/workers.py
import threading
import uuid
import json
from .jobs import write_meta, job_path
from .config import SYNC_ROW_LIMIT
from cli_tool.utils import load_commits_from_csv, save_results_json, save_results_csv, is_github_url
from cli_tool.github_api import compare_commits_github
from cli_tool.git_local import compare_commits_local

def run_job_sync(job_id: str, commits: list, github_token=None):
    results = []
    for row in commits:
        repo = row["repo_url"]; old = row["old_commit"]; new = row["new_commit"]
        try:
            if is_github_url(repo):
                res = compare_commits_github(repo, old, new, github_token)
            else:
                res = compare_commits_local(repo, old, new)
        except Exception as e:
            res = {"repo": repo.split("/")[-1], "url": repo, "old_commit": old, "new_commit": new,
                   "commit_messages": [], "files_added": [], "files_modified": [], "files_removed": [], "error": str(e)}
        results.append(res)
    # save
    p = job_path(job_id)
    p.mkdir(parents=True, exist_ok=True)
    write_meta(job_id, {"job_id": job_id, "status": "finished", "count": len(results)})
    save_results_json(results, str(p / "summary.json"))
    save_results_csv(results, str(p / "summary.csv"))
    return results

def run_job_background(job_id: str, commits: list, github_token=None):
    thread = threading.Thread(target=run_job_sync, args=(job_id, commits, github_token), daemon=True)
    thread.start()
    return thread
