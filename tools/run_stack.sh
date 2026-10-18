#!/usr/bin/env bash
# DevPilot local stack launcher — one command to run the whole pipeline.
#
#   tools/run_stack.sh            start db + ai-engine + backend (if not already up),
#                                 then the Streamlit UI in the foreground.
#                                 Ctrl-C closes the UI; services stay up.
#   tools/run_stack.sh --no-ui    start services only, no Streamlit.
#   tools/run_stack.sh --status   show what's running.
#   tools/run_stack.sh --stop     stop services started by this script.
#
# Overridable:  DB_URL (compose Postgres), ENGINE_VENV, UI_VENV, ports 8000/8001/8501.
# Notes: backend runs against the LOCAL compose DB here (its .env points at Neon);
#        uploads are filesystem-shared between backend and engine (both on host).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNDIR="/tmp/devpilot_stack"
DB_URL="${DB_URL:-postgresql+psycopg://devpilot:devpilot@localhost:5433/devpilot}"
ENGINE_VENV="${ENGINE_VENV:-$ROOT/ai-engine/.venv}"
UI_VENV="${UI_VENV:-$HOME/.venvs/devpilot-ui}"

mkdir -p "$RUNDIR"

port_up() { curl -sf -o /dev/null --max-time 2 "$1"; }
wait_for() { # url, name, max seconds
  for _ in $(seq "$3"); do port_up "$1" && { echo "  ✓ $2"; return 0; }; sleep 1; done
  echo "  ✗ $2 did not come up — see $RUNDIR/$4.log"; return 1
}

start_db() {
  if docker exec devpilot-barclaysmdm-db-1 pg_isready -U devpilot -q 2>/dev/null; then
    echo "  ✓ db (compose) already running"; return 0
  fi
  echo "  starting compose db..."; (cd "$ROOT" && docker compose up -d db >/dev/null)
  for _ in $(seq 60); do
    docker exec devpilot-barclaysmdm-db-1 pg_isready -U devpilot -q 2>/dev/null && { echo "  ✓ db"; return 0; }
    sleep 1
  done
  echo "  ✗ db failed to start"; exit 1
}

ensure_schema() {
  # Compare against alembic's head revision, not a table count: an existing DB with
  # 10+ tables still needs newly added revisions (e.g. 0004_chat_msgs) applied.
  if (cd "$ROOT/backend" && DATABASE_URL="$DB_URL" .venv/bin/alembic current 2>/dev/null | grep -q "(head)"); then
    echo "  ✓ schema current"
    return 0
  fi
  echo "  applying alembic migrations..."
  (cd "$ROOT/backend" && DATABASE_URL="$DB_URL" .venv/bin/alembic upgrade head >/dev/null)
  echo "  ✓ schema migrated"
}

start_engine() {
  if port_up http://localhost:8001/health; then echo "  ✓ ai-engine already up"; return 0; fi
  [ -x "$ENGINE_VENV/bin/uvicorn" ] || { echo "  ✗ engine venv missing at $ENGINE_VENV"; exit 1; }
  echo "  starting ai-engine :8001 (first cold start loads torch/docling — slow)..."
  (cd "$ROOT/ai-engine" && setsid "$ENGINE_VENV/bin/uvicorn" app.main:app --port 8001 \
      >"$RUNDIR/engine.log" 2>&1 < /dev/null & echo $! > "$RUNDIR/engine.pid")
  wait_for http://localhost:8001/health ai-engine 120 engine
}

start_backend() {
  if port_up http://localhost:8000/health; then echo "  ✓ backend already up"; return 0; fi
  echo "  starting backend :8000 (local compose DB)..."
  (cd "$ROOT/backend" && setsid env \
      DATABASE_URL="$DB_URL" AI_ENGINE_URL="http://localhost:8001" \
      AUTO_CREATE_TABLES=false UPLOAD_DIR="$ROOT/backend/var/uploads" \
      .venv/bin/uvicorn app.main:app --port 8000 \
      >"$RUNDIR/backend.log" 2>&1 < /dev/null & echo $! > "$RUNDIR/backend.pid")
  wait_for http://localhost:8000/health backend 60 backend
}

stop_all() {
  for name in engine backend; do
    if [ -f "$RUNDIR/$name.pid" ]; then
      kill "$(cat "$RUNDIR/$name.pid")" 2>/dev/null || true
      rm -f "$RUNDIR/$name.pid"; echo "  stopped $name"
    fi
  done
  # fallback: instances launched by this script's exact signature (no --reload)
  pkill -f "uvicorn app.main:app --port 8001" 2>/dev/null && echo "  stopped engine (orphan)" || true
  pkill -f "uvicorn app.main:app --port 8000" 2>/dev/null && echo "  stopped backend (orphan)" || true
  pkill -f "streamlit run tools/streamlit_app.py" 2>/dev/null && echo "  stopped ui" || true
}

status() {
  printf '  db        : %s\n' "$(docker exec devpilot-barclaysmdm-db-1 pg_isready -U devpilot -q 2>/dev/null && echo up || echo down)"
  printf '  ai-engine : %s\n' "$(port_up http://localhost:8001/health && echo up || echo down)"
  printf '  backend   : %s\n' "$(port_up http://localhost:8000/health && echo up || echo down)"
  printf '  ui        : %s\n' "$(port_up http://localhost:8501/ && echo up || echo down)"
}

case "${1:-}" in
  --stop)  stop_all; exit 0 ;;
  --status) status; exit 0 ;;
esac

echo "== DevPilot stack =="
echo "[1/4] database";     start_db
echo "[2/4] schema";       ensure_schema
echo "[3/4] ai-engine";    start_engine
echo "[4/4] backend";      start_backend

echo; echo "Services up. API docs: http://localhost:8000/docs   Engine: http://localhost:8001/docs"
echo "Pipeline UI: http://localhost:8501  (Ctrl-C closes UI only; '$0 --stop' stops services)"

if [ "${1:-}" != "--no-ui" ]; then
  [ -x "$UI_VENV/bin/streamlit" ] || { echo "  ✗ ui venv missing at $UI_VENV — create it: python3.11 -m venv $UI_VENV && $UI_VENV/bin/pip install -r tools/requirements.txt"; exit 1; }
  cd "$ROOT" && export DB_URL DEVPILOT_BACKEND_URL="http://localhost:8000"
  exec "$UI_VENV/bin/streamlit" run tools/streamlit_app.py --server.headless true
fi
