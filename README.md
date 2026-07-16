# Srija💕 Test Runner

This project accepts a public GitHub repository, discovers pytest tests, lets the
user select tests, executes them, and stores each result in a database.

It is intentionally small: **Streamlit + Flask + SQLAlchemy**. There is no Redis
and no background queue. Test execution is synchronous, so the browser waits for
the Flask response.

## What each button does

1. **Scan** clones the current commit and finds pytest test functions using Python's AST.
2. **Generate** sends a bounded, secret-filtered set of repository files to OpenAI
   and stores structured pytest tests after validating their paths and syntax.
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
The Flask API runs on `http://127.0.0.1:5050`; port 5050 avoids the macOS
AirPlay Receiver service that often occupies port 5000.

## Two user-facing applications

| Application | URL | Purpose |
|---|---|---|
| Srija💕 Test Runner | `http://localhost:8501` | Scan repositories and execute tests |
| Srija Portal | `http://127.0.0.1:5001` | Flask login and dashboard application |

Port `5050` is an internal API used by Streamlit. It is not a third application.
Opening it in a browser redirects to the Srija💕 Test Runner.

To use PostgreSQL instead:

```bash
export DATABASE_URL='postgresql+psycopg://postgres:password@localhost/test_runner'
python app.py
```

## Demo target project

`sample_flask_project/` is a separate Flask login/dashboard application with a
realistic authentication test suite. Put that folder in its own public GitHub repository, then paste
its URL into Streamlit.

Start the portal in a third terminal:

```bash
source .venv/bin/activate
python sample_flask_project/app.py
```

Then open `http://127.0.0.1:5001`.

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
| POST | `/api/generate` | Generate and save validated AI tests |
| GET | `/api/generator-status` | Check whether AI generation is configured |
| POST | `/api/execute` | Execute selected tests once |
| GET | `/api/dashboard` | Read dashboard totals and recent runs |
| GET | `/api/projects` | List scanned repositories |
| GET | `/api/runs` | List saved execution history |
| GET | `/api/runs/<id>` | Read a saved run |
| GET | `/api/tests/<id>` | Read the stored source code for a test case |
| GET | `/api/database` | Read all database tables for the local viewer |

## Streamlit views

- **Dashboard** shows project, run, pass, and failure counts.
- **New Test Run** supports test search, source filtering, and selected execution.
- **Run History** filters saved runs, opens full logs, and exports CSV reports.
- **Projects** summarizes every scanned repository and its latest result.
- **Database** displays every table, row, generated test, and execution output.

## Deliberate limitations

- Public GitHub repositories only.
- The repository must use dependencies already installed in the runner environment.
- The API handles one request until it finishes; this is suitable for a demo, not a large production system.
- Only run repositories you trust. Production execution should use an isolated container.
