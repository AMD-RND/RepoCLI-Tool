# bots/shared_utils.py
"""
Shared utility functions for bot implementations.

- upload_bytes_to_api: upload file bytes to RepoDiff API (async, aiohttp)
- build_api_headers: builds headers for API calls (x-api-key or Authorization)
- compact_results_text: build a compact human-friendly summary string from API results
"""

import aiohttp
import asyncio
from typing import Optional, Dict, Any, List

# ---- Upload helper ----
async def upload_bytes_to_api(
    api_base: str,
    filename: str,
    file_bytes: bytes,
    api_key: Optional[str] = None,
    github_token: Optional[str] = None,
    timeout: int = 120
) -> Dict[str, Any]:
    """
    Upload bytes to POST {api_base}/upload using aiohttp (multipart/form-data).
    Returns parsed JSON response or raises aiohttp.ClientResponseError on non-2xx.
    """
    url = f"{api_base.rstrip('/')}/upload"
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    data = {}
    if github_token:
        data["github_token"] = github_token

    # aiohttp multipart
    timeout_obj = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_obj) as session:
        form = aiohttp.FormData()
        form.add_field("file", file_bytes, filename=filename, content_type="application/octet-stream")
        for k, v in data.items():
            form.add_field(k, v)
        async with session.post(url, data=form, headers=headers) as resp:
            if resp.status >= 400:
                text = await resp.text()
                # raise to be handled by caller
                raise aiohttp.ClientResponseError(
                    resp.request_info, resp.history, status=resp.status, message=text
                )
            return await resp.json()

# ---- Header helper ----
def build_api_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key
    return headers

# ---- Compact results helper ----
def compact_results_text(results: List[Dict], max_repos: int = 8) -> str:
    """
    Build compact multi-line summary for small Slack/Discord messages.
    """
    lines = []
    for i, r in enumerate(results):
        if i >= max_repos:
            lines.append(f"...and {len(results) - max_repos} more repos.")
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
        lines.append(f"{repo}: commits={total}, {files_part}")
    return "\n".join(lines) if lines else "No results."
