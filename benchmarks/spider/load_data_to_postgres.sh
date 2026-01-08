#!/usr/bin/env bash
# Wrapper script that calls the Python loader
# This ensures proper schema handling in PostgreSQL

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/load_data_to_postgres.py"

# Default values (can be overridden by environment variables or command line)
PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-9432}"
PG_USER="${PG_USER:-test}"
PG_PASSWORD="${PG_PASSWORD:-secret}"
PG_DB="${PG_DB:-test}"
SPIDER_ROOT="${SPIDER_ROOT:-database}"

# Check if Python script exists
if [ ! -f "$PYTHON_SCRIPT" ]; then
  echo "❌ Error: Python script not found at $PYTHON_SCRIPT"
  exit 1
fi

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
  echo "❌ Error: python3 is required but not found"
  exit 1
fi

# Check if required Python packages are available
if ! python3 -c "import psycopg2" 2>/dev/null; then
  echo "❌ Error: psycopg2 is required. Install it with: pip install psycopg2-binary"
  exit 1
fi

# Run the Python script with all arguments passed through
exec python3 "$PYTHON_SCRIPT" \
  --host "$PG_HOST" \
  --port "$PG_PORT" \
  --user "$PG_USER" \
  --password "$PG_PASSWORD" \
  --database "$PG_DB" \
  --spider-root "$SPIDER_ROOT" \
  "$@"
