# tests/test_api.py
import json
from api.jobs import job_path
from cli_tool import github_api, git_local

def fake_compare_github(repo_url, old_commit, new_commit, github_token=None):
    return {
        "repo": "example-org/sample",
        "url": repo_url,
        "old_commit": old_commit,
        "new_commit": new_commit,
        "compare_url": "https://api.github.com/fake",
        "total_commits": 1,
        "commit_messages": [f"{old_commit[:7]} | Tester: sample change"],
        "files_added": ["new.py"],
        "files_modified": ["mod.py"],
        "files_removed": [],
        "error": None,
    }

def test_upload_and_summary_sync(monkeypatch, client, sample_csv_file):
    # patch compare_commits_github to avoid network
    monkeypatch.setattr("cli_tool.github_api.compare_commits_github", fake_compare_github)

    # upload file (no API key in tests)
    with open(sample_csv_file, "rb") as f:
        resp = client.post("/upload", files={"file": ("sample.csv", f, "text/csv")})
    assert resp.status_code == 200
    data = resp.json()
    job_id = data["job_id"]
    assert data["status"] == "finished"

    # fetch summary
    resp2 = client.get(f"/summary?job_id={job_id}")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["job_id"] == job_id
    assert isinstance(body["results"], list)
    assert body["results"][0]["repo"].startswith("example-org")

def test_repo_endpoint(monkeypatch, client, sample_csv_file):
    monkeypatch.setattr("cli_tool.github_api.compare_commits_github", fake_compare_github)

    with open(sample_csv_file, "rb") as f:
        resp = client.post("/upload", files={"file": ("sample.csv", f, "text/csv")})
    job_id = resp.json()["job_id"]

    # fetch the repo by shortname
    resp3 = client.get(f"/repo/sample?job_id={job_id}")
    assert resp3.status_code == 200
    repo_json = resp3.json()
    assert repo_json["repo"] == "example-org/sample"
