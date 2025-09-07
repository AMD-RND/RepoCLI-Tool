# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from api.main import app

@pytest.fixture(scope="module")
def client():
    return TestClient(app)

# A small helper: a sample CSV content
@pytest.fixture
def sample_csv_file(tmp_path):
    csv_text = "repo_url,old_commit,new_commit\nhttps://github.com/example-org/sample,aaaaaa,bbbbbb\n"
    p = tmp_path / "sample.csv"
    p.write_text(csv_text)
    return p
