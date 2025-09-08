# bots/discord/app.py
import os
import requests
import discord
from discord.ext import commands

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
REPODIFF_API_URL = os.getenv("REPODIFF_API_URL", "http://127.0.0.1:8000")
REPODIFF_API_KEY = os.getenv("REPODIFF_API_KEY", None)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)

intents = discord.Intents.default()
intents.message_content = True  # required to read messages contents in many bots
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Discord bot ready as {bot.user}")

@bot.event
async def on_message(message):
    # ignore self
    if message.author == bot.user:
        return

    # if a message has attachments, attempt to upload the first one
    if message.attachments:
        att = message.attachments[0]
        # optionally filter by filename or mimetype
        if att.filename.endswith(".csv") or att.filename.endswith(".txt"):
            # download bytes
            data = await att.read()
            files = {"file": (att.filename, data)}
            headers = {}
            if REPODIFF_API_KEY:
                headers["x-api-key"] = REPODIFF_API_KEY
            data = {}
            if GITHUB_TOKEN:
                data["github_token"] = GITHUB_TOKEN
            r = requests.post(f"{REPODIFF_API_URL.rstrip('/')}/upload", files=files, data=data, headers=headers, timeout=120)
            r.raise_for_status()
            resp = r.json()
            job_id = resp.get("job_id")
            status = resp.get("status")
            await message.channel.send(f"Uploaded `{att.filename}` — job `{job_id}` (status: {status}).")
    await bot.process_commands(message)

# optional slash-like command
@bot.command(name="repodiff")
async def repodiff(ctx, action: str = None, arg: str = None):
    if action == "summary" and arg:
        headers = {}
        if REPODIFF_API_KEY:
            headers["x-api-key"] = REPODIFF_API_KEY
        r = requests.get(f"{REPODIFF_API_URL.rstrip('/')}/summary?job_id={arg}", headers=headers, timeout=30)
        if r.status_code == 200:
            results = r.json().get("results", [])
            lines = [f"{r['repo']}: commits={r.get('total_commits',0)}" for r in results[:8]]
            await ctx.send("Summary:\n" + "\n".join(lines))
        elif r.status_code == 202:
            await ctx.send(f"Job {arg} still running.")
        else:
            await ctx.send(f"Failed to fetch summary: {r.text}")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
