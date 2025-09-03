# Repo Diff Bot

A CLI tool to compare commits between repositories using either GitHub API or local git.

## Features
- Compare old vs new commit IDs
- Summarize commits and file changes
- Works with GitHub (via API) or private repos (via git diff)
- Outputs JSON and CSV summaries

## Usage
```bash
python cli_tool/main.py --commits commits.csv --output summary.json
