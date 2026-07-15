import os

import requests
import streamlit as st


API_URL = os.getenv("API_URL", "http://127.0.0.1:5000")

st.set_page_config(page_title="GitHub Test Runner", page_icon="🧪", layout="wide")
st.title("GitHub Test Runner")
st.caption("Scan a public Python repository, choose tests, and execute them once.")

if "scan" not in st.session_state:
    st.session_state.scan = None

repository_url = st.text_input(
    "GitHub repository URL", placeholder="https://github.com/username/repository"
)


def post(path, payload, timeout):
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


scan_column, generate_column, execute_column = st.columns(3)

with scan_column:
    if st.button("1. Scan", use_container_width=True, disabled=not repository_url):
        with st.spinner("Scanning repository..."):
            result = post("/api/scan", {"repository_url": repository_url}, timeout=180)
        if result:
            st.session_state.scan = result
            st.success("Repository scanned")

scan = st.session_state.scan

with generate_column:
    if st.button("2. Generate", use_container_width=True, disabled=not scan):
        with st.spinner("Generating demo test..."):
            result = post(
                "/api/generate",
                {"project_id": scan["project_id"], "commit_sha": scan["commit_sha"]},
                timeout=30,
            )
        if result:
            st.session_state.scan = result
            scan = result
            st.success("Demo test generated")

if scan:
    st.write(f"Commit: `{scan['commit_sha'][:12]}`")
    if scan.get("cached"):
        st.info("This commit was already scanned. Saved data was reused.")

    test_options = {test["id"]: f"{test['node_id']} ({test['source']})" for test in scan["tests"]}
    selected_ids = st.multiselect(
        "Tests to execute",
        options=list(test_options),
        default=list(test_options),
        format_func=lambda test_id: test_options[test_id],
    )

    with execute_column:
        if st.button("3. Execute", use_container_width=True, disabled=not selected_ids):
            with st.spinner("Executing selected tests..."):
                run = post(
                    "/api/execute",
                    {
                        "project_id": scan["project_id"],
                        "commit_sha": scan["commit_sha"],
                        "test_ids": selected_ids,
                    },
                    timeout=600,
                )
            if run:
                if run["reused"]:
                    st.info("Identical tests were already requested. Existing result reused.")
                st.subheader(f"Run #{run['run_id']} — {run['status']}")
                for result in run["results"]:
                    icon = "✅" if result["status"] == "passed" else "❌"
                    with st.expander(
                        f"{icon} Test {result['test_case_id']}: {result['status']} "
                        f"({result['duration_seconds']}s)"
                    ):
                        st.code(result["output"] or "No output")
elif repository_url:
    st.info("Click Scan to discover tests in this repository.")

