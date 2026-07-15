import ast
import hashlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse


def validate_repository_url(repository_url):
    """This small demo intentionally accepts only public GitHub HTTPS URLs."""
    parsed = urlparse(repository_url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise ValueError("Enter a public GitHub HTTPS URL, for example https://github.com/user/repo")
    if len([part for part in parsed.path.split("/") if part]) < 2:
        raise ValueError("The GitHub URL must include an owner and repository name")
    return repository_url.removesuffix("/").removesuffix(".git")


def run_command(command, cwd=None, timeout=120):
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(message or f"Command failed: {' '.join(command)}")
    return completed.stdout


def latest_commit(repository_url):
    output = run_command(["git", "ls-remote", repository_url, "HEAD"], timeout=30)
    if not output.strip():
        raise RuntimeError("Could not find the repository HEAD commit")
    return output.split()[0]


def clone_repository(repository_url, commit_sha, destination):
    run_command(["git", "clone", "--quiet", repository_url, str(destination)], timeout=120)
    run_command(["git", "checkout", "--quiet", commit_sha], cwd=destination, timeout=30)


def discover_tests(repository_root):
    """Find ordinary pytest functions without importing or running repository code."""
    discovered = []
    patterns = ("test_*.py", "*_test.py")
    files = {path for pattern in patterns for path in repository_root.rglob(pattern)}

    for path in sorted(files):
        if any(part.startswith(".") for part in path.relative_to(repository_root).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue

        relative_path = path.relative_to(repository_root).as_posix()
        for item in tree.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test_"):
                discovered.append(f"{relative_path}::{item.name}")
            elif isinstance(item, ast.ClassDef) and item.name.startswith("Test"):
                for method in item.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith("test_"):
                        discovered.append(f"{relative_path}::{item.name}::{method.name}")
    return discovered


def scan_repository(repository_url):
    commit_sha = latest_commit(repository_url)
    with tempfile.TemporaryDirectory(prefix="repo_scan_") as temp_dir:
        root = Path(temp_dir) / "repository"
        clone_repository(repository_url, commit_sha, root)
        return commit_sha, discover_tests(root)


def generated_smoke_test():
    """Temporary adapter. Replace this function with the generator team's API call."""
    node_id = "generated_tests/test_repository_smoke.py::test_repository_has_python_files"
    content = '''from pathlib import Path


def test_repository_has_python_files():
    assert list(Path(".").rglob("*.py")), "Repository does not contain a Python file"
'''
    return node_id, content


def make_idempotency_key(repository_url, commit_sha, test_ids):
    raw_value = "|".join([repository_url, commit_sha, *sorted(map(str, test_ids))])
    return hashlib.sha256(raw_value.encode("utf-8")).hexdigest()


def execute_tests(repository_url, commit_sha, test_cases):
    """Run selected tests one by one so every test gets a clear result."""
    results = []
    with tempfile.TemporaryDirectory(prefix="repo_run_") as temp_dir:
        root = Path(temp_dir) / "repository"
        clone_repository(repository_url, commit_sha, root)

        for test_case in test_cases:
            if test_case.content:
                file_name = test_case.node_id.split("::", 1)[0]
                destination = root / file_name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(test_case.content, encoding="utf-8")

            started = time.monotonic()
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", test_case.node_id],
                cwd=root,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            duration = round(time.monotonic() - started, 3)
            output = (completed.stdout + "\n" + completed.stderr).strip()
            results.append(
                {
                    "test_case_id": test_case.id,
                    "node_id": test_case.node_id,
                    "status": "passed" if completed.returncode == 0 else "failed",
                    "duration_seconds": duration,
                    "output": output[-10000:],
                }
            )
    return results

