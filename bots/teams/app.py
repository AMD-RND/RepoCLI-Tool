# bots/teams/app.py
"""
Microsoft Teams bot for RepoDiff (Bot Framework).

- Exposes POST /api/messages which Teams (Bot Framework) will call.
- Handles message activities and attachments:
  * Tries to download attachments directly (some are public).
  * If direct download fails (401/403), obtains a Bot Framework access token using
    client credentials and retries with Authorization: Bearer <token>.
- Uploads attachment bytes to RepoDiff API via bots.shared_utils.upload_bytes_to_api
  (async).
- Replies to the user confirming the job_id returned by the API.

Requirements:
- Python 3.8+
- pip packages: aiohttp, botbuilder-core, botbuilder-schema, requests
- Environment vars:
    MICROSOFT_APP_ID
    MICROSOFT_APP_PASSWORD
    REPODIFF_API_URL
    REPODIFF_API_KEY (optional)
    GITHUB_TOKEN (optional)
"""

import os
import asyncio
import json
import logging
from typing import Dict, Any, Optional

import aiohttp
from aiohttp import web

from botbuilder.core import BotFrameworkAdapterSettings, BotFrameworkAdapter, TurnContext
from botbuilder.schema import Activity, ActivityTypes

# shared upload helper from previous code
# Ensure bots/shared_utils.py exists and export upload_bytes_to_api and build_api_headers
from bots.shared_utils import upload_bytes_to_api, build_api_headers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("repodiff-teams")

# Environment config
APP_ID = os.getenv("MICROSOFT_APP_ID")
APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD")
REPODIFF_API_URL = os.getenv("REPODIFF_API_URL", "http://127.0.0.1:8000")
REPODIFF_API_KEY = os.getenv("REPODIFF_API_KEY", None)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)

if not APP_ID or not APP_PASSWORD:
    logger.warning("MICROSOFT_APP_ID or MICROSOFT_APP_PASSWORD not set. You must set these for Teams bot to work.")

# Bot Framework adapter
SETTINGS = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
ADAPTER = BotFrameworkAdapter(SETTINGS)


async def acquire_botframework_token(app_id: str, app_password: str) -> Optional[str]:
    """
    Acquire a Bot Framework token via client credentials flow.
    Uses the tenant 'botframework.com' endpoint which is recommended for Bot Framework.
    Returns access_token or None on failure.
    """
    token_url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": app_id,
        "client_secret": app_password,
        "scope": "https://api.botframework.com/.default"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, data=data, headers=headers, timeout=20) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.error(f"Bot Framework token request failed: {resp.status} {text}")
                    return None
                token_json = json.loads(text)
                return token_json.get("access_token")
    except Exception as exc:
        logger.exception(f"Failed to acquire Bot Framework token: {exc}")
        return None


async def fetch_attachment_bytes(content_url: str, service_url: Optional[str] = None,
                                 app_id: Optional[str] = None, app_password: Optional[str] = None) -> bytes:
    """
    Try to fetch attachment bytes.
    1) Try direct GET (no auth).
    2) If 401/403 or other auth error, obtain bot framework token and retry with Bearer.
    Returns bytes or raises Exception.
    """
    logger.info(f"Fetching attachment: {content_url} (service_url={service_url})")
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Try direct GET
        try:
            async with session.get(content_url) as resp:
                if resp.status == 200:
                    logger.info("Downloaded attachment via direct GET")
                    return await resp.read()
                elif resp.status in (401, 403):
                    logger.info(f"Direct GET returned {resp.status}; will try Bot Framework token")
                else:
                    text = await resp.text()
                    logger.info(f"Direct GET returned {resp.status}: {text}")
                    # try token fallback anyway
        except Exception as e:
            logger.warning(f"Direct GET failed: {e}")

        # Acquire token and retry
        if not app_id or not app_password:
            raise RuntimeError("App ID / Password missing; cannot fetch protected attachment")

        token = await acquire_botframework_token(app_id, app_password)
        if not token:
            raise RuntimeError("Failed to acquire Bot Framework token to fetch attachment")

        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(content_url, headers=headers) as resp:
                if resp.status == 200:
                    logger.info("Downloaded attachment using Bot Framework bearer token")
                    return await resp.read()
                else:
                    text = await resp.text()
                    raise RuntimeError(f"Failed to download attachment with token: {resp.status} {text}")


async def on_message_activity(turn_context: TurnContext):
    """
    Called when a message activity is received.
    - If attachments present: download each (first) and upload to RepoDiff API.
    - Reply to user with job_id information.
    """
    activity = turn_context.activity
    text = activity.text or ""
    from_id = activity.from_property.id if activity.from_property else None

    # simple text response if no attachments
    if not activity.attachments:
        await turn_context.send_activity("Hello — send me a CSV file with repo_url,old_commit,new_commit and I'll run RepoDiff for you.")
        return

    # handle attachments (take first attachment)
    att = activity.attachments[0]
    content_url = att.content_url
    filename = att.name or "attachment.dat"

    try:
        # Attempt to fetch bytes (direct or with token)
        file_bytes = await fetch_attachment_bytes(content_url, service_url=activity.service_url,
                                                  app_id=APP_ID, app_password=APP_PASSWORD)
    except Exception as e:
        logger.exception("Failed to fetch attachment")
        await turn_context.send_activity(f"Failed to download attachment `{filename}`: {e}")
        return

    # Upload to RepoDiff API
    try:
        resp_json = await upload_bytes_to_api(
            api_base=REPODIFF_API_URL,
            filename=filename,
            file_bytes=file_bytes,
            api_key=REPODIFF_API_KEY,
            github_token=GITHUB_TOKEN,
            timeout=180
        )
    except Exception as e:
        logger.exception("Failed to upload to RepoDiff API")
        await turn_context.send_activity(f"Failed to upload `{filename}` to RepoDiff API: {e}")
        return

    job_id = resp_json.get("job_id")
    status = resp_json.get("status", "unknown")
    # reply with job id and short guidance
    reply_text = f"Received `{filename}` — created job `{job_id}` (status: {status}).\n"
    reply_text += f"You can check results via your RepoDiff UI or ask `/summary {job_id}` (if supported)."
    await turn_context.send_activity(reply_text)


async def messages(req: web.Request) -> web.Response:
    """
    Aiohttp entry for POST /api/messages.
    It forwards the request body to the BotFrameworkAdapter for processing.
    """
    try:
        body = await req.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")

    async def aux(turn_context: TurnContext):
        if turn_context.activity.type == ActivityTypes.message:
            await on_message_activity(turn_context)
        else:
            # generic reply for other activity types
            await turn_context.send_activity("Event received but not handled by the bot.")

    try:
        await ADAPTER.process_activity(activity, auth_header, aux)
        return web.Response(status=200)
    except Exception as e:
        logger.exception("Error processing activity")
        return web.Response(status=500, text=str(e))


def main():
    app = web.Application()
    app.router.add_post("/api/messages", messages)
    port = int(os.getenv("PORT", "3978"))
    logger.info(f"Starting Teams bot on port {port}")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
