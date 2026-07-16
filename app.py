import os

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request
from sqlalchemy.exc import IntegrityError

from database import (
    Project,
    RepositoryScan,
    TestCase,
    TestResult,
    TestRun,
    db,
    now_utc,
)
from generator_service import generate_tests_for_repository, generator_status
from repository_service import (
    execute_tests,
    make_idempotency_key,
    scan_repository,
    validate_repository_url,
)


load_dotenv(".env.local")

LEGACY_DEMO_NODE_ID = (
    "generated_tests/test_repository_smoke.py::test_repository_has_python_files"
)


def create_app(test_config=None):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", "sqlite:///test_runner.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    with app.app_context():
        db.create_all()
        # Older versions stored a hard-coded smoke test as "generated". Keep its
        # execution history, but never let it appear as or block genuine AI tests.
        legacy_tests = TestCase.query.filter_by(
            node_id=LEGACY_DEMO_NODE_ID, source="generated"
        ).all()
        for legacy_test in legacy_tests:
            legacy_test.source = "legacy_demo"
        if legacy_tests:
            db.session.commit()

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/generator-status")
    def get_generator_status():
        return jsonify(generator_status())

    @app.get("/")
    def home():
        """The API is internal; send browser users to the Streamlit application."""
        return redirect("http://localhost:8501")

    @app.post("/api/scan")
    def scan():
        try:
            repository_url = validate_repository_url(request.json.get("repository_url", ""))
            project = Project.query.filter_by(repository_url=repository_url).first()
            if not project:
                project = Project(repository_url=repository_url)
                db.session.add(project)
                db.session.commit()

            commit_sha, discovered_tests = scan_repository(repository_url)
            scan_record = RepositoryScan.query.filter_by(
                project_id=project.id, commit_sha=commit_sha
            ).first()
            cached = scan_record is not None
            if not scan_record:
                db.session.add(RepositoryScan(project_id=project.id, commit_sha=commit_sha))

            for discovered in discovered_tests:
                # String support keeps the scan service easy to mock in API tests.
                if isinstance(discovered, str):
                    node_id = discovered
                    content = None
                else:
                    node_id = discovered["node_id"]
                    content = discovered.get("content")
                existing = TestCase.query.filter_by(
                    project_id=project.id, commit_sha=commit_sha, node_id=node_id
                ).first()
                if not existing:
                    db.session.add(
                        TestCase(
                            project_id=project.id,
                            commit_sha=commit_sha,
                            node_id=node_id,
                            source="repository",
                            content=content,
                        )
                    )
                elif content and not existing.content:
                    existing.content = content
            db.session.commit()
            return jsonify(scan_response(project, commit_sha, cached))
        except (ValueError, RuntimeError) as error:
            db.session.rollback()
            return jsonify({"error": str(error)}), 400

    @app.post("/api/generate")
    def generate():
        data = request.get_json() or {}
        project = db.session.get(Project, data.get("project_id"))
        commit_sha = data.get("commit_sha")
        if not project or not commit_sha:
            return jsonify({"error": "Scan a repository before generating tests"}), 400

        saved_tests = TestCase.query.filter_by(
            project_id=project.id, commit_sha=commit_sha, source="generated"
        ).all()
        if saved_tests:
            response = scan_response(project, commit_sha, cached=True)
            response["generation_reused"] = True
            return jsonify(response)

        try:
            generated_tests = generate_tests_for_repository(
                project.repository_url, commit_sha
            )
            for generated_test in generated_tests:
                db.session.add(
                    TestCase(
                        project_id=project.id,
                        commit_sha=commit_sha,
                        node_id=f"{generated_test.file_path}::{generated_test.test_name}",
                        source="generated",
                        content=generated_test.content,
                    )
                )
            db.session.commit()
            response = scan_response(project, commit_sha, cached=False)
            response["generation_reused"] = False
            return jsonify(response)
        except (RuntimeError, ValueError, SyntaxError) as error:
            db.session.rollback()
            return jsonify({"error": str(error)}), 400

    @app.post("/api/execute")
    def execute():
        data = request.get_json() or {}
        project = db.session.get(Project, data.get("project_id"))
        commit_sha = data.get("commit_sha")
        test_ids = sorted(set(data.get("test_ids") or []))
        if not project or not commit_sha or not test_ids:
            return jsonify({"error": "Project, commit and at least one test are required"}), 400

        test_cases = TestCase.query.filter(
            TestCase.project_id == project.id,
            TestCase.commit_sha == commit_sha,
            TestCase.id.in_(test_ids),
        ).all()
        if len(test_cases) != len(test_ids):
            return jsonify({"error": "One or more selected tests are invalid"}), 400

        key = make_idempotency_key(project.repository_url, commit_sha, test_ids)
        existing_run = TestRun.query.filter_by(idempotency_key=key).first()
        if existing_run:
            return jsonify(run_response(existing_run, reused=True))

        run = TestRun(
            project_id=project.id,
            commit_sha=commit_sha,
            idempotency_key=key,
            status="running",
        )
        db.session.add(run)
        try:
            db.session.commit()
        except IntegrityError:
            # Another request created the same run between our SELECT and INSERT.
            db.session.rollback()
            existing_run = TestRun.query.filter_by(idempotency_key=key).first()
            return jsonify(run_response(existing_run, reused=True))

        try:
            for result in execute_tests(project.repository_url, commit_sha, test_cases):
                db.session.add(
                    TestResult(
                        run_id=run.id,
                        test_case_id=result["test_case_id"],
                        status=result["status"],
                        duration_seconds=result["duration_seconds"],
                        output=result["output"],
                    )
                )
            run.status = "completed"
        except Exception as error:
            run.status = "failed"
            db.session.add(
                TestResult(
                    run_id=run.id,
                    test_case_id=test_cases[0].id,
                    status="error",
                    duration_seconds=0,
                    output=str(error),
                )
            )
        run.finished_at = now_utc()
        db.session.commit()
        return jsonify(run_response(run, reused=False))

    @app.get("/api/runs/<int:run_id>")
    def get_run(run_id):
        run = db.session.get(TestRun, run_id)
        if not run:
            return jsonify({"error": "Run not found"}), 404
        return jsonify(run_response(run, reused=False))

    @app.get("/api/tests/<int:test_case_id>")
    def get_test_case(test_case_id):
        test_case = db.session.get(TestCase, test_case_id)
        if not test_case:
            return jsonify({"error": "Test case not found"}), 404
        return jsonify(
            {
                "id": test_case.id,
                "node_id": test_case.node_id,
                "source": test_case.source,
                "content": test_case.content,
            }
        )

    @app.get("/api/dashboard")
    def dashboard_summary():
        """Return the small set of numbers used by the Streamlit dashboard."""
        recent_runs = TestRun.query.order_by(TestRun.created_at.desc()).limit(5).all()
        return jsonify(
            {
                "project_count": Project.query.count(),
                "run_count": TestRun.query.count(),
                "passed_count": TestResult.query.filter_by(status="passed").count(),
                "failed_count": TestResult.query.filter(
                    TestResult.status.in_(["failed", "error"])
                ).count(),
                "recent_runs": [run_response(run, reused=False) for run in recent_runs],
            }
        )

    @app.get("/api/runs")
    def list_runs():
        query = TestRun.query
        project_id = request.args.get("project_id", type=int)
        status = request.args.get("status")
        if project_id:
            query = query.filter_by(project_id=project_id)
        if status:
            query = query.filter_by(status=status)
        runs = query.order_by(TestRun.created_at.desc()).all()
        return jsonify({"runs": [run_response(run, reused=False) for run in runs]})

    @app.get("/api/projects")
    def list_projects():
        projects = Project.query.order_by(Project.created_at.desc()).all()
        return jsonify({"projects": [project_response(project) for project in projects]})

    @app.get("/api/database")
    def database_contents():
        """Read-only database viewer used by the local Streamlit dashboard."""
        models = {
            "project": Project,
            "repository_scan": RepositoryScan,
            "test_case": TestCase,
            "test_run": TestRun,
            "test_result": TestResult,
        }
        tables = {}
        for table_name, model in models.items():
            records = model.query.order_by(model.id.desc()).all()
            tables[table_name] = {
                "columns": [column.name for column in model.__table__.columns],
                "row_count": len(records),
                "rows": [serialize_record(record) for record in records],
            }
        return jsonify({"tables": tables})

    return app


def scan_response(project, commit_sha, cached):
    tests = TestCase.query.filter(
        TestCase.project_id == project.id,
        TestCase.commit_sha == commit_sha,
        TestCase.source != "legacy_demo",
    ).all()
    return {
        "project_id": project.id,
        "repository_url": project.repository_url,
        "commit_sha": commit_sha,
        "cached": cached,
        "tests": [
            {"id": test.id, "node_id": test.node_id, "source": test.source}
            for test in tests
        ],
    }


def run_response(run, reused):
    results = TestResult.query.filter_by(run_id=run.id).all()
    project = db.session.get(Project, run.project_id)
    passed_count = sum(result.status == "passed" for result in results)
    failed_count = sum(result.status != "passed" for result in results)
    return {
        "run_id": run.id,
        "project_id": run.project_id,
        "repository_url": project.repository_url if project else "",
        "status": run.status,
        "reused": reused,
        "commit_sha": run.commit_sha,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "test_count": len(results),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "results": [
            {
                "test_case_id": result.test_case_id,
                "node_id": (
                    db.session.get(TestCase, result.test_case_id).node_id
                    if db.session.get(TestCase, result.test_case_id)
                    else "Unknown test"
                ),
                "status": result.status,
                "duration_seconds": result.duration_seconds,
                "output": result.output,
            }
            for result in results
        ],
    }


def project_response(project):
    scans = RepositoryScan.query.filter_by(project_id=project.id).all()
    latest_scan = max(scans, key=lambda scan: scan.created_at) if scans else None
    tests = TestCase.query.filter_by(project_id=project.id).count()
    runs = TestRun.query.filter_by(project_id=project.id).order_by(TestRun.created_at.desc()).all()
    last_run = runs[0] if runs else None
    return {
        "project_id": project.id,
        "repository_url": project.repository_url,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "last_commit": latest_scan.commit_sha if latest_scan else None,
        "test_count": tests,
        "run_count": len(runs),
        "last_run": run_response(last_run, reused=False) if last_run else None,
    }


def serialize_record(record):
    data = {}
    for column in record.__table__.columns:
        value = getattr(record, column.name)
        data[column.name] = value.isoformat() if hasattr(value, "isoformat") else value
    return data


app = create_app()


if __name__ == "__main__":
    # Port 5000 is commonly used by AirPlay Receiver on macOS.
    app.run(debug=True, port=5050)
