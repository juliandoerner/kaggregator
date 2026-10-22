#!/bin/bash
# KA Events - Development Startup Script
# Sets up venv, installs the package, and starts both services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"

echo "=== KA Events - Development Setup ==="

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

pip install --upgrade pip --quiet

# One editable install covers both services - they are one package now.
echo "Installing ka_events (editable, with dev extras)..."
pip install -e "$PROJECT_DIR[dev]" --quiet

mkdir -p "$PROJECT_DIR/data"

echo ""
echo "=== Setup complete ==="
echo ""

export DATABASE_PATH="$PROJECT_DIR/data/events.db"
export FLASK_ENV=development
export FLASK_DEBUG=1

# Load alert settings if present
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
    # Always use the project-local database for development
    export DATABASE_PATH="$PROJECT_DIR/data/events.db"
fi

echo "[Scraper Service] Starting..."
ka-events-scraper &
SCRAPER_PID=$!

sleep 2

echo "[Web Service] Starting on http://localhost:5000..."
python -m flask --app ka_events.web.app run --host 0.0.0.0 --port 5000 &
WEB_PID=$!

echo ""
echo "=== Services started ==="
echo "  Web Service:     http://localhost:5000"
echo "  API:             http://localhost:5000/api/events"
echo "  Scraper Service: Running in background (PID: $SCRAPER_PID)"
echo ""
echo "Press Ctrl+C to stop all services"
echo ""

cleanup() {
    echo ""
    echo "Shutting down..."
    kill $SCRAPER_PID 2>/dev/null || true
    kill $WEB_PID 2>/dev/null || true
    deactivate 2>/dev/null || true
    echo "Done."
}

trap cleanup EXIT

wait
