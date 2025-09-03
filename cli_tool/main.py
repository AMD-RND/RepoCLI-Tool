import argparse
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from cli_tool.utils import load_commits_from_csv

def main():
    parser = argparse.ArgumentParser(description="Repo Diff Bot CLI")
    parser.add_argument("--commits", required=True, help="Path to commits.csv")
    args = parser.parse_args()

    print("📂 Loading commits file...")
    commits = load_commits_from_csv(args.commits)

    # Print only the first 3 repositories as in the example output
    display_count = min(3, len(commits))
    print(f"✅ Loaded {display_count} repositories:")
    for c in commits[:display_count]:
        # Show only first 7 characters of commit hashes as in the example
        old_commit = c['old_commit'][:7]
        new_commit = c['new_commit'][:7]
        print(f" - {c['repo_url']} | {old_commit} → {new_commit}")
