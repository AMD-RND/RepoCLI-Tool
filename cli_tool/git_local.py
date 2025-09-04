import os
import subprocess

BASE_CLONE_DIR = "repos"  # where repos will be cloned locally

def run_cmd(cmd, cwd=None):
    """Run shell command and return output."""
    result = subprocess.run(cmd, cwd=cwd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{result.stderr}")
    return result.stdout.strip()

def ensure_repo_cloned(repo_url):
    """
    Clone repo into BASE_CLONE_DIR if not already cloned.
    Returns path to repo folder.
    """
    if not os.path.exists(BASE_CLONE_DIR):
        os.makedirs(BASE_CLONE_DIR, exist_ok=True)

    repo_name = os.path.basename(repo_url).replace(".git", "")
    repo_path = os.path.join(BASE_CLONE_DIR, repo_name)

    if not os.path.exists(repo_path):
        print(f"📥 Cloning {repo_url}...")
        run_cmd(f"git clone {repo_url} {repo_path}")
    else:
        print(f"🔄 Updating {repo_name}...")
        run_cmd("git fetch --all", cwd=repo_path)

    return repo_path

def compare_commits_local(repo_url, old_commit, new_commit):
    """
    Compare two commits locally using git diff.
    Returns summary of commits and file changes.
    """
    repo_path = ensure_repo_cloned(repo_url)

    # Fetch latest to ensure commits exist
    run_cmd("git fetch --all", cwd=repo_path)

    # Get commit log
    log_output = run_cmd(f"git log --oneline {old_commit}..{new_commit}", cwd=repo_path)
    commit_messages = log_output.splitlines() if log_output else []

    # Get file diffs
    diff_output = run_cmd(f"git diff --name-status {old_commit} {new_commit}", cwd=repo_path)

    added, modified, removed = [], [], []
    for line in diff_output.splitlines():
        status, filename = line.split("\t", 1)
        if status == "A":
            added.append(filename)
        elif status == "M":
            modified.append(filename)
        elif status == "D":
            removed.append(filename)

    return {
        "repo": os.path.basename(repo_path),
        "url": repo_url,
        "old_commit": old_commit,
        "new_commit": new_commit,
        "compare_url": None,
        "total_commits": len(commit_messages),
        "commit_messages": commit_messages,
        "files_added": added,
        "files_modified": modified,
        "files_removed": removed,
    }
