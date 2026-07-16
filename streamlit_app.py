import csv
import io
import os
from datetime import datetime

import requests
import streamlit as st


API_URL = os.getenv("API_URL", "http://127.0.0.1:5050")

st.set_page_config(
    page_title="Srija💕 Test Runner",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {max-width: 1180px; padding-top: 2rem; padding-bottom: 3rem;}
      .hero {padding: 1.6rem 2rem; border-radius: 18px; color: white;
        background: linear-gradient(120deg,#4f46e5,#7c3aed,#2563eb);
        box-shadow: 0 12px 30px rgba(79,70,229,.18); margin-bottom: 1.5rem;}
      .hero h1 {margin:0; font-size:2.2rem;} .hero p {margin:.45rem 0 0; opacity:.9;}
      .page-title {font-size:2rem; font-weight:800; letter-spacing:-.025em; margin-bottom:.2rem;}
      .page-subtitle {color:#64748b; margin-bottom:1.5rem;}
      .step-card {padding:1rem; border:1px solid rgba(128,128,128,.22); border-radius:14px;
        min-height:106px; background:rgba(128,128,128,.04);}
      .step-number {display:inline-grid; place-items:center; width:28px; height:28px;
        border-radius:50%; color:white; background:#4f46e5; font-weight:800; margin-right:.35rem;}
      .step-title {font-weight:750;} .step-card p {margin:.55rem 0 0; opacity:.7; font-size:.9rem;}
      .repo-card {padding:1rem 1.15rem; border:1px solid rgba(128,128,128,.2);
        border-radius:13px; margin:.6rem 0; background:rgba(128,128,128,.025);}
      .repo-card strong {font-size:1.03rem;} .repo-card small {color:#64748b;}
      .status-pass {color:#15803d; font-weight:750;} .status-fail {color:#b91c1c; font-weight:750;}
      .stButton>button, .stDownloadButton>button {border-radius:10px; min-height:42px; font-weight:650;}
      div[data-testid="stMetric"] {padding:.85rem 1rem; border:1px solid rgba(128,128,128,.18);
        border-radius:13px; background:rgba(128,128,128,.025);}
    </style>
    """,
    unsafe_allow_html=True,
)


def api_get(path, params=None, quiet=False):
    try:
        response = requests.get(f"{API_URL}{path}", params=params, timeout=10)
        data = response.json()
        if not response.ok:
            if not quiet:
                st.error(data.get("error", "Request failed"))
            return None
        return data
    except (requests.RequestException, ValueError) as error:
        if not quiet:
            st.error(f"Cannot reach the Flask API: {error}")
        return None


def api_post(path, payload, timeout):
    try:
        response = requests.post(f"{API_URL}{path}", json=payload, timeout=timeout)
        data = response.json()
        if not response.ok:
            st.error(data.get("error", "Request failed"))
            return None
        return data
    except requests.RequestException as error:
        st.error(f"Cannot reach the Flask API: {error}")
        return None
    except ValueError:
        st.error("The Flask API returned an invalid response.")
        return None


def repository_name(url):
    return url.rstrip("/").removesuffix(".git").split("/")[-1]


def display_date(value):
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%b %d, %Y · %I:%M %p")
    except ValueError:
        return value


def page_heading(title, subtitle):
    st.markdown(f'<div class="page-title">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-subtitle">{subtitle}</div>', unsafe_allow_html=True)


def run_to_csv(run):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Run ID", "Repository", "Commit", "Test", "Status", "Duration", "Output"])
    for result in run["results"]:
        writer.writerow(
            [
                run["run_id"],
                run["repository_url"],
                run["commit_sha"],
                result["node_id"],
                result["status"],
                result["duration_seconds"],
                result["output"],
            ]
        )
    return output.getvalue()


def show_run_details(run):
    st.subheader(f"Run #{run['run_id']} details")
    st.caption(f"{run['repository_url']} · commit {run['commit_sha'][:10]} · {display_date(run['created_at'])}")

    columns = st.columns(4)
    columns[0].metric("Tests", run["test_count"])
    columns[1].metric("Passed", run["passed_count"])
    columns[2].metric("Failed", run["failed_count"])
    duration = round(sum(result["duration_seconds"] for result in run["results"]), 3)
    columns[3].metric("Duration", f"{duration}s")

    if run.get("reused"):
        st.info("The identical commit and test selection already ran. Saved results were reused.", icon="♻️")
    elif run["failed_count"] == 0 and run["test_count"]:
        st.success("All selected tests passed.", icon="🎉")
    elif run["failed_count"]:
        st.warning(f"{run['failed_count']} test(s) did not pass.", icon="⚠️")

    for result in run["results"]:
        passed = result["status"] == "passed"
        icon = "✅" if passed else "❌"
        with st.expander(
            f"{icon} {result['node_id']} — {result['status'].upper()} — {result['duration_seconds']}s",
            expanded=not passed,
        ):
            st.code(result["output"] or "No test output", language="text")
            if st.button(
                "👁 View test code",
                key=f"run_{run['run_id']}_test_{result['test_case_id']}",
            ):
                test_case = api_get(f"/api/tests/{result['test_case_id']}")
                if test_case and test_case.get("content"):
                    st.code(test_case["content"], language="python")
                elif test_case:
                    st.warning("Code was not saved by the older scan. Scan the repository again.")

    st.download_button(
        "⬇️ Download CSV report",
        data=run_to_csv(run),
        file_name=f"test-run-{run['run_id']}.csv",
        mime="text/csv",
    )


def dashboard_page():
    st.markdown(
        """<div class="hero"><h1>Srija💕 Test Runner</h1>
        <p>Scan repositories, execute selected tests once, and review every saved result.</p></div>""",
        unsafe_allow_html=True,
    )
    data = api_get("/api/dashboard")
    if not data:
        return

    metrics = st.columns(4)
    metrics[0].metric("Repositories", data["project_count"])
    metrics[1].metric("Test runs", data["run_count"])
    metrics[2].metric("Passed tests", data["passed_count"])
    metrics[3].metric("Failed tests", data["failed_count"])

    st.write("")
    st.subheader("Recent executions")
    if not data["recent_runs"]:
        st.info("No test runs yet. Open **New Test Run** from the sidebar.")
    for run in data["recent_runs"]:
        name = repository_name(run["repository_url"])
        status = "Passed" if run["failed_count"] == 0 and run["test_count"] else "Needs attention"
        status_class = "status-pass" if status == "Passed" else "status-fail"
        st.markdown(
            f"""<div class="repo-card"><strong>#{run['run_id']} · {name}</strong><br>
            <small>{run['commit_sha'][:8]} · {display_date(run['created_at'])} · {run['test_count']} tests</small><br>
            <span class="{status_class}">{status}</span></div>""",
            unsafe_allow_html=True,
        )


def new_run_page():
    page_heading("New Test Run", "Scan a public Python repository and execute only the tests you choose.")

    steps = st.columns(3)
    details = [
        ("1", "Scan", "Discover pytest tests at the latest commit."),
        ("2", "Generate", "Create repository-grounded pytest tests with AI."),
        ("3", "Execute", "Run selected tests and save their output."),
    ]
    for column, (number, title, description) in zip(steps, details):
        with column:
            st.markdown(
                f'<div class="step-card"><span class="step-number">{number}</span>'
                f'<span class="step-title">{title}</span><p>{description}</p></div>',
                unsafe_allow_html=True,
            )

    if "scan" not in st.session_state:
        st.session_state.scan = None
    if "run" not in st.session_state:
        st.session_state.run = None
    scan = st.session_state.scan

    st.write("")
    repository_url = st.text_input(
        "Public GitHub repository URL",
        value=scan["repository_url"] if scan else "",
        placeholder="https://github.com/username/repository",
        disabled=bool(scan),
    )

    generator = api_get("/api/generator-status", quiet=True) or {}
    generator_ready = bool(generator.get("configured"))

    buttons = st.columns(3)
    scan_clicked = buttons[0].button(
        "🔎 Scan repository", type="primary" if not scan else "secondary",
        use_container_width=True, disabled=not repository_url or bool(scan),
    )
    generate_clicked = buttons[1].button(
        "✨ Generate AI tests", use_container_width=True,
        disabled=not scan or not generator_ready,
    )

    if not generator_ready:
        st.warning(
            "AI generation needs a replacement `OPENAI_API_KEY` in `.env.local`. "
            "Restart Flask after adding it.",
            icon="🔑",
        )
    elif scan:
        st.caption(f"AI generator ready · {generator.get('model', 'configured model')}")

    if scan_clicked:
        with st.status("Scanning repository...", expanded=True) as status:
            st.write("Reading the latest commit and discovering pytest functions")
            result = api_post("/api/scan", {"repository_url": repository_url}, 180)
            if result:
                st.session_state.scan = result
                st.session_state.run = None
                status.update(label="Scan completed", state="complete", expanded=False)
                st.rerun()
            status.update(label="Scan failed", state="error")

    if generate_clicked:
        result = api_post(
            "/api/generate",
            {"project_id": scan["project_id"], "commit_sha": scan["commit_sha"]},
            30,
        )
        if result:
            st.session_state.scan = result
            st.session_state.run = None
            message = "Saved AI tests reused" if result.get("generation_reused") else "AI tests generated"
            st.toast(message, icon="✨")
            st.rerun()

    scan = st.session_state.scan
    if not scan:
        st.info("Enter a repository URL and click Scan to begin.")
        return

    if buttons[2].button("Start over", use_container_width=True):
        st.session_state.scan = None
        st.session_state.run = None
        st.rerun()

    st.divider()
    metrics = st.columns(4)
    repo_tests = [test for test in scan["tests"] if test["source"] == "repository"]
    generated = [test for test in scan["tests"] if test["source"] == "generated"]
    metrics[0].metric("Project", repository_name(scan["repository_url"]))
    metrics[1].metric("Commit", scan["commit_sha"][:8])
    metrics[2].metric("Repository tests", len(repo_tests))
    metrics[3].metric("Generated tests", len(generated))

    st.subheader("Choose tests")
    filter_columns = st.columns([2, 1])
    search = filter_columns[0].text_input("Search tests", placeholder="login, dashboard, test_api...")
    source_filter = filter_columns[1].selectbox("Source", ["All", "Repository", "Generated"])

    visible_tests = scan["tests"]
    if search:
        visible_tests = [test for test in visible_tests if search.lower() in test["node_id"].lower()]
    if source_filter != "All":
        visible_tests = [test for test in visible_tests if test["source"] == source_filter.lower()]

    options = {test["id"]: f"{test['node_id']} · {test['source']}" for test in visible_tests}
    selected_ids = st.multiselect(
        "Tests to execute", options=list(options), default=list(options),
        format_func=lambda test_id: options[test_id], placeholder="Select tests",
    )
    st.caption(f"{len(selected_ids)} of {len(visible_tests)} visible tests selected")

    if options:
        inspect_columns = st.columns([3, 1])
        inspect_id = inspect_columns[0].selectbox(
            "Test case to inspect",
            options=list(options),
            format_func=lambda test_id: options[test_id],
            key="inspect_test_case",
        )
        if inspect_columns[1].button("👁 View code", use_container_width=True):
            test_case = api_get(f"/api/tests/{inspect_id}")
            if test_case and test_case.get("content"):
                st.code(test_case["content"], language="python")
            elif test_case:
                st.warning("Code was not saved by the older scan. Click Start over and scan again.")

    execute_clicked = st.button(
        "▶️ Execute selected tests", type="primary", use_container_width=True,
        disabled=not selected_ids,
    )
    if execute_clicked:
        with st.status("Executing selected tests...", expanded=True) as status:
            st.write(f"Running {len(selected_ids)} test(s) against commit {scan['commit_sha'][:8]}")
            run = api_post(
                "/api/execute",
                {"project_id": scan["project_id"], "commit_sha": scan["commit_sha"], "test_ids": selected_ids},
                600,
            )
            if run:
                st.session_state.run = run
                label = "Existing run reused" if run["reused"] else "Execution completed"
                status.update(label=label, state="complete", expanded=False)
            else:
                status.update(label="Execution failed", state="error")

    if st.session_state.run:
        st.divider()
        show_run_details(st.session_state.run)


def history_page():
    page_heading("Run History", "Review previous executions and download complete test reports.")
    data = api_get("/api/runs")
    if not data or not data["runs"]:
        st.info("No saved executions yet. Run tests first from **New Test Run**.")
        return

    runs = data["runs"]
    repositories = sorted({run["repository_url"] for run in runs})
    filters = st.columns([1.4, 1, 1])
    selected_repo = filters[0].selectbox("Repository", ["All repositories", *repositories], format_func=lambda value: repository_name(value) if value.startswith("http") else value)
    result_filter = filters[1].selectbox("Result", ["All results", "Passed", "Failed"])
    text_filter = filters[2].text_input("Commit or run ID")

    filtered = runs
    if selected_repo != "All repositories":
        filtered = [run for run in filtered if run["repository_url"] == selected_repo]
    if result_filter == "Passed":
        filtered = [run for run in filtered if run["failed_count"] == 0 and run["test_count"]]
    elif result_filter == "Failed":
        filtered = [run for run in filtered if run["failed_count"] > 0]
    if text_filter:
        value = text_filter.lower()
        filtered = [run for run in filtered if value in run["commit_sha"].lower() or value in str(run["run_id"])]

    rows = [
        {
            "Run": run["run_id"], "Repository": repository_name(run["repository_url"]),
            "Commit": run["commit_sha"][:8], "Tests": run["test_count"],
            "Passed": run["passed_count"], "Failed": run["failed_count"],
            "Status": run["status"].title(), "Created": display_date(run["created_at"]),
        }
        for run in filtered
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    if not filtered:
        st.warning("No runs match the selected filters.")
        return

    labels = {run["run_id"]: f"Run #{run['run_id']} · {repository_name(run['repository_url'])} · {run['commit_sha'][:8]}" for run in filtered}
    selected_id = st.selectbox("Open run details", list(labels), format_func=lambda run_id: labels[run_id])
    selected_run = next(run for run in filtered if run["run_id"] == selected_id)
    st.divider()
    show_run_details(selected_run)


def projects_page():
    page_heading("Projects", "Repositories that have been scanned by this test runner.")
    data = api_get("/api/projects")
    if not data or not data["projects"]:
        st.info("No projects yet. Scan a repository from **New Test Run**.")
        return

    search = st.text_input("Search repositories", placeholder="Repository name or GitHub URL")
    projects = data["projects"]
    if search:
        projects = [project for project in projects if search.lower() in project["repository_url"].lower()]

    for project in projects:
        last_run = project["last_run"]
        result = "No runs" if not last_run else ("Passed" if last_run["failed_count"] == 0 and last_run["test_count"] else "Needs attention")
        st.markdown(
            f"""<div class="repo-card"><strong>{repository_name(project['repository_url'])}</strong><br>
            <small>{project['repository_url']}</small><br><br>
            <small>Last commit: {(project['last_commit'] or 'Not scanned')[:10]} · Tests: {project['test_count']} · Runs: {project['run_count']} · Latest: {result}</small>
            </div>""",
            unsafe_allow_html=True,
        )


def database_page():
    page_heading("Database", "Read-only view of every table and saved row.")
    data = api_get("/api/database")
    if not data:
        return

    tables = data["tables"]
    summary_columns = st.columns(len(tables))
    for column, (table_name, table_data) in zip(summary_columns, tables.items()):
        column.metric(table_name, table_data["row_count"])

    st.info(
        "This page is read-only. Generated Python code is stored in `test_case.content`, "
        "and pytest output is stored in `test_result.output`.",
        icon="🗄️",
    )

    table_names = list(tables)
    table_tabs = st.tabs(table_names)
    for tab, table_name in zip(table_tabs, table_names):
        with tab:
            table_data = tables[table_name]
            rows = table_data["rows"]
            st.caption(
                f"{table_data['row_count']} row(s) · Columns: "
                f"{', '.join(table_data['columns'])}"
            )
            if not rows:
                st.info(f"The `{table_name}` table is empty.")
                continue

            st.dataframe(rows, use_container_width=True, hide_index=True)

            row_labels = {
                row["id"]: f"ID {row['id']}" for row in rows if "id" in row
            }
            selected_id = st.selectbox(
                "View complete record",
                options=list(row_labels),
                format_func=lambda row_id: row_labels[row_id],
                key=f"database_record_{table_name}",
            )
            selected_row = next(row for row in rows if row.get("id") == selected_id)

            long_fields = {
                key: value
                for key, value in selected_row.items()
                if key in {"content", "output"} and value
            }
            normal_fields = {
                key: value for key, value in selected_row.items() if key not in long_fields
            }
            st.json(normal_fields)
            for field_name, value in long_fields.items():
                st.markdown(f"**{field_name}**")
                language = "python" if field_name == "content" else "text"
                st.code(value, language=language)


with st.sidebar:
    st.title("Srija💕 Test Runner")
    st.caption("Repository testing dashboard")
    st.divider()
    page = st.radio(
        "Navigation",
        ["Dashboard", "New Test Run", "Run History", "Projects", "Database"],
        label_visibility="collapsed",
    )
    st.divider()
    if api_get("/health", quiet=True):
        st.success("Flask API connected", icon="✅")
    else:
        st.error("Flask API is offline", icon="🔌")
        st.code("python app.py", language="bash")
    st.caption("Database-backed · Idempotent · No queue")


pages = {
    "Dashboard": dashboard_page,
    "New Test Run": new_run_page,
    "Run History": history_page,
    "Projects": projects_page,
    "Database": database_page,
}
pages[page]()
