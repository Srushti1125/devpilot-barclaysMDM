"""
Minimal Streamlit UI for the DevPilot pipeline — a dev tool, NOT a product frontend.

Zero-config by design: connection details come from the same env the stack launcher
exports (DB_URL, backend port 8000), and a fixed dev identity is auto-logged-in.
Override anything from the sidebar "Advanced" panel if your setup differs.

Prereqs: tools/run_stack.sh (starts db + ai-engine + backend, then this UI).

Run standalone (services already up):
    /home/devanssh/.venvs/devpilot-ui/bin/streamlit run tools/streamlit_app.py
"""
import os
import time

import pandas as pd
import requests
import streamlit as st

DEFAULT_BACKEND = os.environ.get("DEVPILOT_BACKEND_URL", "http://localhost:8000")
DEFAULT_DB = os.environ.get("DB_URL", "postgresql+psycopg://devpilot:devpilot@localhost:5433/devpilot")
DEV_EMAIL = os.environ.get("DEVPILOT_UI_EMAIL", "ui@example.com")
DEV_PASSWORD = os.environ.get("DEVPILOT_UI_PASSWORD", "Str0ng-pass-123")
ARTIFACT_TYPES = ["user_story", "acceptance_criteria", "test_case",
                  "api_spec", "architecture", "sprint_plan"]

st.set_page_config(page_title="DevPilot pipeline", layout="wide")

backend = st.session_state.get("backend", DEFAULT_BACKEND)
db_url = st.session_state.get("db_url", DEFAULT_DB)
email = st.session_state.get("email", DEV_EMAIL)
password = st.session_state.get("password", DEV_PASSWORD)


@st.cache_resource(show_spinner=False)
def db_engine(url: str):
    from sqlalchemy import create_engine
    return create_engine(url)


def fetch_tree(doc_id: str, url: str) -> pd.DataFrame:
    # sqlalchemy.text() is required: pandas would otherwise hand the raw string to the
    # psycopg driver, which cannot interpret ":d" named binds (syntax error at ":").
    from sqlalchemy import text
    return pd.read_sql(
        text("SELECT ordinal, level, title, page_start, page_end, low_structure, "
             "       length(text) AS text_len, text "
             "FROM doc_tree_nodes WHERE doc_id = :d ORDER BY ordinal"),
        db_engine(url), params={"d": doc_id})


def api(method: str, path: str, **kw):
    return requests.request(method, f"{backend}/api/v1{path}", timeout=kw.pop("timeout", 60), **kw)


def try_login(mail: str, pwd: str):
    try:
        r = api("post", "/auth/login", json={"email": mail, "password": pwd})
        if r.status_code == 200:
            return r.json()["access_token"], ""
        api("post", "/auth/register", json={"email": mail, "full_name": "UI Dev User", "password": pwd})
        r = api("post", "/auth/login", json={"email": mail, "password": pwd})
        return (r.json()["access_token"], "") if r.status_code == 200 else ("", r.text[:200])
    except requests.RequestException as e:
        return "", f"cannot reach backend at {backend} ({type(e).__name__}) — start it: tools/run_stack.sh"


# ── auto-login with the dev identity (no clicking) ────────────────────────────
login_error = ""
if "token" not in st.session_state:
    tok, err = try_login(email, password)
    if tok:
        st.session_state["token"] = tok
    else:
        login_error = err

# ── sidebar: status + advanced overrides ──────────────────────────────────────
with st.sidebar:
    st.subheader("DevPilot pipeline")
    if "token" in st.session_state:
        st.success(f"Signed in as {email}")
    else:
        st.error(f"Not signed in: {login_error}")
    with st.expander("Advanced (defaults come from run_stack env)"):
        new_backend = st.text_input("Backend URL", backend)
        new_db = st.text_input("Database URL (tree view)", db_url)
        new_email = st.text_input("Email", email)
        new_password = st.text_input("Password", password, type="password")
        if st.button("Apply & re-login") or (new_backend, new_db, new_email, new_password) != (backend, db_url, email, password):
            st.session_state.update(backend=new_backend.rstrip("/"), db_url=new_db,
                                    email=new_email, password=new_password)
            st.session_state.pop("token", None)
            st.rerun()

if "token" not in st.session_state:
    st.stop()
H = {"Authorization": f"Bearer {st.session_state['token']}"}

# ── project ────────────────────────────────────────────────────────────────────
projects = api("get", "/projects", headers=H).json()
if not projects:
    projects = [api("post", "/projects", json={"name": "UI Project"}, headers=H).json()]
pids = {p["name"] + f" ({p['id'][:8]})": p["id"] for p in projects}
pid = pids[st.selectbox("Project", list(pids))]

# ── upload + ingest job ────────────────────────────────────────────────────────
st.subheader("1 · Upload & index")
up = st.file_uploader("Requirements document (pdf/docx/md/txt/csv/html, ≤10 MB)",
                      type=["pdf", "docx", "doc", "txt", "md", "csv", "html"])
if up and st.button("Upload & run ingest job", type="primary"):
    r = api("post", f"/projects/{pid}/requirements", headers=H, timeout=120,
            files={"file": (up.name, up.getvalue(), up.type or "application/octet-stream")})
    if r.status_code != 202:
        st.error(f"upload rejected ({r.status_code}): {r.text[:300]}")
    else:
        job_id = r.json()["ingest_job_id"]
        st.session_state["doc_id"] = r.json()["id"]
        with st.status(f"202 accepted — job {job_id}", expanded=True) as s:
            st.write("Engine runs Docling parse + Gemini embeddings in the background. "
                     "First document after an engine restart pays model loading (~1 min); "
                     "later runs: ~10–30 s.")
            state = {}
            for _ in range(150):  # up to 5 min
                time.sleep(2)
                state = api("get", f"/ingest-jobs/{job_id}", headers=H).json()
                if state["status"] != "processing":
                    break
            s.write(f"final: {state}")
            s.update(label=f"Ingest {state.get('status', 'timeout')}",
                     state="complete" if state.get("status") == "done" else "error")

# ── requirements + document tree (read straight from the shared Postgres) ──────
reqs = api("get", f"/projects/{pid}/requirements", headers=H).json()
req_labels = {f"{r['filename']} ({r['id'][:8]})": r["id"] for r in reqs}

st.subheader("2 · Document tree (doc_tree_nodes)")
if not reqs:
    st.info("No requirements yet — upload a document above.")
else:
    default_idx = list(req_labels).index(
        next((l for l, i in req_labels.items() if i == st.session_state.get("doc_id")), next(iter(req_labels))))
    sel = st.selectbox("Requirement", list(req_labels), index=default_idx)
    try:
        tree = fetch_tree(req_labels[sel], db_url)
        if tree.empty:
            st.warning("No tree rows for this requirement (indexed before tree persistence?).")
        else:
            view = tree.copy()
            view["section"] = view["level"].map(lambda l: "  " * (l - 1)) + view["title"]
            st.dataframe(view[["section", "ordinal", "page_start", "page_end",
                               "low_structure", "text_len"]], hide_index=True, height=260)
            pick = st.selectbox("Inspect a section", view["ordinal"],
                                format_func=lambda o: view.loc[view.ordinal == o, "section"].iloc[0])
            st.markdown(f"**pages** {int(view.loc[view.ordinal == pick, 'page_start'].iloc[0] or 0)}–"
                        f"{int(view.loc[view.ordinal == pick, 'page_end'].iloc[0] or 0)}")
            st.text(view.loc[view.ordinal == pick, "text"].iloc[0][:3000] or "(structural node — text lives in children)")
    except Exception as e:
        st.error(f"tree query failed (is the DB URL right?): {e}")

# ── generation ─────────────────────────────────────────────────────────────────
st.subheader("3 · Generate (SOP graph)")
rid = st.selectbox("Link generation to requirement (traceability)", ["— none —"] + list(req_labels))
a_type = st.selectbox("Artifact type", ARTIFACT_TYPES)
question = st.text_area("Requirement text",
                        "Create user stories covering the main functional requirements in this document.",
                        height=90)
if st.button("Generate", type="primary"):
    payload = {"artifact_type": a_type, "requirement_text": question}
    if rid != "— none —":
        payload["requirement_id"] = req_labels[rid]
    with st.spinner("retrieve → pm → qa loop (up to ~2 min incl. judge + retries)..."):
        r = api("post", f"/projects/{pid}/generate", headers=H, json=payload, timeout=300)
    if r.status_code != 201:
        st.error(f"generate failed ({r.status_code}): {r.text[:400]}")
    else:
        art = r.json()
        st.success(f"artifact {art['id'][:8]} v{art['version']}")
        st.json(art["content"])

hist = api("get", f"/projects/{pid}/history", headers=H).json()
if hist:
    st.subheader("Generation history")
    st.dataframe(pd.json_normalize(hist)[["artifact_type", "prompt_version", "eval_score",
                                          "retry_count", "model_used", "latency_ms",
                                          "requirement_id", "created_at"]].head(10),
                 hide_index=True)
