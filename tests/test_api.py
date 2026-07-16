from unittest.mock import patch

import pytest

from app import create_app
from database import db
from generator_service import GeneratedTest


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


def test_flask_api_root_redirects_to_streamlit(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"] == "http://localhost:8501"


def test_scan_rejects_non_github_url(client):
    response = client.post(
        "/api/scan", json={"repository_url": "https://example.com/project"}
    )
    assert response.status_code == 400
    assert "public GitHub HTTPS URL" in response.json["error"]


def test_generate_requires_a_scanned_project(client):
    response = client.post(
        "/api/generate", json={"project_id": 999, "commit_sha": "a" * 40}
    )
    assert response.status_code == 400
    assert response.json["error"] == "Scan a repository before generating tests"


@patch("app.generate_tests_for_repository")
@patch("app.scan_repository")
def test_generate_saves_ai_tests_and_reuses_them(mock_scan, mock_generate, client):
    mock_scan.return_value = ("d" * 40, ["tests/test_app.py::test_home"])
    mock_generate.return_value = [
        GeneratedTest(
            file_path="generated_tests/test_login_required.py",
            test_name="test_dashboard_requires_login",
            content=(
                "from sample_flask_project.app import create_app\n\n"
                "def test_dashboard_requires_login():\n"
                "    client = create_app({'TESTING': True}).test_client()\n"
                "    assert client.get('/dashboard').status_code == 302\n"
            ),
            purpose="Verify dashboard authorization",
        )
    ]
    scan = client.post(
        "/api/scan", json={"repository_url": "https://github.com/example/ai-demo"}
    ).json
    payload = {"project_id": scan["project_id"], "commit_sha": scan["commit_sha"]}

    first = client.post("/api/generate", json=payload)
    second = client.post("/api/generate", json=payload)

    assert first.status_code == 200
    assert first.json["generation_reused"] is False
    assert any(test["source"] == "generated" for test in first.json["tests"])
    assert second.json["generation_reused"] is True
    mock_generate.assert_called_once()


@patch("app.generate_tests_for_repository")
@patch("app.scan_repository")
def test_legacy_demo_test_does_not_block_ai_generation(mock_scan, mock_generate, client):
    mock_scan.return_value = ("e" * 40, [])
    scan = client.post(
        "/api/scan", json={"repository_url": "https://github.com/example/legacy-demo"}
    ).json

    from database import TestCase

    with client.application.app_context():
        db.session.add(
            TestCase(
                project_id=scan["project_id"],
                commit_sha=scan["commit_sha"],
                node_id=(
                    "generated_tests/test_repository_smoke.py::"
                    "test_repository_has_python_files"
                ),
                source="legacy_demo",
                content="def test_repository_has_python_files():\n    assert True\n",
            )
        )
        db.session.commit()

    mock_generate.return_value = [
        GeneratedTest(
            file_path="generated_tests/test_real_behavior.py",
            test_name="test_real_behavior",
            content="def test_real_behavior():\n    assert 2 + 2 == 4\n",
            purpose="Verify real behavior",
        )
    ]
    response = client.post(
        "/api/generate",
        json={"project_id": scan["project_id"], "commit_sha": scan["commit_sha"]},
    )

    assert response.status_code == 200
    assert response.json["generation_reused"] is False
    assert all(test["source"] != "legacy_demo" for test in response.json["tests"])
    mock_generate.assert_called_once()


def test_execute_requires_at_least_one_test(client):
    response = client.post(
        "/api/execute",
        json={"project_id": 1, "commit_sha": "a" * 40, "test_ids": []},
    )
    assert response.status_code == 400
    assert "at least one test" in response.json["error"]


def test_dashboard_starts_with_zero_counts(client):
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    assert response.json["project_count"] == 0
    assert response.json["run_count"] == 0
    assert response.json["recent_runs"] == []


def test_database_view_lists_all_tables(client):
    response = client.get("/api/database")
    assert response.status_code == 200
    assert set(response.json["tables"]) == {
        "project",
        "repository_scan",
        "test_case",
        "test_run",
        "test_result",
    }
    assert response.json["tables"]["project"]["rows"] == []


@patch("app.execute_tests")
@patch("app.scan_repository")
def test_history_and_projects_show_saved_execution(mock_scan, mock_execute, client):
    mock_scan.return_value = ("c" * 40, ["tests/test_login.py::test_valid_login"])
    scan = client.post(
        "/api/scan", json={"repository_url": "https://github.com/example/history-demo"}
    ).json
    test_id = scan["tests"][0]["id"]
    mock_execute.return_value = [
        {
            "test_case_id": test_id,
            "node_id": "tests/test_login.py::test_valid_login",
            "status": "passed",
            "duration_seconds": 0.2,
            "output": "1 passed",
        }
    ]
    client.post(
        "/api/execute",
        json={
            "project_id": scan["project_id"],
            "commit_sha": scan["commit_sha"],
            "test_ids": [test_id],
        },
    )

    history = client.get("/api/runs").json["runs"]
    projects = client.get("/api/projects").json["projects"]
    dashboard = client.get("/api/dashboard").json

    assert len(history) == 1
    assert history[0]["passed_count"] == 1
    assert history[0]["results"][0]["node_id"].endswith("test_valid_login")
    assert projects[0]["run_count"] == 1
    assert projects[0]["last_commit"] == "c" * 40
    assert dashboard["run_count"] == 1
    assert dashboard["passed_count"] == 1


@patch("app.scan_repository")
def test_scan_saves_discovered_tests(mock_scan, client):
    mock_scan.return_value = ("a" * 40, ["tests/test_login.py::test_login"])
    response = client.post(
        "/api/scan", json={"repository_url": "https://github.com/example/demo"}
    )
    assert response.status_code == 200
    assert response.json["commit_sha"] == "a" * 40
    assert response.json["tests"][0]["node_id"] == "tests/test_login.py::test_login"


@patch("app.scan_repository")
def test_scan_saves_repository_test_code_for_viewing(mock_scan, client):
    source = "def test_login():\n    assert True\n"
    mock_scan.return_value = (
        "f" * 40,
        [{"node_id": "tests/test_login.py::test_login", "content": source}],
    )
    scan = client.post(
        "/api/scan", json={"repository_url": "https://github.com/example/code-view"}
    ).json

    response = client.get(f"/api/tests/{scan['tests'][0]['id']}")
    assert response.status_code == 200
    assert response.json["content"] == source


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
