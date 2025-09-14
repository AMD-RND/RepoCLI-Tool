# bots/teams/app.py
"""
Microsoft Teams bot for RepoDiff (Bot Framework) - Graph fallback version.

Behavior:
 - Try direct GET to contentUrl (some attachments are public).
 - If direct GET fails (403/401), try Bot Framework token (https://api.botframework.com/.default).
 - If Bot Framework token fails or returns 401, try Graph token (https://graph.microsoft.com/.default).
 - If download succeeds, upload file bytes to RepoDiff API via bots.shared_utils.upload_bytes_to_api.
 - Reply to user with job_id or an informative error message.

Environment variables required:
 - MICROSOFT_APP_ID
 - MICROSOFT_APP_PASSWORD
 - MICROSOFT_TENANT_ID
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

# shared helper: implement upload_bytes_to_api(api_base, filename, file_bytes, api_key, github_token, timeout)
from bots.shared_utils import upload_bytes_to_api

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("repodiff-teams")

# env
APP_ID = os.getenv("MICROSOFT_APP_ID")
APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD")
TENANT_ID = os.getenv("MICROSOFT_TENANT_ID")  # tenant GUID
REPODIFF_API_URL = os.getenv("REPODIFF_API_URL", "http://127.0.0.1:8000")
REPODIFF_API_KEY = os.getenv("REPODIFF_API_KEY", None)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)

if not APP_ID or not APP_PASSWORD or not TENANT_ID:
    logger.warning(
        "MICROSOFT_APP_ID / MICROSOFT_APP_PASSWORD / MICROSOFT_TENANT_ID are recommended to be set for Teams bot."
    )

SETTINGS = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
ADAPTER = BotFrameworkAdapter(SETTINGS)


async def acquire_token_tenant_scope(scope: str, tenant: Optional[str], client_id: str, client_secret: str) -> Optional[str]:
    """
    Acquire client-credentials token for the given scope.
    scope: e.g. "https://api.botframework.com/.default" or "https://graph.microsoft.com/.default"
    tenant: tenant id or 'common'
    """
    tenant = tenant or "common"
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": scope,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(token_url, data=data, headers=headers, timeout=20) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.error("Token request failed (%s) %s", resp.status, text[:500])
                    return None
                token_json = json.loads(text)
                return token_json.get("access_token")
    except Exception as exc:
        logger.exception("Token request exception: %s", exc)
        return None


async def fetch_with_auth(content_url: str, auth_header: Optional[str] = None) -> tuple[int, bytes, str]:
    """
    Download the content_url optionally using Authorization header.
    Returns: (status, bytes_or_empty, text_or_empty)
    """
    timeout = aiohttp.ClientTimeout(total=60)
    headers = {}
    if auth_header:
        headers["Authorization"] = auth_header
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(content_url, headers=headers) as resp:
                status = resp.status
                if status == 200:
                    data = await resp.read()
                    return status, data, ""
                else:
                    text = await resp.text()
                    return status, b"", text
    except Exception as e:
        logger.warning("HTTP fetch exception for %s: %s", content_url, e)
        return 0, b"", str(e)


async def fetch_attachment_bytes(content_url: str, app_id: str, app_password: str, tenant_id: Optional[str] = None) -> bytes:
    """
    Robust download flow:
     1) direct GET
     2) Bot Framework token (scope=https://api.botframework.com/.default)
     3) Graph token (scope=https://graph.microsoft.com/.default)
    Raises RuntimeError on failure with helpful message.
    """
    logger.info("Fetching attachment: %s", content_url)

    # 1) direct GET
    status, data, text = await fetch_with_auth(content_url)
    if status == 200 and data:
        logger.info("Direct GET succeeded")
        return data

    logger.info("Direct GET returned %s. proceeding to Bot Framework token flow.", status)

    # 2) Bot Framework token
    bot_token = await acquire_token_tenant_scope("https://api.botframework.com/.default", tenant_id, app_id, app_password)
    if bot_token:
        status, data, text = await fetch_with_auth(content_url, auth_header=f"Bearer {bot_token}")
        if status == 200 and data:
            logger.info("Downloaded via Bot Framework token")
            return data
        logger.info("Bot Framework token GET returned %s: %s", status, (text or "")[:300])
    else:
        logger.warning("Could not acquire Bot Framework token (or returned none).")

    # 3) Graph token (for SharePoint/OneDrive-hosted attachments)
    logger.info("Attempting Microsoft Graph token flow for %s", content_url)
    graph_token = await acquire_token_tenant_scope("https://graph.microsoft.com/.default", tenant_id, app_id, app_password)
    if graph_token:
        # Graph token might require a slightly different header to access contentUrl in tenant storage
        status, data, text = await fetch_with_auth(content_url, auth_header=f"Bearer {graph_token}")
        if status == 200 and data:
            logger.info("Downloaded via Graph token")
            return data
        logger.error("Graph token download returned %s: %s", status, (text or "")[:500])
    else:
        logger.warning("Could not acquire Graph token (or returned none).")

    # No success
    msg = (
        "Failed to download attachment. Attempted direct GET, Bot Framework token, and Graph token but all failed. "
        "Check your App Registration (permissions & admin consent), MICROSOFT_TENANT_ID, and whether the file is in SharePoint/OneDrive "
        "needing Graph access."
    )
    logger.error(msg)
    raise RuntimeError(msg)


async def on_message_activity(turn_context: TurnContext):
    """
    Handle message activities: if attachments exist, download first attachment and upload to RepoDiff API.
    """
    activity = turn_context.activity

    if not activity.attachments:
        await turn_context.send_activity(
            "Hello — send me a CSV file (columns: repo_url,old_commit,new_commit) and I'll run RepoDiff for you."
        )
        return

    att = activity.attachments[0]
    content_url = att.content_url
    filename = att.name or "attachment.csv"

    try:
        file_bytes = await fetch_attachment_bytes(content_url, app_id=APP_ID, app_password=APP_PASSWORD, tenant_id=TENANT_ID)
    except Exception as e:
        logger.exception("Failed to fetch attachment bytes")
        await turn_context.send_activity(f"Failed to download attachment `{filename}`: {e}")
        return

    # Upload to RepoDiff API (shared_utils is expected to provide this)
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
        logger.exception("Upload to RepoDiff API failed")
        await turn_context.send_activity(f"Failed to upload `{filename}` to RepoDiff API: {e}")
        return

    job_id = resp_json.get("job_id")
    status = resp_json.get("status", "unknown")
    reply_text = f"Received `{filename}` — created job `{job_id}` (status: {status})."
    await turn_context.send_activity(reply_text)


async def messages(req: web.Request) -> web.Response:
    """
    Aiohttp entry for POST /api/messages. Pass activity to the BotFrameworkAdapter.
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
    logger.info("Starting Teams bot on port %s (TENANT=%s)", port, TENANT_ID or "not-set")
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
