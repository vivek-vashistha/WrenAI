#!/usr/bin/env bash
# Script using pgloader with PostgreSQL schema files for proper schema creation
# This reads schema_postgres.sql (or schema.sql) from each database folder,
# creates the schema, then loads data using pgloader
# If schema creation fails, the script will not proceed with data loading

set -e

PG_HOST="${PG_HOST:-localhost}"
PG_PORT="${PG_PORT:-9432}"
PG_USER="${PG_USER:-test}"
PG_PASSWORD="${PG_PASSWORD:-secret}"
PG_DB="${PG_DB:-test}"
SPIDER_ROOT="${SPIDER_ROOT:-database}"

export PGPASSWORD="$PG_PASSWORD"

# Check if pgloader is installed
if ! command -v pgloader &> /dev/null; then
  echo "❌ Error: pgloader is required but not found"
  echo "   Install it with: brew install pgloader (macOS) or apt-get install pgloader (Linux)"
  exit 1
fi

# Function to convert SQLite schema to PostgreSQL
convert_sqlite_to_postgres() {
  local schema_file="$1"
  local temp_file=$(mktemp)
  local sed_script=$(mktemp)
  
  # Create sed script using here-document to avoid quoting issues
  cat > "$sed_script" <<'SEDSCRIPT'
# Remove PRAGMA statements
/^PRAGMA/d

# Remove INSERT statements (data is loaded separately)
/^INSERT INTO/d

# Convert backticks to double quotes (handle multiple occurrences per line)
s/`([^`]+)`/"\1"/g

# Convert int(11) or int(N) to integer (PostgreSQL doesn't use display width)
s/\bint\([0-9][0-9]*\)/integer/g
# Convert plain int to integer (PostgreSQL prefers integer)
# Match int as a whole word, including after quotes
s/([^a-zA-Z])int([^a-zA-Z0-9])/\1integer\2/g
s/^int([^a-zA-Z0-9])/integer\1/g

# Ensure foreign key references use double quotes instead of backticks
s/foreign key\(`([^`]+)`\)/foreign key("\1")/g
s/references `([^`]+)`\(`([^`]+)`\)/references "\1"("\2")/g
s/references `([^`]+)`/references "\1"/g
SEDSCRIPT
  
  # Apply sed script
  sed -E -f "$sed_script" "$schema_file" > "$temp_file"
  rm -f "$sed_script"
  
  echo "$temp_file"
}

# Process each database directory
for db_dir in "$SPIDER_ROOT"/*; do
  [ -d "$db_dir" ] || continue

  db_name=$(basename "$db_dir")
  sqlite_file="$db_dir/$db_name.sqlite"
  schema_postgres_file="$db_dir/schema_postgres.sql"
  schema_file="$db_dir/schema.sql"

  [ -f "$sqlite_file" ] || continue
  
  # Prefer schema_postgres.sql, fall back to schema.sql
  if [ -f "$schema_postgres_file" ]; then
    schema_to_use="$schema_postgres_file"
    echo "  Using schema_postgres.sql"
  elif [ -f "$schema_file" ]; then
    schema_to_use="$schema_file"
    echo "  Using schema.sql (will convert to PostgreSQL)"
  else
    echo "⚠️  Warning: Neither schema_postgres.sql nor schema.sql found for $db_name, skipping"
    continue
  fi

  echo "🔍 Processing $db_name"

  # Ensure schema exists
  psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" \
    -c "CREATE SCHEMA IF NOT EXISTS \"$db_name\";" >/dev/null

  # Skip if already loaded
  table_count=$(psql \
    -h "$PG_HOST" \
    -p "$PG_PORT" \
    -U "$PG_USER" \
    -d "$PG_DB" \
    -tAc "
      SELECT COUNT(*)
      FROM information_schema.tables
      WHERE table_schema = '$db_name';
    ")

  if [ "$table_count" -gt 0 ]; then
    echo "⏭️  Skipping $db_name (already loaded, $table_count tables)"
    continue
  fi

  echo "🚀 Loading $db_name"

  # Step 1: Prepare and create schema
  echo "  Creating schema..."
  
  # Convert schema if needed (only for schema.sql, not schema_postgres.sql)
  if [ "$schema_to_use" = "$schema_file" ]; then
    converted_schema=$(convert_sqlite_to_postgres "$schema_file")
    schema_to_execute="$converted_schema"
  else
    schema_to_execute="$schema_to_use"
  fi
  
  # Create schema - if this fails, do NOT proceed with data loading
  if ! psql \
    -h "$PG_HOST" \
    -p "$PG_PORT" \
    -U "$PG_USER" \
    -d "$PG_DB" \
    -c "SET search_path TO \"$db_name\";" \
    -f "$schema_to_execute" \
    >/tmp/schema_${db_name}.log 2>&1; then
    echo "❌ Error creating schema for $db_name"
    echo "Error details:"
    cat /tmp/schema_${db_name}.log
    # Only remove converted temporary file, not original schema_postgres.sql
    if [ "$schema_to_use" = "$schema_file" ]; then
      rm -f "$schema_to_execute"
    fi
    rm -f /tmp/schema_${db_name}.log
    echo "⚠️  Skipping data load for $db_name due to schema creation failure"
    continue
  fi
  
  # Clean up converted schema file if it was created
  if [ "$schema_to_use" = "$schema_file" ]; then
    rm -f "$schema_to_execute"
  fi
  rm -f /tmp/schema_${db_name}.log
  
  echo "✅ Schema created successfully for $db_name"

  # Step 2: Load data from SQLite using pgloader
  echo "  Loading data from SQLite..."
  loader_file=$(mktemp)
  sqlite_path=$(realpath "$sqlite_file")
  
  cat > "$loader_file" <<EOF
LOAD DATABASE
  FROM sqlite://$sqlite_path
  INTO postgresql://$PG_USER:$PG_PASSWORD@$PG_HOST:$PG_PORT/$PG_DB

WITH
  quote identifiers,
  data only,
  create indexes,
  reset sequences,
  foreign keys

BEFORE LOAD DO
  \$\$ SET search_path TO "$db_name"; \$\$

CAST
  type int to integer,
  type bigint when (= precision 19) to bigint,
  type smallint to smallint,
  type real to real,
  type double to "double precision",
  type float to "double precision",
  type text to text,
  type varchar to varchar,
  type char to char,
  type blob to bytea;
EOF

  # Run pgloader to load data into target schema
  if ! pgloader "$loader_file" 2>&1 | tee /tmp/pgloader_${db_name}.log; then
    echo "❌ Error loading data for $db_name with pgloader"
    echo "Error details (last 20 lines):"
    tail -20 /tmp/pgloader_${db_name}.log | grep -E "(ERROR|FATAL|KABOOM)" || tail -20 /tmp/pgloader_${db_name}.log
    rm -f "$loader_file" /tmp/pgloader_${db_name}.log
    continue
  fi
  rm -f /tmp/pgloader_${db_name}.log "$loader_file"

  # Step 5: Copy data from public schema to target schema and clean up
  echo "  Copying data to target schema..."
  copy_result=$(psql \
    -h "$PG_HOST" \
    -p "$PG_PORT" \
    -U "$PG_USER" \
    -d "$PG_DB" \
    -tAc "
      DO \$\$
      DECLARE
        r RECORD;
        row_count INTEGER;
      BEGIN
        FOR r IN 
          SELECT tablename 
          FROM pg_tables 
          WHERE schemaname = 'public' 
          AND tablename NOT LIKE 'pg_%'
          AND tablename NOT LIKE 'sqlite_%'
        LOOP
          -- Copy data from public to target schema
          EXECUTE format('INSERT INTO %I.%I SELECT * FROM public.%I', '$db_name', r.tablename, r.tablename);
          GET DIAGNOSTICS row_count = ROW_COUNT;
          -- Drop table from public schema
          EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename);
        END LOOP;
      END \$\$;
      SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = '$db_name';
    " 2>&1)
  
  if echo "$copy_result" | grep -q "ERROR"; then
    echo "❌ Error copying data for $db_name"
    echo "$copy_result"
    continue
  fi

  # Verify tables were created
  table_count=$(psql \
    -h "$PG_HOST" \
    -p "$PG_PORT" \
    -U "$PG_USER" \
    -d "$PG_DB" \
    -tAc "
      SELECT COUNT(*)
      FROM information_schema.tables
      WHERE table_schema = '$db_name';
    ")

  if [ -z "$table_count" ] || [ "$table_count" = "0" ]; then
    echo "⚠️  Warning: No tables found for $db_name"
  else
    echo "✅ Finished $db_name ($table_count tables loaded)"
  fi

  echo "--------------------------------"
done

echo "🎉 Spider load complete"
