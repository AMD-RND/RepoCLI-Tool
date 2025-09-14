# bots/shared_utils.py
"""
Shared utility functions for bot implementations.

Provides:
- async upload_bytes_to_api(...) — uploads bytes to RepoDiff API (/upload) using aiohttp.
  Raises aiohttp.ClientResponseError on non-2xx responses with server body in the error message.
- build_api_headers(...) — convenience to build API headers (x-api-key).
- compact_results_text(...) — small text summary used by bots for compact responses.

Notes:
- This file is async-ready and intended to be awaited from bot code.
- If you need synchronous usage, wrap calls with asyncio.run or asyncio.to_thread depending on context.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Dict, Any, List

import aiohttp

logger = logging.getLogger("repodiff.shared_utils")

# default retry/backoff config for uploads
_DEFAULT_RETRIES = 3
_DEFAULT_BACKOFF = 0.5  # seconds, exponential


async def upload_bytes_to_api(
    api_base: str,
    filename: str,
    file_bytes: bytes,
    api_key: Optional[str] = None,
    github_token: Optional[str] = None,
    timeout: int = 120,
    retries: int = _DEFAULT_RETRIES,
    backoff: float = _DEFAULT_BACKOFF,
) -> Dict[str, Any]:
    """
    Upload bytes to POST {api_base}/upload using aiohttp (multipart/form-data).
    Returns parsed JSON response.

    Raises:
        aiohttp.ClientResponseError on HTTP >= 400 responses (message contains server body).
        aiohttp.ClientError on transport/timeout errors.
        ValueError if response JSON decoding fails.
    """
    url = f"{api_base.rstrip('/')}/upload"
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    # data fields (form fields) - only include if present
    form_fields = {}
    if github_token:
        form_fields["github_token"] = github_token

    timeout_obj = aiohttp.ClientTimeout(total=timeout)

    attempt = 0
    while True:
        attempt += 1
        try:
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                form = aiohttp.FormData()
                # add file field; content_type left generic
                form.add_field("file", file_bytes, filename=filename, content_type="application/octet-stream")
                # add other form fields (if any)
                for k, v in form_fields.items():
                    form.add_field(k, str(v))

                logger.debug("Uploading file %s to %s (attempt %d)", filename, url, attempt)
                async with session.post(url, data=form, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        # Construct a ClientResponseError with server body to aid debugging
                        logger.error("Upload failed status=%s body=%s", resp.status, text[:1000])
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                            message=text,
                            headers=resp.headers,
                        )
                    # Try parse json, but be robust
                    try:
                        return await resp.json()
                    except Exception as e:
                        logger.exception("Failed to parse JSON response from upload (status=%s) - body: %s", resp.status, text[:1000])
                        raise ValueError(f"Upload succeeded (status={resp.status}) but response JSON parsing failed: {e}; body: {text[:2000]}")

        except (aiohttp.ClientResponseError):
            # server returned >=400 — don't retry on 4xx except maybe 429
            # if 429 (rate limit) retry; otherwise re-raise
            # we already raised ClientResponseError with status, allow caller to inspect.
            # check status code in exception message if needed
            # re-raise to caller
            raise
        except Exception as exc:
            # Transport error, timeout, or other — allow retry
            logger.warning("Upload attempt %d failed: %s", attempt, exc)
            if attempt > retries:
                logger.error("Exceeded upload retries (%d). Failing.", retries)
                raise
            sleep_for = backoff * (2 ** (attempt - 1))
            logger.info("Retrying upload in %.2fs (attempt %d/%d)", sleep_for, attempt + 1, retries + 1)
            await asyncio.sleep(sleep_for)


def build_api_headers(api_key: Optional[str] = None) -> Dict[str, str]:
    """
    Build headers used when calling the RepoDiff API.
    """
    headers: Dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def compact_results_text(results: List[Dict[str, Any]], max_repos: int = 8) -> str:
    """
    Build a compact multi-line summary for bots.
    Example lines:
      repo/name: commits=12, +3 ~1 -0
    """
    lines: List[str] = []
    for i, r in enumerate(results):
        if i >= max_repos:
            remaining = len(results) - max_repos
            lines.append(f"...and {remaining} more repos.")
            break
        repo = r.get("repo") or r.get("url") or r.get("name") or "unknown"
        total = r.get("total_commits", 0)
        added = r.get("files_added") or []
        modified = r.get("files_modified") or []
        removed = r.get("files_removed") or []
        files = []
        if added:
            files.append(f"+{len(added)}")
        if modified:
            files.append(f"~{len(modified)}")
        if removed:
            files.append(f"-{len(removed)}")
        files_part = " ".join(files) if files else "no file changes"
        lines.append(f"{repo}: commits={total}, {files_part}")
    return "\n".join(lines) if lines else "No results."
