#!/usr/bin/env bash
# Install, migrate, seed the offline demo, and start Boardom (backend + frontend).
#
#   ./run_all.sh                 dev servers on 8000 / 3000, demo data seeded
#   ./run_all.sh --no-seed       skip the demo course
#   ./run_all.sh --prod          production frontend build (next build + start)
#   BACKEND_PORT=8001 FRONTEND_PORT=3001 ./run_all.sh
# Press Ctrl+C to stop both servers.
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
SEED=1
PROD=0
for arg in "$@"; do
  case "$arg" in
    --no-seed) SEED=0 ;;
    --prod) PROD=1 ;;
    *) echo "Unknown option: $arg"; exit 1 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")" && pwd)"
need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing '$1'. $2"; exit 1; }; }
step() { printf '\n==> %s\n' "$1"; }

need uv "Install it: https://docs.astral.sh/uv/getting-started/installation/"
need node "Install Node.js 22.13 or newer: https://nodejs.org/"
need npm "npm comes with Node.js: https://nodejs.org/"

# The browser origin must match the frontend port (CSRF check); the proxy must find the API.
export BOARDOM_FRONTEND_ORIGIN="http://localhost:${FRONTEND_PORT}"
export BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"

step "Backend: environment, dependencies, database"
cd "$ROOT/backend"
[ -f .env ] || { cp .env.example .env; echo "Created backend/.env from .env.example"; }
uv sync
uv run alembic upgrade head
if [ "$SEED" = 1 ]; then
  step "Seeding the offline demo course"
  uv run python -m app.seed_demo
fi

step "Frontend: environment and dependencies"
cd "$ROOT/frontend"
[ -f .env.local ] || { cp .env.example .env.local; echo "Created frontend/.env.local"; }
npm install --no-audit --no-fund
[ "$PROD" = 1 ] && npm run build

step "Starting the servers"
PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(cd "$ROOT/backend" && exec uv run uvicorn app.main:app --port "$BACKEND_PORT") &
PIDS+=($!)
if [ "$PROD" = 1 ]; then SCRIPT=start; else SCRIPT=dev; fi
(cd "$ROOT/frontend" && exec npm run "$SCRIPT" -- --port "$FRONTEND_PORT") &
PIDS+=($!)

ready=0
for _ in $(seq 1 60); do
  sleep 2
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1 &&
     curl -fsS -o /dev/null --max-time 30 "http://localhost:${FRONTEND_PORT}/login" 2>/dev/null; then
    ready=1; break
  fi
done
if [ "$ready" = 1 ]; then echo; echo "Boardom is running."; else echo; echo "The servers are still starting (or failed: see the output above)."; fi
echo "  App:      http://localhost:${FRONTEND_PORT}   (use localhost, not 127.0.0.1)"
echo "  API docs: http://127.0.0.1:${BACKEND_PORT}/docs"
echo "  Admin:    admin@example.com / BoardomAdmin#2026 (change it!)"
if [ "$SEED" = 1 ]; then
  echo "  Teacher:  demo.teacher@example.com / DemoTeacher#2026"
  echo "  Student:  asha@example.com / DemoStudent#2026"
fi
echo "Press Ctrl+C to stop."
wait
