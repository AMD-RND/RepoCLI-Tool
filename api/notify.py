# api/notify.py
import os
import requests
from typing import List

SLACK_INCOMING_WEBHOOK = os.getenv("SLACK_INCOMING_WEBHOOK")  # e.g. https://hooks.slack.com/services/XXX/YYY/ZZZ
API_BASE_URL = os.getenv("REPODIFF_PUBLIC_URL", "http://127.0.0.1:8000")  # public URL for links

def make_compact_block_for_results(job_id: str, results: List[dict], max_repos=6):
    """
    Build Slack Blocks: header, few repo lines, link to full details.
    """
    blocks = []
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*RepoDiff job finished* — `<{API_BASE_URL}/summary?job_id={job_id}|Open results>`"}})
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

        # one repo per section
        text = f"*{repo}* — commits: {commits} — {filesummary_text}\n<{API_BASE_URL}/repo/{repo}?job_id={job_id}|View details>"
        blocks.append({"type":"section", "text":{"type":"mrkdwn", "text": text}})
        count += 1

    # actions: link to JSON and download CSV
    blocks.append({"type":"divider"})
    actions = {
        "type":"actions",
        "elements":[
            {"type":"button","text":{"type":"plain_text","text":"Open full results"},"url": f"{API_BASE_URL}/summary?job_id={job_id}"},
            {"type":"button","text":{"type":"plain_text","text":"Download CSV"},"url": f"{API_BASE_URL}/jobs/{job_id}/summary.csv"}
        ]
    }
    blocks.append(actions)
    return {"blocks": blocks}

def post_to_slack_webhook(job_id: str, results: List[dict]):
    webhook = SLACK_INCOMING_WEBHOOK
    if not webhook:
        # no webhook configured — do nothing
        return False
    payload = make_compact_block_for_results(job_id, results)
    resp = requests.post(webhook, json=payload, timeout=10)
    if resp.status_code >= 300:
        raise RuntimeError(f"Slack webhook failed: {resp.status_code} {resp.text}")
    return True
