# bots/discord/app.py
"""
Discord bot for RepoDiff.

Features:
- Listens for messages with attachments (CSV/TXT) and uploads the first attachment to RepoDiff API.
- Supports a simple command: !repodiff summary <job_id> to fetch summary from the API.
- Replies with job_id and short confirmation immediately (no polling).
- Uses aiohttp for non-blocking HTTP upload to the API.

Requirements:
- discord.py (v2.x)
- aiohttp
- Python 3.8+
"""

import os
import asyncio
import logging
from typing import Optional

import aiohttp
import discord
from discord.ext import commands

from bots.shared_utils import upload_bytes_to_api, build_api_headers, compact_results_text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("repodiff-discord")

# Environment config
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
REPODIFF_API_URL = os.getenv("REPODIFF_API_URL", "http://127.0.0.1:8000")
# Optionally use x-api-key or Authorization depending on your auth mode
REPODIFF_API_KEY = os.getenv("REPODIFF_API_KEY", None)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is required")

intents = discord.Intents.default()
# If you need to read message content (commands or text), enable this with developer intent enabled in Developer Portal
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Small helper to format API responses
def parse_upload_response(resp_json: dict) -> dict:
    """
    Expected upload response:
      { "job_id": "...", "status": "finished"|"queued", "count": N, ...}
    """
    return {
        "job_id": resp_json.get("job_id"),
        "status": resp_json.get("status", "unknown"),
        "count": resp_json.get("count", 0)
    }

@bot.event
async def on_ready():
    logger.info(f"Discord bot logged in as {bot.user} (id={bot.user.id})")
    print(f"Discord bot ready: {bot.user} (id={bot.user.id})")

@bot.event
async def on_message(message: discord.Message):
    # ignore messages from ourselves
    if message.author == bot.user:
        return

    # If message has attachments, handle first relevant one
    if message.attachments:
        # Find first CSV or text-like file
        candidate = None
        for att in message.attachments:
            name = att.filename.lower()
            # Accept csv, txt, .tsv, .commit lists etc.
            if name.endswith(".csv") or name.endswith(".txt") or "commit" in name:
                candidate = att
                break
        # if none found, consider the first attachment (opt-in)
        if not candidate:
            candidate = message.attachments[0]

        # Download and upload asynchronously
        await handle_attachment_upload(message, candidate)
    # allow command processing too
    await bot.process_commands(message)

async def handle_attachment_upload(message: discord.Message, attachment: discord.Attachment):
    """
    Download attachment bytes and send to RepoDiff API.
    Acknowledge immediately and then return job id when API replies.
    """
    channel = message.channel
    author = message.author

    ack_msg = await channel.send(f"Thanks <@{author.id}> — downloading `{attachment.filename}` and uploading to RepoDiff...")

    try:
        # download bytes via aiohttp
        file_bytes = await attachment.read()
    except Exception as e:
        logger.exception("Failed to download attachment from Discord")
        await ack_msg.edit(content=f"Failed to download `{attachment.filename}`: {e}")
        return

    # upload to API (non-blocking)
    try:
        resp_json = await upload_bytes_to_api(
            api_base=REPODIFF_API_URL,
            filename=attachment.filename,
            file_bytes=file_bytes,
            api_key=REPODIFF_API_KEY,
            github_token=GITHUB_TOKEN,
            timeout=180
        )
    except aiohttp.ClientResponseError as cre:
        logger.exception("API returned error during upload")
        await ack_msg.edit(content=f"Failed to upload `{attachment.filename}` to RepoDiff API: {cre.status} {cre.message}")
        return
    except Exception as e:
        logger.exception("Unexpected error uploading to API")
        await ack_msg.edit(content=f"Failed to upload `{attachment.filename}` to RepoDiff API: {e}")
        return

    parsed = parse_upload_response(resp_json)
    job_id = parsed.get("job_id")
    status = parsed.get("status")

    # edit ack message with job id & short info
    text = f"Uploaded `{attachment.filename}` — job id: `{job_id}` (status: {status}).\n"
    text += f"Use `!repodiff summary {job_id}` to fetch a quick summary, or open the repo UI if available."
    await ack_msg.edit(content=text)

# Slash-like command to fetch a summary on demand
@bot.command(name="repodiff")
async def repodiff(ctx: commands.Context, action: Optional[str] = None, arg: Optional[str] = None):
    """
    Usage:
      !repodiff summary <job_id>
    """
    if action is None:
        await ctx.reply("Usage: `!repodiff summary <job_id>`")
        return

    if action.lower() == "summary":
        if not arg:
            await ctx.reply("Usage: `!repodiff summary <job_id>`")
            return
        job_id = arg.strip()
        await ctx.reply(f"Fetching summary for `{job_id}`...")

        headers = build_api_headers(api_key=REPODIFF_API_KEY)
        url = f"{REPODIFF_API_URL.rstrip('/')}/summary?job_id={job_id}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, timeout=30) as r:
                    if r.status == 200:
                        data = await r.json()
                        results = data.get("results", [])
                        compact = compact_results_text(results, max_repos=8)
                        # send compact result (small)
                        await ctx.send(f"*Summary for* `{job_id}`:\n{compact}")
                    elif r.status == 202:
                        await ctx.send(f"Job `{job_id}` is still running. Please try again later.")
                    else:
                        text = await r.text()
                        await ctx.send(f"Failed to fetch summary for `{job_id}`: {r.status} {text}")
            except Exception as e:
                await ctx.send(f"Error fetching summary: {e}")
    else:
        await ctx.reply("Unknown action. Supported: `summary`")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
