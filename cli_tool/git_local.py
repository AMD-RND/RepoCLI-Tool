import os
import subprocess

BASE_CLONE_DIR = "repos"

def run_cmd(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd, shell=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd}\n{result.stderr.strip()}")
    return result.stdout.strip()

def ensure_repo_cloned(repo_url):
    if not os.path.exists(BASE_CLONE_DIR):
        os.makedirs(BASE_CLONE_DIR, exist_ok=True)

    # repo folder name
    name = os.path.basename(repo_url.rstrip("/")).replace(".git", "")
    repo_path = os.path.join(BASE_CLONE_DIR, name)

    if not os.path.exists(repo_path):
        print(f"📥 cloning {repo_url}...")
        run_cmd(f"git clone {repo_url} {repo_path}")
    else:
        run_cmd("git fetch --all --tags --prune", cwd=repo_path)

    return repo_path

def compare_commits_local(repo_url, old_commit, new_commit):
    repo_path = ensure_repo_cloned(repo_url)
    run_cmd("git fetch --all --tags --prune", cwd=repo_path)

    # commits log
    try:
        log_output = run_cmd(f"git log --oneline {old_commit}..{new_commit}", cwd=repo_path)
    except RuntimeError as e:
        return {
            "repo": os.path.basename(repo_path),
            "url": repo_url,
            "old_commit": old_commit,
            "new_commit": new_commit,
            "compare_url": None,
            "total_commits": 0,
            "commit_messages": [],
            "files_added": [],
            "files_modified": [],
            "files_removed": [],
            "error": f"log failed: {e}",
        }

    commit_messages = log_output.splitlines() if log_output else []

    # file changes
    try:
        diff_output = run_cmd(f"git diff --name-status {old_commit} {new_commit}", cwd=repo_path)
    except RuntimeError as e:
        return {
            "repo": os.path.basename(repo_path),
            "url": repo_url,
            "old_commit": old_commit,
            "new_commit": new_commit,
            "compare_url": None,
            "total_commits": len(commit_messages),
            "commit_messages": commit_messages,
            "files_added": [],
            "files_modified": [],
            "files_removed": [],
            "error": f"diff failed: {e}",
        }

    added, modified, removed = [], [], []
    for line in diff_output.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        status, filename = parts
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
        "error": None,
    }
