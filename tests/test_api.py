from unittest.mock import patch

import pytest

from app import create_app
from database import db


@pytest.fixture()
def client():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )
    with app.test_client() as client:
        yield client
    with app.app_context():
        db.drop_all()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


@patch("app.scan_repository")
def test_scan_saves_discovered_tests(mock_scan, client):
    mock_scan.return_value = ("a" * 40, ["tests/test_login.py::test_login"])
    response = client.post(
        "/api/scan", json={"repository_url": "https://github.com/example/demo"}
    )
    assert response.status_code == 200
    assert response.json["commit_sha"] == "a" * 40
    assert response.json["tests"][0]["node_id"] == "tests/test_login.py::test_login"


@patch("app.execute_tests")
@patch("app.scan_repository")
def test_duplicate_execution_reuses_first_run(mock_scan, mock_execute, client):
    mock_scan.return_value = ("b" * 40, ["tests/test_app.py::test_home"])
    scan = client.post(
        "/api/scan", json={"repository_url": "https://github.com/example/demo"}
    ).json
    test_id = scan["tests"][0]["id"]
    mock_execute.return_value = [
        {
            "test_case_id": test_id,
            "node_id": "tests/test_app.py::test_home",
            "status": "passed",
            "duration_seconds": 0.1,
            "output": "1 passed",
        }
    ]
    payload = {
        "project_id": scan["project_id"],
        "commit_sha": scan["commit_sha"],
        "test_ids": [test_id],
    }

    first = client.post("/api/execute", json=payload).json
    second = client.post("/api/execute", json=payload).json

    assert first["reused"] is False
    assert second["reused"] is True
    assert first["run_id"] == second["run_id"]
    mock_execute.assert_called_once()

