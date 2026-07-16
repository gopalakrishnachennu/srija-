import pytest

from generator_service import (
    GeneratedTest,
    collect_source_files,
    redact_secrets,
    validate_generated_tests,
)


def generated_test(**changes):
    values = {
        "file_path": "generated_tests/test_login.py",
        "test_name": "test_invalid_login",
        "content": "def test_invalid_login():\n    assert True\n",
        "purpose": "Reject invalid credentials",
    }
    values.update(changes)
    return GeneratedTest(**values)


def test_validate_generated_test_accepts_safe_pytest_code():
    result = validate_generated_tests([generated_test()])
    assert result[0].test_name == "test_invalid_login"


@pytest.mark.parametrize(
    "file_path",
    ["../test_bad.py", "/tmp/test_bad.py", "tests/test_bad.py", "generated_tests/helper.py"],
)
def test_validate_generated_test_rejects_unsafe_path(file_path):
    with pytest.raises(ValueError):
        validate_generated_tests([generated_test(file_path=file_path)])


def test_validate_generated_test_requires_named_function():
    with pytest.raises(ValueError, match="does not define"):
        validate_generated_tests(
            [generated_test(content="def test_something_else():\n    assert True\n")]
        )


def test_redact_secrets_removes_obvious_assignments():
    content = 'API_KEY = "private-value"\nNORMAL_VALUE = "safe"'
    redacted = redact_secrets(content)
    assert "private-value" not in redacted
    assert 'NORMAL_VALUE = "safe"' in redacted


def test_collect_source_files_ignores_env_and_virtual_environment(tmp_path):
    (tmp_path / "app.py").write_text("def home():\n    return 'ok'\n", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=secret", encoding="utf-8")
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "ignored.py").write_text("SECRET='value'", encoding="utf-8")

    files = collect_source_files(tmp_path)
    assert [file["path"] for file in files] == ["app.py"]
