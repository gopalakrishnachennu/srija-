# Simple GitHub Test Runner

This project accepts a public GitHub repository, discovers pytest tests, lets the
user select tests, executes them, and stores each result in a database.

It is intentionally small: **Streamlit + Flask + SQLAlchemy**. There is no Redis
and no background queue. Test execution is synchronous, so the browser waits for
the Flask response.

## What each button does

1. **Scan** clones the current commit and finds pytest test functions using Python's AST.
2. **Generate** adds one demo smoke test. Replace `generated_smoke_test()` in
   `repository_service.py` with the other team's API call later.
3. **Execute** runs all selected tests and saves pass/fail output in the database.

## Idempotency

Before execution, the API hashes the repository URL, exact commit SHA, and sorted
test IDs. `test_run.idempotency_key` has a database unique constraint. Therefore,
the same code and same test selection run only once. Later clicks reuse the saved
run, and a simultaneous duplicate insert is also rejected safely by the database.

## Run locally

Python 3.11 or newer and Git are recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

In a second terminal:

```bash
source .venv/bin/activate
streamlit run streamlit_app.py
```

Open `http://localhost:8501`. SQLite is used automatically for the easiest demo.

To use PostgreSQL instead:

```bash
export DATABASE_URL='postgresql+psycopg://postgres:password@localhost/test_runner'
python app.py
```

## Demo target project

`sample_flask_project/` is a separate tiny Flask login/dashboard application with
four pytest tests. Put that folder in its own public GitHub repository, then paste
its URL into Streamlit.

You can also run its tests directly:

```bash
cd sample_flask_project
pytest -q
```

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/api/scan` | Scan a GitHub repository |
| POST | `/api/generate` | Add the temporary generated test |
| POST | `/api/execute` | Execute selected tests once |
| GET | `/api/runs/<id>` | Read a saved run |

## Deliberate limitations

- Public GitHub repositories only.
- The repository must use dependencies already installed in the runner environment.
- The API handles one request until it finishes; this is suitable for a demo, not a large production system.
- Only run repositories you trust. Production execution should use an isolated container.

