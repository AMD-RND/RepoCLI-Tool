# api/notify.py
import os
import requests
from typing import List, Optional

# The public URL where your API is reachable (used to build links)
# Set REPODIFF_PUBLIC_URL env var in production (e.g. https://repodiff.example.com)
REPODIFF_PUBLIC_URL = os.getenv("REPODIFF_PUBLIC_URL", "http://127.0.0.1:8000")
# Slack incoming webhook URL (create in Slack, see instructions below)
SLACK_INCOMING_WEBHOOK = os.getenv("SLACK_INCOMING_WEBHOOK", None)

# Import the share helper lazily to avoid circular imports
def _make_share_link(job_id: str, ttl_seconds: int = 3600) -> Optional[str]:
    """
    Return a signed one-time link (URL) to view job summary JSON.
    This uses the /share/<token> endpoint which must be mounted in your FastAPI app.
    """
    try:
        from .share import create_signed_token, SHARE_PATH
        token = create_signed_token(job_id, ttl_seconds=ttl_seconds)
        return f"{REPODIFF_PUBLIC_URL.rstrip('/')}{SHARE_PATH}/{token}"
    except Exception:
        return None

def make_compact_block_for_results(job_id: str, results: List[dict], max_repos: int = 6):
    """
    Build Slack Block Kit payload with summary + link to full results.
    """
    blocks = []
    header_text = f"*RepoDiff job finished* — <{REPODIFF_PUBLIC_URL}/summary?job_id={job_id}|Open results (API)>"
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": header_text}})
    blocks.append({"type": "divider"})

    count = 0
    for r in results:
        if count >= max_repos:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"...and {len(results)-max_repos} more repos."}]})
            break
        repo = r.get("repo") or r.get("url", "unknown")
        commits = r.get("total_commits", 0)
        added = len(r.get("files_added", []) or [])
        modified = len(r.get("files_modified", []) or [])
        removed = len(r.get("files_removed", []) or [])
        filesummary = []
        if added: filesummary.append(f"+{added}")
        if modified: filesummary.append(f"~{modified}")
        if removed: filesummary.append(f"-{removed}")
        filesummary_text = " ".join(filesummary) if filesummary else "no file changes"

        # use a view-details link pointing to /repo endpoint (users may need to be authenticated)
        repo_encoded = repo.replace("/", "%2F")
        details_link = f"{REPODIFF_PUBLIC_URL}/repo/{repo_encoded}?job_id={job_id}"
        text = f"*{repo}* — commits: {commits} — {filesummary_text}\n<{details_link}|View details>"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
        count += 1

    blocks.append({"type": "divider"})

    # create a short-lived public link for the JSON (if share helper present)
    public_link = _make_share_link(job_id, ttl_seconds=3600)
    actions = {"type": "actions", "elements": []}
    actions["elements"].append({"type": "button", "text": {"type": "plain_text", "text": "Open full results (API)"}, "url": f"{REPODIFF_PUBLIC_URL}/summary?job_id={job_id}"})
    if public_link:
        actions["elements"].append({"type": "button", "text": {"type": "plain_text", "text": "Temporary JSON link (1h)"}, "url": public_link})
    # Always offer CSV download link (will be protected if API requires auth)
    actions["elements"].append({"type": "button", "text": {"type": "plain_text", "text": "Download CSV"}, "url": f"{REPODIFF_PUBLIC_URL}/jobs/{job_id}/summary.csv"})
    blocks.append(actions)

    return {"blocks": blocks}

def post_to_slack_webhook(job_id: str, results: List[dict]):
    """
    Post a Block Kit message to the configured incoming webhook.
    Returns True on success, False if webhook not configured.
    """
    webhook = SLACK_INCOMING_WEBHOOK
    if not webhook:
        return False
    payload = make_compact_block_for_results(job_id, results)
    resp = requests.post(webhook, json=payload, timeout=10)
    resp.raise_for_status()
    return True
