import argparse
from cli_tool.utils import load_commits_from_csv

def main():
    parser = argparse.ArgumentParser(description="Repo Diff Bot CLI")
    parser.add_argument("--commits", required=True, help="Path to commits.csv")
    args = parser.parse_args()

    print("📂 Loading commits file...")
    commits = load_commits_from_csv(args.commits)

    print(f"✅ Loaded {len(commits)} repositories:")
    for c in commits:
        print(f" - {c['repo_url']} | {c['old_commit']} → {c['new_commit']}")

