"""
Run any PDF through the full DevPilot pipeline: backend upload (202) -> engine ingest
job (Docling parse + embeddings) -> poll until terminal -> optional SOP generation.

The backend and ai-engine must be running (see the steps in the repo README/GUIDE),
plus `docker compose up -d db`. Uploads are filesystem-shared: run the services on
this machine, or use compose so both containers mount the same uploads volume.

Usage (any venv with httpx — backend/.venv or ai-engine/.venv):
    python ai-engine/scripts/pdf_pipeline.py /path/to/your.pdf
    python ai-engine/scripts/pdf_pipeline.py /path/to/your.pdf --question "Summarize the fraud rules"
    python ai-engine/scripts/pdf_pipeline.py /path/to/your.pdf --artifact-type test_case --no-generate

A throwaway user/project is created per run so nothing collides with your data.
"""
import argparse
import sys
import time
import uuid

import httpx

DEFAULT_BACKEND = "http://localhost:8000/api/v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    parser.add_argument("--question", default="Create user stories covering the main requirements in this document.",
                        help="Requirement text for the generate step")
    parser.add_argument("--artifact-type", default="user_story",
                        choices=["user_story", "acceptance_criteria", "test_case", "api_spec", "architecture", "sprint_plan"])
    parser.add_argument("--no-generate", action="store_true", help="Stop after ingestion")
    parser.add_argument("--max-wait", type=float, default=300.0, help="Seconds to wait for the ingest job")
    args = parser.parse_args()

    client = httpx.Client(timeout=httpx.Timeout(30.0, read=180.0))
    B = args.backend.rstrip("/")

    # 1) throwaway identity + project
    email = f"pdf-demo-{uuid.uuid4().hex[:8]}@example.com"
    password = "Str0ng-pass-123"
    r = client.post(f"{B}/auth/register", json={"email": email, "full_name": "PDF Demo", "password": password})
    if r.status_code not in (201, 409):
        sys.exit(f"register failed: {r.status_code} {r.text}")
    token = client.post(f"{B}/auth/login", json={"email": email, "password": password}).json()["access_token"]
    H = {"Authorization": f"Bearer {token}"}
    pid = client.post(f"{B}/projects", json={"name": f"PDF {time.strftime('%H:%M:%S')}"}, headers=H).json()["id"]
    print(f"[1/4] project ready: {pid}")

    # 2) upload -> 202 job
    with open(args.pdf, "rb") as fh:
        data = fh.read()
    r = client.post(f"{B}/projects/{pid}/requirements", headers=H,
                    files={"file": (args.pdf.rsplit("/", 1)[-1], data, "application/pdf")})
    if r.status_code != 202:
        sys.exit(f"upload rejected: {r.status_code} {r.text}")
    body = r.json()
    job_id, req_id = body["ingest_job_id"], body["id"]
    print(f"[2/4] uploaded {len(data)/1e6:.1f} MB -> 202, ingest_job_id={job_id}")

    # 3) poll until the engine job is terminal (first PDF of a fresh engine process
    #    pays Docling model init; later runs are ~10-20 s for tens of pages)
    deadline = time.time() + args.max_wait
    while True:
        state = client.get(f"{B}/ingest-jobs/{job_id}", headers=H).json()
        if state["status"] != "processing":
            break
        if time.time() > deadline:
            sys.exit(f"job still processing after {args.max_wait:.0f}s — check the engine log")
        time.sleep(3)
    print(f"[3/4] ingest {state['status']}: chunks_indexed={state['chunks_indexed']}"
          + (f" error={state['error_message']}" if state.get("error_message") else ""))
    if state["status"] != "done":
        sys.exit(1)
    print("      tree nodes are persisted in doc_tree_nodes; chunks in pgvector with node_id metadata")

    # 4) generation through the SOP graph against the freshly indexed document
    if args.no_generate:
        return
    r = client.post(f"{B}/projects/{pid}/generate", headers=H, json={
        "artifact_type": args.artifact_type, "requirement_text": args.question, "requirement_id": req_id})
    if r.status_code != 201:
        sys.exit(f"generate failed: {r.status_code} {r.text[:400]}")
    art = r.json()
    hist = client.get(f"{B}/projects/{pid}/history", headers=H).json()[0]
    print(f"[4/4] artifact {art['id']} (v{art['version']}): "
          f"eval_score={hist['eval_score']} retry_count={hist['retry_count']} model={hist['model_used']}")
    items = art["content"].get(args.artifact_type + "s") or art["content"].get("stories") or art["content"]
    print(f"      content preview: {str(items)[:300]}")


if __name__ == "__main__":
    main()
