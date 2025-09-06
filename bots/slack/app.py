import logging
# bots/slack/app.py
# bots/slack/app.py
import os
import time
import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

logging.basicConfig(level=logging.INFO)
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")  # for Socket Mode
API_URL = os.getenv("REPODIFF_API_URL", "http://127.0.0.1:8000")
API_KEY = os.getenv("REPODIFF_API_KEY", None)   # optional

app = App(token=SLACK_BOT_TOKEN)

def download_file_from_slack(client, file_id):
    # get file info
    info = client.files_info(file=file_id)["file"]
    url_private = info["url_private"]
    # use bot token to download (needs files:read scope)
    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
    r = requests.get(url_private, headers=headers)
    r.raise_for_status()
    return r.content, info["name"]

def upload_to_api(file_bytes, filename, github_token=None):
    headers = {}
    if API_KEY:
        headers["x-api-key"] = API_KEY
    files = {"file": (filename, file_bytes)}
    data = {}
    if github_token:
        data["github_token"] = github_token
    resp = requests.post(f"{API_URL}/upload", files=files, data=data, headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.json()

@app.event("file_shared")
def handle_file(event, client, logger):
    file_id = event["file_id"]
    channel_id = event["channel_id"]
    user_id = event["user_id"]
    try:
        file_bytes, filename = download_file_from_slack(client, file_id)
    except Exception as e:
        client.chat_postEphemeral(channel=channel_id, user=user_id, text=f"Failed to download file: {e}")
        return

    # post an acknowledgement
    res = client.chat_postMessage(channel=channel_id, text=f"Received `{filename}` — uploading to Repo Diff service...")
    ack_ts = res["ts"]

    try:
        api_resp = upload_to_api(file_bytes, filename)
    except Exception as e:
        client.chat_update(channel=channel_id, ts=ack_ts, text=f"Upload failed: {e}")
        return

    job_id = api_resp.get("job_id")
    status = api_resp.get("status")
    client.chat_update(channel=channel_id, ts=ack_ts, text=f"Job created: `{job_id}` (status: {status}). I will post summary once finished.")

    # naive polling for final results (small demo). For production use webhook/callback.
    if status != "finished":
        for _ in range(30):
            time.sleep(2)
            try:
                headers = {}
                if API_KEY: headers["x-api-key"] = API_KEY
                s = requests.get(f"{API_URL}/summary?job_id={job_id}", headers=headers, timeout=30)
                if s.status_code == 200:
                    data = s.json()
                    results = data.get("results", [])
                    # build compact message
                    lines = [f"*Repo:* {r.get('repo')} — *commits:* {r.get('total_commits')}" for r in results]
                    text = "\n".join(lines) if lines else "No results."
                    client.chat_postMessage(channel=channel_id, text=f"Summary for `{job_id}`:\n{text}")
                    break
            except Exception:
                continue
    else:
        # if finished immediately, fetch and post
        headers = {}
        if API_KEY: headers["x-api-key"] = API_KEY
        s = requests.get(f"{API_URL}/summary?job_id={job_id}", headers=headers, timeout=30).json()
        results = s.get("results", [])
        lines = [f"*Repo:* {r.get('repo')} — *commits:* {r.get('total_commits')}" for r in results]
        client.chat_postMessage(channel=channel_id, text=f"Summary for `{job_id}`:\n" + ("\n".join(lines) or "No results."))

        # Main entry point to start the Slack bot
        if __name__ == "__main__":
            SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
            if not SLACK_APP_TOKEN:
                raise RuntimeError("SLACK_APP_TOKEN not set")
            logging.info("INFO: Slack Bolt: ... connected")
            handler = SocketModeHandler(app, SLACK_APP_TOKEN)
            handler.start()
