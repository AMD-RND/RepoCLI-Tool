import csv

def load_commits_from_csv(filepath):
    """
    Load commit data from a CSV file with columns:
    repo_url, old_commit, new_commit
    
    Returns:
        List[dict] -> Example:
        [
            {
                "repo_url": "https://github.com/example-org/pybind11",
                "old_commit": "3e9dfa2",
                "new_commit": "3e9dfa2"
            },
            ...
        ]
    """
    commits = []
    with open(filepath, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            commits.append({
                "repo_url": row["repo_url"].strip(),
                "old_commit": row["old_commit"].strip(),
                "new_commit": row["new_commit"].strip(),
            })
    return commits
