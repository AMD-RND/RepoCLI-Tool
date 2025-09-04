import requests
from urllib.parse import urlparse

def parse_github_repo(repo_url):
    """
    Extract <owner>/<repo> from GitHub repo URL.
    Example: https://github.com/example-org/pybind11 -> example-org/pybind11
    """
    parsed = urlparse(repo_url)
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    raise ValueError(f"Invalid GitHub repo URL: {repo_url}")

def compare_commits_github(repo_url, old_commit, new_commit, github_token=None):
    """
    Use GitHub Compare API to get commit diff summary.
    
    Args:
        repo_url (str): GitHub repo URL
        old_commit (str): Old commit SHA
        new_commit (str): New commit SHA
        github_token (str): Optional GitHub personal access token
    
    Returns:
        dict: summary containing commits, files added/modified/removed
    """
    repo_name = parse_github_repo(repo_url)
    api_url = f"https://api.github.com/repos/{repo_name}/compare/{old_commit}...{new_commit}"

    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    response = requests.get(api_url, headers=headers)

    if response.status_code != 200:
        return {
            "error": f"Failed to fetch compare API ({response.status_code})",
            "repo": repo_name,
            "url": api_url,
        }

    data = response.json()

    # Collect commit messages
    commits_summary = [
        f"{c['sha'][:7]} | {c['commit']['author']['name']}: {c['commit']['message'].splitlines()[0]}"
        for c in data.get("commits", [])
    ]

    # Collect file changes
    added, modified, removed = [], [], []
    for f in data.get("files", []):
        if f["status"] == "added":
            added.append(f["filename"])
        elif f["status"] == "modified":
            modified.append(f["filename"])
        elif f["status"] == "removed":
            removed.append(f["filename"])

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
    }
