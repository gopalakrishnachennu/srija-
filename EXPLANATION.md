# How to explain this project

## One-line explanation

The user submits a public GitHub URL in Streamlit; Flask scans its pytest tests,
runs the selected tests, and SQLAlchemy stores the scan, run, and result data.

## Simple request flow

```text
Streamlit -> Flask API -> clone GitHub repo -> pytest -> database -> Streamlit
```

There is no Redis and no queue. The Execute HTTP request stays open until pytest
finishes. That is acceptable for this small demonstration.

## Files to show

- `streamlit_app.py`: URL input, three buttons, test selection, and results.
- `app.py`: Flask endpoints and database workflow.
- `repository_service.py`: Git clone, test discovery, hashing, and pytest execution.
- `database.py`: SQLAlchemy tables.
- `sample_flask_project/`: the small login/dashboard application used as a target.
- `tests/test_api.py`: proves scanning and idempotency behavior.

The Streamlit sidebar also exposes Dashboard, Run History, and Projects.
Run History comes from the database and can export an individual run as CSV.

## Database tables

1. `project` stores one GitHub repository URL.
2. `repository_scan` stores the exact commit that was scanned.
3. `test_case` stores repository or generated tests for that commit.
4. `test_run` stores one execution request.
5. `test_result` stores pass/fail output for each selected test.

## How idempotency works

The code creates this hash before running pytest:

```text
hash(repository URL + commit SHA + sorted selected test IDs)
```

The hash is stored as `test_run.idempotency_key` and the database requires it to
be unique. Clicking Execute again with the same commit and same tests returns the
old run. If two users send the same request together, only one database insert can
succeed, so the second request reads the first run.

A new commit or a different test selection produces a different hash and therefore
creates a new run.

## Test generation

`generator_service.py` collects a limited set of Python and test files, removes
obvious hard-coded credentials, and requests structured pytest cases from OpenAI.
Generated paths and Python syntax are validated before tests enter the database.
Generating again for the same commit reuses the saved tests instead of spending
tokens again.

## Honest limitation

Without a queue, simultaneous *different* jobs may run at the same time in separate
Flask request threads. Duplicate jobs still cannot run twice because of the unique
database key. For the demonstration, submit only trusted repositories whose Python
dependencies are already installed.

## Suggested demonstration

1. Start Flask and Streamlit.
2. Paste the public URL of the sample Flask repository.
3. Click Scan and show its four discovered tests.
4. Click Generate and show the new AI-generated tests.
5. Select only two tests and click Execute.
6. Click Execute again and show the “existing result reused” message.
7. Explain that selecting a different set creates a different valid run.
