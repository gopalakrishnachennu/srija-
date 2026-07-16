import ast
import os
import re
import tempfile
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel, Field

from repository_service import clone_repository


MAX_FILES = 20
MAX_FILE_CHARACTERS = 12_000
MAX_TOTAL_CHARACTERS = 80_000

IGNORED_FOLDERS = {
    ".git",
    ".github",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
}

SAFE_CONFIG_FILES = {
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "pytest.ini",
    "conftest.py",
}

SECRET_ASSIGNMENT = re.compile(
    r"(?i)^\s*([A-Z0-9_]*(?:password|secret|token|api_key)[A-Z0-9_]*)\s*=.*$"
)


class GeneratedTest(BaseModel):
    file_path: str = Field(description="Path below generated_tests ending in .py")
    test_name: str = Field(description="One pytest function name beginning with test_")
    content: str = Field(description="Complete executable Python test-file content")
    purpose: str = Field(description="Short explanation of the behavior being tested")


class GeneratedTestBatch(BaseModel):
    tests: list[GeneratedTest]


def generator_status():
    return {
        "configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "model": os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
    }


def redact_secrets(content):
    """Remove obvious hard-coded credentials before source is sent to the model."""
    safe_lines = []
    for line in content.splitlines():
        match = SECRET_ASSIGNMENT.match(line)
        if match:
            safe_lines.append(f'{match.group(1)} = "[REDACTED]"')
        else:
            safe_lines.append(line)
    return "\n".join(safe_lines)


def collect_source_files(repository_root):
    """Collect a bounded amount of useful Python context and skip secrets/binaries."""
    candidates = []
    for path in repository_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(repository_root)
        if any(part in IGNORED_FOLDERS or part.startswith(".") for part in relative.parts):
            continue
        if path.suffix == ".py" or path.name in SAFE_CONFIG_FILES:
            candidates.append(path)

    # Existing tests and configuration are especially useful for fixtures and imports.
    candidates.sort(
        key=lambda path: (
            0 if "test" in path.name or path.name == "conftest.py" else 1,
            0 if path.name in SAFE_CONFIG_FILES else 1,
            len(path.parts),
            str(path),
        )
    )

    files = []
    total_characters = 0
    for path in candidates[:MAX_FILES]:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        content = redact_secrets(content[:MAX_FILE_CHARACTERS])
        remaining = MAX_TOTAL_CHARACTERS - total_characters
        if remaining <= 0:
            break
        content = content[:remaining]
        files.append(
            {
                "path": path.relative_to(repository_root).as_posix(),
                "content": content,
            }
        )
        total_characters += len(content)
    return files


def build_generation_prompt(repository_url, commit_sha, source_files):
    file_sections = []
    for source_file in source_files:
        file_sections.append(
            f"\n--- FILE: {source_file['path']} ---\n{source_file['content']}\n--- END FILE ---"
        )

    return f"""
Repository: {repository_url}
Commit: {commit_sha}

Generate 3 to 6 meaningful pytest tests for the supplied Python repository.

Requirements:
- Test real application behavior, validation, authorization, error handling, or API contracts.
- Reuse fixtures and import styles that already exist in the repository.
- Return one standalone test function per GeneratedTest object.
- Each file_path must be unique and start with generated_tests/test_ and end with .py.
- Each test_name must start with test_.
- The content must be a complete executable Python test file containing that exact function.
- Do not use network calls, shell commands, destructive actions, sleeps, or external services.
- Do not invent endpoints, fixtures, models, or functions that are not supported by the source.
- Prefer deterministic assertions that execute quickly.
- Include any required imports in content.

Repository files:
{''.join(file_sections)}
""".strip()


def validate_generated_tests(tests):
    if not 1 <= len(tests) <= 8:
        raise ValueError("The generator must return between 1 and 8 tests")

    validated = []
    seen_paths = set()
    seen_names = set()
    for test in tests:
        path = Path(test.file_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Generated test path must stay inside generated_tests")
        if len(path.parts) != 2 or path.parts[0] != "generated_tests":
            raise ValueError("Generated tests must be placed directly in generated_tests")
        if not path.name.startswith("test_") or path.suffix != ".py":
            raise ValueError("Generated filename must match generated_tests/test_*.py")
        if test.file_path in seen_paths:
            raise ValueError("Generated test file paths must be unique")
        if not test.test_name.startswith("test_") or not test.test_name.isidentifier():
            raise ValueError("Generated test names must be valid pytest function names")
        if test.test_name in seen_names:
            raise ValueError("Generated test names must be unique")

        tree = ast.parse(test.content)
        functions = {
            item.name
            for item in tree.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if test.test_name not in functions:
            raise ValueError(f"Generated content does not define {test.test_name}")

        seen_paths.add(test.file_path)
        seen_names.add(test.test_name)
        validated.append(test)
    return validated


def generate_tests_for_repository(repository_url, commit_sha):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "AI generation is not configured. Add a replacement OPENAI_API_KEY to .env.local and restart Flask."
        )

    with tempfile.TemporaryDirectory(prefix="repo_generate_") as temp_dir:
        root = Path(temp_dir) / "repository"
        clone_repository(repository_url, commit_sha, root)
        source_files = collect_source_files(root)

    if not source_files:
        raise RuntimeError("No supported Python source files were found for generation")

    prompt = build_generation_prompt(repository_url, commit_sha, source_files)
    client = OpenAI(api_key=api_key, timeout=120.0, max_retries=2)
    try:
        response = client.responses.parse(
            model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior Python test engineer. Generate safe, deterministic, "
                        "repository-grounded pytest tests and follow the output schema exactly."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            text_format=GeneratedTestBatch,
        )
    except Exception as error:
        raise RuntimeError(f"OpenAI test generation failed: {error}") from error

    if not response.output_parsed:
        raise RuntimeError("The model did not return structured test cases")
    return validate_generated_tests(response.output_parsed.tests)
