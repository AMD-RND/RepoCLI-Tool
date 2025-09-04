import csv
import json
import re
from urllib.parse import urlparse
import pandas as pd

SHA_RE = re.compile(r"^[0-9a-fA-F]{6,40}$")

def is_valid_sha(s: str) -> bool:
    return bool(SHA_RE.match(s or ""))

def is_github_url(url: str) -> bool:
    try:
        netloc = urlparse(url).netloc.lower()
        return "github.com" in netloc
    except Exception:
        return False

def validate_row(row, idx):
    # required columns present?
    for k in ("repo_url", "old_commit", "new_commit"):
        if k not in row or not str(row[k]).strip():
            raise ValueError(f"Row {idx}: missing '{k}'")

    # basic SHA sanity (6..40 hex chars; allows short SHAs)
    if not is_valid_sha(row["old_commit"]):
        raise ValueError(f"Row {idx}: invalid old_commit '{row['old_commit']}'")
    if not is_valid_sha(row["new_commit"]):
        raise ValueError(f"Row {idx}: invalid new_commit '{row['new_commit']}'")

def load_commits_from_csv(filepath):
    """
    CSV columns: repo_url,old_commit,new_commit
    Returns list of dicts with those keys.
    """
    commits = []
    with open(filepath, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        expected = {"repo_url", "old_commit", "new_commit"}
        if set((reader.fieldnames or [])) < expected:
            raise ValueError(
                f"CSV must have headers: {', '.join(sorted(expected))}. "
                f"Found: {reader.fieldnames}"
            )
        for i, row in enumerate(reader, start=2):  # header is line 1
            row = {k: (row.get(k, "") or "").strip() for k in expected}
            validate_row(row, i)
            commits.append(row)
    return commits

def save_results_json(results, filepath):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

def save_results_csv(results, filepath):
    df = pd.DataFrame(results)
    df.to_csv(filepath, index=False)

def summarize_counts(results):
    total = len(results)
    failures = sum(1 for r in results if r.get("error"))
    unchanged = sum(1 for r in results if not r.get("error") and r.get("old_commit") == r.get("new_commit"))
    changed = total - failures - unchanged
    return {"total": total, "changed": changed, "unchanged": unchanged, "failures": failures}
