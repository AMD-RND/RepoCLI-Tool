# bots/teams/app.py
"""
Microsoft Teams bot for RepoDiff (Bot Framework) - updated.

Key fixes:
 - Uses tenant-aware token endpoint (MICROSOFT_TENANT_ID) for Bot Framework client credential flow.
 - Better error logging and guidance when token acquisition fails.
 - Tries direct GET first; if 401/403 (or failure), retries with bearer token.
 - Keep the same async aiohttp-based upload to RepoDiff API via bots.shared_utils.upload_bytes_to_api.

Environment variables used:
 - MICROSOFT_APP_ID
 - MICROSOFT_APP_PASSWORD
 - MICROSOFT_TENANT_ID  (recommended; set to the tenant GUID where your App Registration lives)
 - REPODIFF_API_URL
 - REPODIFF_API_KEY (optional)
 - GITHUB_TOKEN (optional)
"""

import os
import json
import logging
from typing import Optional

import aiohttp
from aiohttp import web

from botbuilder.core import BotFrameworkAdapterSettings, BotFrameworkAdapter, TurnContext
from botbuilder.schema import Activity, ActivityTypes

# shared helper — make sure bots/shared_utils.py exports upload_bytes_to_api
from bots.shared_utils import upload_bytes_to_api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("repodiff-teams")

# Environment config
APP_ID = os.getenv("MICROSOFT_APP_ID")
APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD")
TENANT_ID = os.getenv("MICROSOFT_TENANT_ID")  # strongly recommended to set this to your tenant GUID
REPODIFF_API_URL = os.getenv("REPODIFF_API_URL", "http://127.0.0.1:8000")
REPODIFF_API_KEY = os.getenv("REPODIFF_API_KEY", None)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)

if not APP_ID or not APP_PASSWORD:
    logger.warning("MICROSOFT_APP_ID or MICROSOFT_APP_PASSWORD not set. Teams bot may not work properly.")

# Bot Framework adapter
SETTINGS = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
ADAPTER = BotFrameworkAdapter(SETTINGS)


async def acquire_botframework_token(app_id: str, app_password: str) -> Optional[str]:
    """
    Acquire a Bot Framework token via client credentials flow using tenant-aware endpoint.
    Returns access_token or None on failure.
    """
    tenant = TENANT_ID or "common"
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
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
                    logger.error("Bot Framework token request failed: %s %s", resp.status, text)
                    # Log helpful hint when unauthorized_client occurs
                    try:
                        body = json.loads(text)
                        if body.get("error") == "unauthorized_client":
                            logger.error(
                                "Token error 'unauthorized_client'. Likely causes:\n"
                                "- App Registration not present in tenant %s\n"
                                "- App not multi-tenant and request sent to wrong tenant\n"
                                "- Admin consent not granted\n"
                                "Check MICROSOFT_TENANT_ID and App Registration (App ID) configuration.",
                                tenant,
                            )
                    except Exception:
                        pass
                    return None
                token_json = json.loads(text)
                return token_json.get("access_token")
    except Exception as exc:
        logger.exception("Failed to acquire Bot Framework token: %s", exc)
        return None


async def fetch_attachment_bytes(content_url: str, service_url: Optional[str] = None,
                                 app_id: Optional[str] = None, app_password: Optional[str] = None) -> bytes:
    """
    Try to fetch attachment bytes.
    1) Try direct GET (no auth).
    2) If 401/403 or direct GET unsuitable, obtain bot framework token and retry with Bearer.
    Returns bytes or raises Exception.
    """
    logger.info("Fetching attachment: %s (service_url=%s)", content_url, service_url)
    timeout = aiohttp.ClientTimeout(total=60)

    # 1) Try direct GET
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(content_url) as resp:
                if resp.status == 200:
                    logger.info("Downloaded attachment via direct GET")
                    return await resp.read()
                else:
                    text = await resp.text()
                    logger.info("Direct GET returned %s: %s", resp.status, text[:400])
                    # continue to token flow for 401/403 or other non-200
    except Exception as e:
        logger.warning("Direct GET failed: %s", e)

    # 2) Acquire token and retry
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

    # If there are no attachments, send a friendly instruction
    if not activity.attachments:
        await turn_context.send_activity(
            "Hello — send me a CSV file (columns: repo_url,old_commit,new_commit) and I'll run RepoDiff for you."
        )
        return

    # take the first attachment
    att = activity.attachments[0]
    content_url = att.content_url
    filename = att.name or "attachment.dat"

    try:
        file_bytes = await fetch_attachment_bytes(
            content_url, service_url=activity.service_url, app_id=APP_ID, app_password=APP_PASSWORD
        )
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
            timeout=180,
        )
    except Exception as e:
        logger.exception("Failed to upload to RepoDiff API")
        await turn_context.send_activity(f"Failed to upload `{filename}` to RepoDiff API: {e}")
        return

    job_id = resp_json.get("job_id")
    status = resp_json.get("status", "unknown")
    reply_text = f"Received `{filename}` — created job `{job_id}` (status: {status})."
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
    logger.info("Starting Teams bot on port %s (MICROSOFT_TENANT_ID=%s)", port, TENANT_ID or "not-set")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
