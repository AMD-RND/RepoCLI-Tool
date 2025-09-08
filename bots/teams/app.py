# bots/teams/app.py
import os
import asyncio
import requests
from aiohttp import web
from botbuilder.core import BotFrameworkAdapterSettings, BotFrameworkAdapter, TurnContext
from botbuilder.schema import Activity, ActivityTypes

APP_ID = os.getenv("MICROSOFT_APP_ID")
APP_PASSWORD = os.getenv("MICROSOFT_APP_PASSWORD")
REPODIFF_API_URL = os.getenv("REPODIFF_API_URL", "http://127.0.0.1:8000")
REPODIFF_API_KEY = os.getenv("REPODIFF_API_KEY", None)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)

SETTINGS = BotFrameworkAdapterSettings(APP_ID, APP_PASSWORD)
ADAPTER = BotFrameworkAdapter(SETTINGS)

async def on_message(turn_context: TurnContext):
    text = turn_context.activity.text or ""
    # Respond to simple text commands
    if turn_context.activity.attachments:
        # For attachments, Bot Framework provides attachment contentUrl; fetch bytes
        for att in turn_context.activity.attachments:
            content_url = att.content_url
            # contentUrl may require bearer token; here we try straightforward fetch
            resp = requests.get(content_url)
            resp.raise_for_status()
            files = {"file": (att.name, resp.content)}
            headers = {}
            if REPODIFF_API_KEY:
                headers["x-api-key"] = REPODIFF_API_KEY
            data = {}
            if GITHUB_TOKEN:
                data["github_token"] = GITHUB_TOKEN
            r = requests.post(f"{REPODIFF_API_URL.rstrip('/')}/upload", files=files, data=data, headers=headers, timeout=120)
            r.raise_for_status()
            job_id = r.json().get("job_id")
            await turn_context.send_activity(f"Uploaded `{att.name}` — job `{job_id}`.")
    else:
        await turn_context.send_activity(f"Hello — send me a CSV with repo/commits and I will run RepoDiff. Try uploading a file.")

async def messages(req):
    body = await req.json()
    activity = Activity().deserialize(body)
    auth_header = req.headers.get("Authorization", "")
    async def aux(turn_context):
        await on_message(turn_context)
    await ADAPTER.process_activity(activity, auth_header, aux)
    return web.Response(status=200)

if __name__ == "__main__":
    app = web.Application()
    app.router.add_post("/api/messages", messages)
    port = int(os.getenv("PORT", 3978))
    web.run_app(app, host="0.0.0.0", port=port)
