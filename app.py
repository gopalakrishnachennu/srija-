import os

from flask import Flask, jsonify, request
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
from repository_service import (
    execute_tests,
    generated_smoke_test,
    make_idempotency_key,
    scan_repository,
    validate_repository_url,
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

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.post("/api/scan")
    def scan():
        try:
            repository_url = validate_repository_url(request.json.get("repository_url", ""))
            project = Project.query.filter_by(repository_url=repository_url).first()
            if not project:
                project = Project(repository_url=repository_url)
                db.session.add(project)
                db.session.commit()

            commit_sha, node_ids = scan_repository(repository_url)
            scan_record = RepositoryScan.query.filter_by(
                project_id=project.id, commit_sha=commit_sha
            ).first()
            cached = scan_record is not None
            if not scan_record:
                db.session.add(RepositoryScan(project_id=project.id, commit_sha=commit_sha))

            for node_id in node_ids:
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
                        )
                    )
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

        node_id, content = generated_smoke_test()
        test_case = TestCase.query.filter_by(
            project_id=project.id, commit_sha=commit_sha, node_id=node_id
        ).first()
        if not test_case:
            test_case = TestCase(
                project_id=project.id,
                commit_sha=commit_sha,
                node_id=node_id,
                source="generated",
                content=content,
            )
            db.session.add(test_case)
            db.session.commit()
        return jsonify(scan_response(project, commit_sha, cached=False))

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

    return app


def scan_response(project, commit_sha, cached):
    tests = TestCase.query.filter_by(project_id=project.id, commit_sha=commit_sha).all()
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
    return {
        "run_id": run.id,
        "status": run.status,
        "reused": reused,
        "commit_sha": run.commit_sha,
        "results": [
            {
                "test_case_id": result.test_case_id,
                "status": result.status,
                "duration_seconds": result.duration_seconds,
                "output": result.output,
            }
            for result in results
        ],
    }


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)

