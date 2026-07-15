import os
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


def now_utc():
    """Return a timezone-aware timestamp for database records."""
    return datetime.now(timezone.utc)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    repository_url = db.Column(db.String(500), nullable=False, unique=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)


class RepositoryScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    commit_sha = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), default="completed", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("project_id", "commit_sha", name="uq_project_commit_scan"),
    )


class TestCase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    commit_sha = db.Column(db.String(40), nullable=False)
    node_id = db.Column(db.String(500), nullable=False)
    source = db.Column(db.String(20), nullable=False)  # repository or generated
    content = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint(
            "project_id", "commit_sha", "node_id", name="uq_test_case_version"
        ),
    )


class TestRun(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    commit_sha = db.Column(db.String(40), nullable=False)
    idempotency_key = db.Column(db.String(64), nullable=False, unique=True)
    status = db.Column(db.String(20), default="running", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)


class TestResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey("test_run.id"), nullable=False)
    test_case_id = db.Column(db.Integer, db.ForeignKey("test_case.id"), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    duration_seconds = db.Column(db.Float, nullable=False)
    output = db.Column(db.Text, nullable=True)

