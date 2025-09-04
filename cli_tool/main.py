import argparse
import sys
import os
try:
    from cli_tool.utils import load_commits_from_csv
    from cli_tool.github_api import compare_commits_github
    from cli_tool.git_local import compare_commits_local
except ImportError:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from cli_tool.utils import load_commits_from_csv
    from cli_tool.github_api import compare_commits_github
    from cli_tool.git_local import compare_commits_local

def main():
    parser = argparse.ArgumentParser(description="Repo Diff Bot CLI")
    parser.add_argument("--commits", required=True, help="Path to commits.csv")
    parser.add_argument("--token", help="GitHub Personal Access Token (optional)", default=None)
    args = parser.parse_args()

    commits = load_commits_from_csv(args.commits)

    print(f"✅ Loaded {len(commits)} repos to check")

    for c in commits:
        if "github.com" in c["repo_url"]:
            result = compare_commits_github(c["repo_url"], c["old_commit"], c["new_commit"], github_token=args.token)
        else:
            result = compare_commits_local(c["repo_url"], c["old_commit"], c["new_commit"])

        print("\n🔹 Repo:", result["repo"])
        print("   Old:", result["old_commit"])
        print("   New:", result["new_commit"])
        print("   Commits Changed:", result["total_commits"])
        if "commit_messages" in result:
            for m in result["commit_messages"]:
                print("     -", m)
        if result["files_added"]:
            print("   ✅ Added:", result["files_added"])
        if result["files_modified"]:
            print("   🔄 Modified:", result["files_modified"])

        if result["files_removed"]:
            print("   ❌ Removed:", result["files_removed"])


# Standard Python entry point
if __name__ == "__main__":
    main()
