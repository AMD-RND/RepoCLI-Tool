# bots/slack/app.py
import os
import time
import json
import requests
from pathlib import Path
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

# -------------------------
# Config from environment
# -------------------------
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")        # xoxb-...
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")        # xapp-...
REPODIFF_API_URL = os.getenv("REPODIFF_API_URL", "http://127.0.0.1:8000")
REPODIFF_API_KEY = os.getenv("REPODIFF_API_KEY", None)  # optional header to send to API
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)         # optional default GH token to pass to API
POLL_INTERVAL = float(os.getenv("REPODIFF_POLL_INTERVAL", "2"))  # seconds
POLL_RETRIES = int(os.getenv("REPODIFF_POLL_RETRIES", "30"))

if not SLACK_BOT_TOKEN:
    raise RuntimeError("SLACK_BOT_TOKEN environment variable is required")
if not SLACK_APP_TOKEN:
    raise RuntimeError("SLACK_APP_TOKEN environment variable is required")

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
    # prefer argument token, otherwise environment default
    if github_token:
        data["github_token"] = github_token
    elif GITHUB_TOKEN:
        data["github_token"] = GITHUB_TOKEN

    resp = requests.post(url, files=files, data=data, headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.json()

def fetch_summary(job_id):
    """
    Poll /summary until finished or timed out. Returns JSON result or raises.
    """
    url = f"{REPODIFF_API_URL.rstrip('/')}/summary?job_id={job_id}"
    headers = {}
    if REPODIFF_API_KEY:
        headers["x-api-key"] = REPODIFF_API_KEY

    for _ in range(POLL_RETRIES):
        resp = requests.get(url, headers=headers, timeout=30)
        # 200 -> finished, 202 -> queued/running
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 202:
            # still working
            time.sleep(POLL_INTERVAL)
            continue
        else:
            # other error
            try:
                raise RuntimeError(f"Summary API error ({resp.status_code}): {resp.text}")
            except Exception:
                raise
    raise TimeoutError("Timed out waiting for job summary")

def compact_results_text(results, max_repos=10, max_files_display=6):
    """
    Build a compact, human-friendly string summarizing results.
    Truncates long file lists and number of repos.
    """
    lines = []
    for i, r in enumerate(results):
        if i >= max_repos:
            lines.append(f"...and {len(results)-max_repos} more repos.")
            break
        repo = r.get("repo") or r.get("url", "unknown")
        total = r.get("total_commits", 0)
        added = r.get("files_added", []) or []
        modified = r.get("files_modified", []) or []
        removed = r.get("files_removed", []) or []
        # build small file list
        files = []
        if added:
            files.append(f"+{len(added)}")
        if modified:
            files.append(f"~{len(modified)}")
        if removed:
            files.append(f"-{len(removed)}")
        files_part = " ".join(files) if files else "no file changes"
        lines.append(f"*{repo}*: commits={total}, {files_part}")
    return "\n".join(lines) if lines else "No results."

# -------------------------
# Event handlers
# -------------------------
@app.event("file_shared")
def handle_file_shared(event, client, logger):
    """
    Handle file_shared events: download file, upload to RepoDiff API, post job_id,
    then poll for summary and post compact results back to channel.
    """
    try:
        file_id = event.get("file_id")
        channel_id = event.get("channel_id") or event.get("channel")  # event variants
        user_id = event.get("user_id") or event.get("user") or None

        if not file_id:
            # older events might have different payload; bail gracefully
            logger.error("file_shared event missing file_id")
            return

        # Download file
        try:
            file_bytes, filename = download_file_from_slack(client, file_id)
        except Exception as e:
            msg = f"Failed to download the uploaded file: {e}"
            logger.exception(msg)
            # inform user via ephemeral if user_id present
            if user_id:
                client.chat_postEphemeral(channel=channel_id, user=user_id, text=msg)
            else:
                client.chat_postMessage(channel=channel_id, text=msg)
            return

        # Acknowledge upload to channel
        ack_text = f"Received `{filename}` — uploading to RepoDiff service..."
        ack = client.chat_postMessage(channel=channel_id, text=ack_text)
        ack_ts = ack.get("ts")

        # Upload file to RepoDiff API
        try:
            api_resp = upload_to_repodiff_api(file_bytes, filename)
        except Exception as e:
            err_text = f"Failed to upload to RepoDiff API: {e}"
            logger.exception(err_text)
            client.chat_update(channel=channel_id, ts=ack_ts, text=err_text)
            return

        job_id = api_resp.get("job_id")
        status = api_resp.get("status", "unknown")
        client.chat_update(channel=channel_id, ts=ack_ts, text=f"Job created: `{job_id}` (status: {status}). I will post summary when finished.")

        # If finished right away, fetch and post results; otherwise poll until finished (naive)
        if status == "finished":
            try:
                summary = fetch_summary(job_id)
                results = summary.get("results", [])
                compact = compact_results_text(results)
                client.chat_postMessage(channel=channel_id, text=f"Summary for `{job_id}`:\n{compact}")
            except Exception as e:
                logger.exception("Failed to fetch immediate summary")
                client.chat_postMessage(channel=channel_id, text=f"Job `{job_id}` finished but failed to fetch summary: {e}")
            return

        # queued -> poll for completion (simple approach)
        try:
            summary = fetch_summary(job_id)
        except TimeoutError:
            client.chat_postMessage(channel=channel_id, text=f"Job `{job_id}` is still running. I'll DM you when finished.")
            # optionally DM user to avoid channel spam
            if user_id:
                try:
                    client.chat_postMessage(channel=user_id, text=f"Your job `{job_id}` is still running. Please check /summary later.")
                except Exception:
                    pass
            return
        except Exception as e:
            logger.exception("Failed to get summary")
            client.chat_postMessage(channel=channel_id, text=f"Failed to fetch summary for `{job_id}`: {e}")
            return

        # Post compact summary in channel (or DM for large)
        results = summary.get("results", [])
        compact = compact_results_text(results)
        # if many repos, DM the user instead of channel
        if len(results) > 8 and user_id:
            client.chat_postMessage(channel=user_id, text=f"Summary for `{job_id}` (DM):\n{compact}")
            client.chat_postMessage(channel=channel_id, text=f"Job `{job_id}` finished — summary DM'd to <@{user_id}>.")
        else:
            client.chat_postMessage(channel=channel_id, text=f"Summary for `{job_id}`:\n{compact}")

    except Exception as e:
        logger.exception("Unhandled error in file_shared handler")
        # best-effort notify channel if possible
        try:
            client.chat_postMessage(channel=event.get("channel_id") or event.get("channel"), text=f"Unexpected error: {e}")
        except Exception:
            pass

# Optional: simple slash command to fetch summary by job id
@app.command("/repodiff-summary")
def slash_summary(ack, respond, command):
    ack()
    job_id = (command.get("text") or "").strip()
    if not job_id:
        respond("Usage: /repodiff-summary <job_id>")
        return
    try:
        summary = fetch_summary(job_id)
        results = summary.get("results", [])
        respond(f"Summary for `{job_id}`:\n" + compact_results_text(results))
    except Exception as e:
        respond(f"Failed to fetch summary: {e}")

# -------------------------
# Main runner
# -------------------------
if __name__ == "__main__":
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    print("Starting Slack bot (Socket Mode). Make sure SLACK_BOT_TOKEN and SLACK_APP_TOKEN are set.")
    handler.start()
