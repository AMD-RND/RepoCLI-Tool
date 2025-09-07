# bots/slack/app.py
import os
import requests
from pathlib import Path
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

# -------------------------
# Config from environment
# -------------------------
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
REPODIFF_API_URL = os.getenv("REPODIFF_API_URL", "http://127.0.0.1:8000")
REPODIFF_API_KEY = os.getenv("REPODIFF_API_KEY", None)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)  # optional default GH token to pass to API

if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
    raise RuntimeError("SLACK_BOT_TOKEN and SLACK_APP_TOKEN must be set")

# optional temp folder to save downloaded files
TMP_DIR = Path(os.getenv("REPODIFF_TMP_DIR", "/tmp/repodiff_slack"))
TMP_DIR.mkdir(parents=True, exist_ok=True)

# -------------------------
# Slack App init
# -------------------------
app = App(token=SLACK_BOT_TOKEN)

# -------------------------
# Helpers
# -------------------------
def download_file_from_slack(client, file_id):
    """
    Download the file bytes from Slack using the bot token.
    Returns: (bytes, filename)
    """
    try:
        info = client.files_info(file=file_id).get("file")
        if not info:
            raise RuntimeError("files_info returned no file info")

        url_private = info.get("url_private")
        filename = info.get("name", f"{file_id}.dat")

        headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
        resp = requests.get(url_private, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.content, filename
    except SlackApiError as e:
        raise RuntimeError(f"Slack API error while fetching file info: {e.response['error']}")
    except Exception as e:
        raise RuntimeError(f"Failed to download file from Slack: {e}")

def upload_to_repodiff_api(file_bytes, filename, github_token=None):
    """
    Upload file bytes to the RepoDiff API /upload endpoint.
    Returns parsed JSON response.
    """
    url = f"{REPODIFF_API_URL.rstrip('/')}/upload"
    headers = {}
    if REPODIFF_API_KEY:
        headers["x-api-key"] = REPODIFF_API_KEY

    files = {"file": (filename, file_bytes)}
    data = {}
    if github_token:
        data["github_token"] = github_token
    elif GITHUB_TOKEN:
        data["github_token"] = GITHUB_TOKEN

    resp = requests.post(url, files=files, data=data, headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.json()

def fetch_summary_from_api(job_id):
    """
    Fetch summary JSON from the RepoDiff API (no polling).
    Returns dict or raises.
    """
    url = f"{REPODIFF_API_URL.rstrip('/')}/summary?job_id={job_id}"
    headers = {}
    if REPODIFF_API_KEY:
        headers["x-api-key"] = REPODIFF_API_KEY
    resp = requests.get(url, headers=headers, timeout=30)
    # if queued this will return 202 - caller should handle
    if resp.status_code == 200:
        return resp.json()
    elif resp.status_code == 202:
        # still running
        return {"status": "running", "job_id": job_id}
    else:
        resp.raise_for_status()

def compact_results_text(results, max_repos=10):
    """
    Build a compact, user-friendly summary string for Slack.
    """
    lines = []
    for i, r in enumerate(results):
        if i >= max_repos:
            lines.append(f"...and {len(results)-max_repos} more repos.")
            break
        repo = r.get("repo") or r.get("url", "unknown")
        total = r.get("total_commits", 0)
        added = r.get("files_added") or []
        modified = r.get("files_modified") or []
        removed = r.get("files_removed") or []
        files = []
        if added: files.append(f"+{len(added)}")
        if modified: files.append(f"~{len(modified)}")
        if removed: files.append(f"-{len(removed)}")
        files_part = " ".join(files) if files else "no file changes"
        lines.append(f"*{repo}*: commits={total}, {files_part}")
    return "\n".join(lines) if lines else "No results."

# -------------------------
# Event handlers
# -------------------------
@app.event("file_shared")
def handle_file_shared(event, client, logger):
    """
    Handle file_shared events:
    - download file from Slack
    - upload to RepoDiff API (/upload)
    - post a short acknowledgment with job_id (API will notify final results via webhook)
    """
    try:
        file_id = event.get("file_id")
        channel_id = event.get("channel_id") or event.get("channel")
        user_id = event.get("user_id") or event.get("user")
        if not file_id:
            logger.error("file_shared event missing file_id")
            return

        # download file
        try:
            file_bytes, filename = download_file_from_slack(client, file_id)
        except Exception as e:
            msg = f"Failed to download the uploaded file: {e}"
            logger.exception(msg)
            if user_id:
                client.chat_postEphemeral(channel=channel_id, user=user_id, text=msg)
            else:
                client.chat_postMessage(channel=channel_id, text=msg)
            return

        # acknowledge and upload to API
        ack = client.chat_postMessage(channel=channel_id, text=f"Received `{filename}` — uploading to RepoDiff service...")
        ack_ts = ack.get("ts")

        try:
            api_resp = upload_to_repodiff_api(file_bytes, filename)
        except Exception as e:
            err_txt = f"Failed to upload to RepoDiff API: {e}"
            logger.exception(err_txt)
            client.chat_update(channel=channel_id, ts=ack_ts, text=err_txt)
            return

        job_id = api_resp.get("job_id")
        status = api_resp.get("status", "unknown")
        # Short message: API will post final results to Slack (via webhook) when finished
        client.chat_update(channel=channel_id, ts=ack_ts, text=f"Job created: `{job_id}` (status: {status}). The API will post final results to Slack when finished.")
        return

    except Exception as e:
        logger.exception("Unhandled error in file_shared handler")
        try:
            client.chat_postMessage(channel=event.get("channel_id") or event.get("channel"), text=f"Unexpected error: {e}")
        except Exception:
            pass

# -------------------------
# Slash command to fetch summary by job id (on-demand)
# -------------------------
@app.command("/repodiff-summary")
def slash_summary(ack, respond, command, logger):
    """
    Usage: /repodiff-summary <job_id>
    Fetches summary from API and returns a compact summary.
    """
    ack()
    text = (command.get("text") or "").strip()
    if not text:
        respond("Usage: /repodiff-summary <job_id>")
        return
    job_id = text.split()[0]
    try:
        res = fetch_summary_from_api(job_id)
    except Exception as e:
        logger.exception("Error fetching summary")
        respond(f"Failed to fetch summary for `{job_id}`: {e}")
        return

    if res.get("status") == "running":
        respond(f"Job `{job_id}` is still running. Please try again later.")
        return

    results = res.get("results", [])
    compact = compact_results_text(results)
    # keep reply short — Slack has limits; if large, recommend user to open job link
    summary_msg = f"*Summary for `{job_id}`:*\n{compact}\n\nOpen full results: {REPODIFF_API_URL.rstrip('/')}/summary?job_id={job_id}"
    respond(summary_msg)

# -------------------------
# Main runner
# -------------------------
if __name__ == "__main__":
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    print("Starting Slack bot (Socket Mode). Make sure SLACK_BOT_TOKEN and SLACK_APP_TOKEN are set.")
    handler.start()
