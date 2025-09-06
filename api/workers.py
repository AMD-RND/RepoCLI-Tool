# api/workers.py
import threading
from pathlib import Path
import json

from .jobs import write_meta, job_path
from cli_tool.utils import save_results_json, save_results_csv, is_github_url
from cli_tool.github_api import compare_commits_github
from cli_tool.git_local import compare_commits_local

def run_job_sync(job_id: str, commits: list, github_token=None):
    """
    Process commits synchronously (blocking). Save results to job folder.
    Returns results list.
    """
    results = []
    for row in commits:
        repo = row["repo_url"]
        old = row["old_commit"]
        new = row["new_commit"]
        try:
            if is_github_url(repo):
                res = compare_commits_github(repo, old, new, github_token)
            else:
                res = compare_commits_local(repo, old, new)
        except Exception as e:
            res = {
                "repo": repo.split("/")[-1].replace(".git", ""),
                "url": repo,
                "old_commit": old,
                "new_commit": new,
                "compare_url": None,
                "total_commits": 0,
                "commit_messages": [],
                "files_added": [],
                "files_modified": [],
                "files_removed": [],
                "error": str(e),
            }
        results.append(res)

    # persist results
    p = job_path(job_id)
    p.mkdir(parents=True, exist_ok=True)
    write_meta(job_id, {"job_id": job_id, "status": "finished", "count": len(results)})
    save_results_json(results, str(p / "summary.json"))
    save_results_csv(results, str(p / "summary.csv"))

    # notify Slack via incoming webhook (if configured)
    try:
        from .notify import post_to_slack_webhook
        post_to_slack_webhook(job_id, results)
    except Exception as e:
        # don't fail the job for notification errors; log or ignore
        print(f"Slack notification failed: {e}")

    return results

def run_job_background(job_id: str, commits: list, github_token=None):
    """
    Start background thread and immediately return the Thread object.
    """
    def worker():
        try:
            run_job_sync(job_id, commits, github_token)
        except Exception as e:
            # write failed metadata
            write_meta(job_id, {"job_id": job_id, "status": "failed", "error": str(e)})
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread
