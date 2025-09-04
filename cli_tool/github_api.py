import requests
from urllib.parse import urlparse

def parse_github_repo(repo_url):
    parsed = urlparse(repo_url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1].replace('.git','')}"
    raise ValueError(f"Invalid GitHub repo URL: {repo_url}")

def compare_commits_github(repo_url, old_commit, new_commit, github_token=None):
    repo_name = parse_github_repo(repo_url)
    api_url = f"https://api.github.com/repos/{repo_name}/compare/{old_commit}...{new_commit}"

    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    resp = requests.get(api_url, headers=headers, timeout=30)
    if resp.status_code != 200:
        return {
            "repo": repo_name,
            "url": repo_url,
            "old_commit": old_commit,
            "new_commit": new_commit,
            "compare_url": api_url,
            "error": f"GitHub API {resp.status_code}: {resp.text[:200]}",
        }

    data = resp.json()

    commits_summary = [
        f"{c['sha'][:7]} | {c['commit']['author']['name']}: {c['commit']['message'].splitlines()[0]}"
        for c in data.get("commits", [])
    ]

    added, modified, removed = [], [], []
    for f in data.get("files", []):
        st = f.get("status")
        fn = f.get("filename")
        if st == "added":
            added.append(fn)
        elif st == "modified":
            modified.append(fn)
        elif st == "removed":
            removed.append(fn)

    return {
        "repo": repo_name,
        "url": repo_url,
        "old_commit": old_commit,
        "new_commit": new_commit,
        "compare_url": api_url,
        "total_commits": data.get("total_commits", 0),
        "commit_messages": commits_summary,
        "files_added": added,
        "files_modified": modified,
        "files_removed": removed,
        "error": None,
    }
