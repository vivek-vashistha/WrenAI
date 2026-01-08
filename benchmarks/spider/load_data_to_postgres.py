#!/usr/bin/env python3
"""
Load SQLite databases from Spider dataset into PostgreSQL with proper schema handling.

This script loads each SQLite database into a separate PostgreSQL schema,
ensuring tables are created in the correct schema namespace.
"""

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def get_pg_connection(
    host: str, port: int, user: str, password: str, database: str
) -> psycopg2.extensions.connection:
    """Create a PostgreSQL connection."""
    return psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    )


def get_sqlite_connection(sqlite_file: str) -> sqlite3.Connection:
    """Create a SQLite connection."""
    return sqlite3.connect(sqlite_file)


def get_sqlite_tables(conn: sqlite3.Connection) -> List[str]:
    """Get list of table names from SQLite database."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return [row[0] for row in cursor.fetchall()]


def get_sqlite_table_schema(conn: sqlite3.Connection, table_name: str) -> List[Dict[str, Any]]:
    """Get table schema information from SQLite."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = []
    for row in cursor.fetchall():
        columns.append({
            "cid": row[0],
            "name": row[1],
            "type": row[2],
            "notnull": row[3],
            "dflt_value": row[4],
            "pk": row[5],
        })
    return columns


def get_sqlite_foreign_keys(conn: sqlite3.Connection, table_name: str) -> List[Dict[str, Any]]:
    """Get foreign key relationships from SQLite table."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA foreign_key_list({table_name})")
    foreign_keys = []
    for row in cursor.fetchall():
        foreign_keys.append({
            "id": row[0],  # Sequential number
            "seq": row[1],  # Column sequence number
            "table": row[2],  # Referenced table name
            "from": row[3],  # Column name in current table
            "to": row[4],  # Column name in referenced table
            "on_update": row[5],  # ON UPDATE action
            "on_delete": row[6],  # ON DELETE action
            "match": row[7],  # MATCH clause
        })
    return foreign_keys


def sqlite_to_postgres_type(sqlite_type: str) -> str:
    """Convert SQLite type to PostgreSQL type."""
    sqlite_type = sqlite_type.upper()
    
    # Handle common SQLite types
    if "INT" in sqlite_type:
        return "BIGINT"
    elif "REAL" in sqlite_type or "FLOAT" in sqlite_type or "DOUBLE" in sqlite_type:
        return "DOUBLE PRECISION"
    elif "TEXT" in sqlite_type or "CHAR" in sqlite_type or "CLOB" in sqlite_type:
        return "TEXT"
    elif "BLOB" in sqlite_type:
        return "BYTEA"
    elif "NUMERIC" in sqlite_type or "DECIMAL" in sqlite_type:
        return "NUMERIC"
    elif "BOOLEAN" in sqlite_type:
        return "BOOLEAN"
    elif "DATE" in sqlite_type:
        return "DATE"
    elif "TIME" in sqlite_type:
        return "TIME"
    elif "TIMESTAMP" in sqlite_type or "DATETIME" in sqlite_type:
        return "TIMESTAMP"
    else:
        # Default to TEXT for unknown types
        return "TEXT"


def create_postgres_table(
    pg_conn: psycopg2.extensions.connection,
    schema_name: str,
    table_name: str,
    columns: List[Dict[str, Any]],
) -> None:
    """Create a table in PostgreSQL with the specified schema."""
    cursor = pg_conn.cursor()
    
    try:
        # Build column definitions
        column_defs = []
        primary_keys = []
        
        for col in columns:
            col_name = col["name"]
            pg_type = sqlite_to_postgres_type(col["type"])
            
            # Handle nullable constraint
            # In SQLite, pk columns can be NULL, but in PostgreSQL we typically make them NOT NULL
            if col["pk"]:
                nullable = "NOT NULL"
            elif col["notnull"]:
                nullable = "NOT NULL"
            else:
                nullable = ""
            
            # Handle default values
            default = ""
            if col["dflt_value"] is not None:
                default_val = col["dflt_value"]
                # SQLite stores NULL as the string "NULL" in some cases
                if isinstance(default_val, str):
                    # Remove any extra quotes that SQLite might have added
                    default_val = default_val.strip("'\"")
                    
                    # Check if it's actually NULL
                    if default_val.upper() == "NULL" or default_val == "":
                        # Don't add DEFAULT for NULL
                        default = ""
                    elif default_val.upper() in ("CURRENT_TIMESTAMP", "CURRENT_TIME", "CURRENT_DATE"):
                        # Handle SQLite datetime functions
                        default = f"DEFAULT {default_val.upper()}"
                    else:
                        # Check if it's a numeric value (for numeric columns)
                        try:
                            # Try to parse as number
                            if "." in default_val:
                                float(default_val)
                            else:
                                int(default_val)
                            # It's numeric, use without quotes
                            default = f"DEFAULT {default_val}"
                        except ValueError:
                            # It's a string, escape and quote it
                            escaped_val = default_val.replace("'", "''")
                            default = f"DEFAULT '{escaped_val}'"
                else:
                    # Numeric or other non-string defaults
                    default = f"DEFAULT {default_val}"
            
            # Build column definition
            parts = [f'"{col_name}"', pg_type]
            if nullable:
                parts.append(nullable)
            if default:
                parts.append(default)
            
            column_def = " ".join(parts)
            column_defs.append(column_def)
            
            if col["pk"]:
                primary_keys.append(f'"{col_name}"')
        
        # Add primary key constraint if exists
        if primary_keys:
            column_defs.append(f"PRIMARY KEY ({', '.join(primary_keys)})")
        
        # Create table with explicit schema qualification
        create_table_sql = sql.SQL(
            'CREATE TABLE {schema}.{table} ({columns})'
        ).format(
            schema=sql.Identifier(schema_name),
            table=sql.Identifier(table_name),
            columns=sql.SQL(', '.join(column_defs)),
        )
        
        cursor.execute(create_table_sql)
        pg_conn.commit()
    except Exception as e:
        pg_conn.rollback()
        raise
    finally:
        cursor.close()


def copy_table_data(
    sqlite_conn: sqlite3.Connection,
    pg_conn: psycopg2.extensions.connection,
    schema_name: str,
    table_name: str,
    columns: List[Dict[str, Any]],
) -> int:
    """Copy data from SQLite table to PostgreSQL table."""
    sqlite_cursor = sqlite_conn.cursor()
    pg_cursor = pg_conn.cursor()
    
    try:
        # Get column names
        col_names = [col["name"] for col in columns]
        col_names_quoted = [f'"{name}"' for name in col_names]
        
        # Read data from SQLite
        sqlite_cursor.execute(f'SELECT {", ".join(col_names_quoted)} FROM "{table_name}"')
        rows = sqlite_cursor.fetchall()
        
        if not rows:
            return 0
        
        # Prepare insert statement with explicit schema
        # Use string formatting for the SQL since executemany needs a string with %s placeholders
        col_names_quoted_pg = [f'"{col}"' for col in col_names]
        placeholders = ", ".join(["%s"] * len(col_names))
        insert_sql_str = f'INSERT INTO "{schema_name}"."{table_name}" ({", ".join(col_names_quoted_pg)}) VALUES ({placeholders})'
        
        # Insert data in batches for better performance
        batch_size = 1000
        row_count = 0
        
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            pg_cursor.executemany(insert_sql_str, batch)
            row_count += len(batch)
        
        pg_conn.commit()
        return row_count
        
    except Exception as e:
        pg_conn.rollback()
        raise
    finally:
        sqlite_cursor.close()
        pg_cursor.close()


def parse_foreign_keys_from_sql(schema_sql: str) -> List[Dict[str, Any]]:
    """Parse foreign key relationships from SQL schema.
    
    Returns a list of foreign key definitions with:
    - table: source table name
    - columns: list of column names in source table
    - ref_table: referenced table name
    - ref_columns: list of column names in referenced table
    """
    foreign_keys = []
    
    # Pattern to match foreign key definitions
    # Matches: foreign key("col1", "col2") references "table"("ref_col1", "ref_col2")
    fk_pattern = re.compile(
        r'foreign\s+key\s*\(([^)]+)\)\s+references\s+["`]?(\w+)["`]?\s*\(([^)]+)\)',
        re.IGNORECASE
    )
    
    # Split by CREATE TABLE statements
    table_blocks = re.split(r'CREATE\s+TABLE\s+["`]?(\w+)["`]?', schema_sql, flags=re.IGNORECASE)
    
    current_table = None
    for i, block in enumerate(table_blocks):
        if i % 2 == 1:  # Table name
            current_table = block.strip().strip('"`')
        elif current_table and block:
            # Find all foreign keys in this table definition
            for match in fk_pattern.finditer(block):
                columns_str = match.group(1)
                ref_table = match.group(2).strip().strip('"`')
                ref_columns_str = match.group(3)
                
                # Parse column lists (handle single and multiple columns)
                columns = [col.strip().strip('"`') for col in re.split(r'["`]?\s*,\s*["`]?', columns_str)]
                ref_columns = [col.strip().strip('"`') for col in re.split(r'["`]?\s*,\s*["`]?', ref_columns_str)]
                
                foreign_keys.append({
                    'table': current_table,
                    'columns': columns,
                    'ref_table': ref_table,
                    'ref_columns': ref_columns,
                })
    
    return foreign_keys


def get_column_type(
    pg_conn: psycopg2.extensions.connection,
    schema_name: str,
    table_name: str,
    column_name: str,
) -> Optional[str]:
    """Get the data type of a column in PostgreSQL."""
    cursor = pg_conn.cursor()
    try:
        cursor.execute(
            """
            SELECT data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
            """,
            (schema_name, table_name, column_name),
        )
        result = cursor.fetchone()
        if result:
            # Return the actual type name (udt_name is more specific)
            return result[1]  # udt_name (e.g., 'int4', 'text', 'varchar')
        return None
    except Exception:
        # If there's an error, rollback to clear the transaction state
        try:
            pg_conn.rollback()
        except:
            pass
        return None
    finally:
        cursor.close()


def get_primary_key_columns(
    pg_conn: psycopg2.extensions.connection,
    schema_name: str,
    table_name: str,
) -> List[str]:
    """Get primary key column names for a table."""
    cursor = pg_conn.cursor()
    try:
        cursor.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass
            AND i.indisprimary
            ORDER BY a.attnum
            """,
            (f"{schema_name}.{table_name}",),
        )
        return [row[0] for row in cursor.fetchall()]
    except Exception:
        # Fallback method
        try:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = %s
                AND tc.table_name = %s
                ORDER BY kcu.ordinal_position
                """,
                (schema_name, table_name),
            )
            return [row[0] for row in cursor.fetchall()]
        except Exception:
            # If both methods fail, rollback and return empty list
            try:
                pg_conn.rollback()
            except:
                pass
            return []
    finally:
        cursor.close()


def has_unique_constraint(
    pg_conn: psycopg2.extensions.connection,
    schema_name: str,
    table_name: str,
    column_names: List[str],
) -> bool:
    """Check if a unique constraint exists on the given columns."""
    cursor = pg_conn.cursor()
    try:
        # First check if it's a primary key
        pk_columns = get_primary_key_columns(pg_conn, schema_name, table_name)
        if pk_columns == column_names:
            return True
        
        # Check for unique constraints
        cursor.execute(
            """
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'UNIQUE'
            AND tc.table_schema = %s
            AND tc.table_name = %s
            GROUP BY tc.constraint_name
            HAVING array_agg(kcu.column_name ORDER BY kcu.ordinal_position) = %s
            """,
            (schema_name, table_name, column_names),
        )
        return cursor.fetchone() is not None
    except Exception as e:
        # Fallback: check if it's a primary key
        try:
            pk_columns = get_primary_key_columns(pg_conn, schema_name, table_name)
            return pk_columns == column_names
        except:
            return False
    finally:
        cursor.close()


def fix_foreign_key_issues(
    pg_conn: psycopg2.extensions.connection,
    schema_name: str,
    foreign_keys: List[Dict[str, Any]],
) -> List[str]:
    """Fix foreign key issues by:
    1. Fixing type mismatches (alter column types)
    2. Adding missing unique constraints
    3. Validating column references
    
    Returns list of actions taken.
    """
    actions = []
    
    # Process each foreign key separately to avoid transaction issues
    # Each FK is processed in its own transaction to avoid cascading failures
    for idx, fk in enumerate(foreign_keys):
        table = fk['table']
        columns = fk['columns']
        ref_table = fk['ref_table']
        ref_columns = fk['ref_columns']
        
        # Start a fresh transaction for this FK
        try:
            # Ensure we're in a clean state
            pg_conn.rollback()
        except:
            pass
        
        cursor = pg_conn.cursor()
        try:
            # Check if referenced table exists
            cursor.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = %s AND table_name = %s
                """,
                (schema_name, ref_table),
            )
            if cursor.fetchone()[0] == 0:
                actions.append(f"⚠️  Skipped FK {table}({','.join(columns)}) -> {ref_table}: referenced table doesn't exist")
                pg_conn.rollback()
                continue
            
            # Check if all columns exist using the same cursor
            all_exist = True
            for col in columns:
                cursor.execute(
                    """
                    SELECT udt_name FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s AND column_name = %s
                    """,
                    (schema_name, table, col),
                )
                if cursor.fetchone() is None:
                    actions.append(f"⚠️  Skipped FK {table}({col}): column doesn't exist")
                    all_exist = False
            
            # Fix referenced columns if they don't exist
            fixed_ref_columns = []
            for i, ref_col in enumerate(ref_columns):
                cursor.execute(
                    """
                    SELECT udt_name FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s AND column_name = %s
                    """,
                    (schema_name, ref_table, ref_col),
                )
                if cursor.fetchone() is None:
                    # Try to find the primary key column instead
                    pk_columns = get_primary_key_columns(pg_conn, schema_name, ref_table)
                    if pk_columns and len(pk_columns) == len(ref_columns):
                        # Use primary key columns
                        fixed_ref_columns.append(pk_columns[i])
                        actions.append(
                            f"✓ Fixed column reference: {ref_table}.{ref_col} -> {ref_table}.{pk_columns[i]} (using primary key)"
                        )
                    else:
                        actions.append(f"⚠️  Skipped FK {table} -> {ref_table}({ref_col}): referenced column doesn't exist")
                        all_exist = False
                        break
                else:
                    fixed_ref_columns.append(ref_col)
            
            if not all_exist:
                pg_conn.rollback()
                continue
            
            # Update ref_columns if we fixed any
            if fixed_ref_columns != ref_columns:
                fk['ref_columns'] = fixed_ref_columns
                ref_columns = fixed_ref_columns
            
            # Fix type mismatches
            for i, (col, ref_col) in enumerate(zip(columns, ref_columns)):
                # Get column types using the same cursor
                cursor.execute(
                    """
                    SELECT udt_name FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s AND column_name = %s
                    """,
                    (schema_name, table, col),
                )
                col_result = cursor.fetchone()
                col_type = col_result[0] if col_result else None
                
                cursor.execute(
                    """
                    SELECT udt_name FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s AND column_name = %s
                    """,
                    (schema_name, ref_table, ref_col),
                )
                ref_result = cursor.fetchone()
                ref_col_type = ref_result[0] if ref_result else None
                
                if col_type and ref_col_type and col_type != ref_col_type:
                    # Determine which type to use (prefer the referenced table's type)
                    # Map PostgreSQL types to standard types for comparison
                    type_map = {
                        'int4': 'integer', 'integer': 'integer',
                        'int8': 'bigint', 'bigint': 'bigint',
                        'text': 'text', 'varchar': 'text',
                        'numeric': 'numeric', 'decimal': 'numeric',
                    }
                    
                    col_base = type_map.get(col_type, col_type)
                    ref_base = type_map.get(ref_col_type, ref_col_type)
                    
                    if col_base != ref_base:
                        # Change the referencing column to match the referenced column type
                        # Get the actual PostgreSQL type name
                        cursor.execute(
                            """
                            SELECT udt_name, character_maximum_length, data_type
                            FROM information_schema.columns
                            WHERE table_schema = %s AND table_name = %s AND column_name = %s
                            """,
                            (schema_name, ref_table, ref_col),
                        )
                        ref_type_info = cursor.fetchone()
                        if ref_type_info:
                            ref_udt = ref_type_info[0]
                            ref_max_len = ref_type_info[1]
                            ref_data_type = ref_type_info[2]
                            
                            # Map to PostgreSQL type
                            pg_type = ref_udt
                            if ref_udt == 'varchar' and ref_max_len:
                                pg_type = f"VARCHAR({ref_max_len})"
                            elif ref_udt == 'varchar':
                                pg_type = "TEXT"
                            elif ref_udt in ('int4', 'int2', 'int8'):
                                pg_type = ref_data_type.upper()  # INTEGER, SMALLINT, BIGINT
                            
                            try:
                                # Build USING clause for type conversion
                                using_clause = ""
                                if col_type in ('text', 'varchar') and ref_udt in ('int4', 'int2', 'int8'):
                                    # Convert text to integer
                                    using_clause = f' USING "{col}"::integer'
                                elif col_type in ('int4', 'int2', 'int8') and ref_udt in ('text', 'varchar'):
                                    # Convert integer to text
                                    using_clause = f' USING "{col}"::text'
                                elif col_type != ref_udt:
                                    # Try direct cast
                                    using_clause = f' USING "{col}"::{pg_type}'
                                
                                alter_sql_str = (
                                    f'ALTER TABLE "{schema_name}"."{table}" '
                                    f'ALTER COLUMN "{col}" TYPE {pg_type}{using_clause}'
                                )
                                cursor.execute(alter_sql_str)
                                pg_conn.commit()
                                actions.append(
                                    f"✓ Fixed type mismatch: {table}.{col} changed from {col_type} to {pg_type} "
                                    f"to match {ref_table}.{ref_col}"
                                )
                            except Exception as e:
                                pg_conn.rollback()
                                actions.append(
                                    f"⚠️  Could not fix type mismatch for {table}.{col}: {e}"
                                )
            
            # Check and add unique constraint if missing
            # First check if it's a primary key
            pk_columns = get_primary_key_columns(pg_conn, schema_name, ref_table)
            if pk_columns != ref_columns:
                # Check if unique constraint already exists using the same cursor
                constraint_name = f"{ref_table}_{'_'.join(ref_columns)}_unique"
                if len(constraint_name) > 63:
                    constraint_name = f"{ref_table[:30]}_{'_'.join(ref_columns)[:30]}_unique"
                
                # Check if constraint already exists
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.table_constraints
                    WHERE constraint_schema = %s
                    AND table_name = %s
                    AND constraint_name = %s
                    AND constraint_type = 'UNIQUE'
                    """,
                    (schema_name, ref_table, constraint_name),
                )
                constraint_exists = cursor.fetchone()[0] > 0
                
                # Also check if there's a unique constraint on these columns (by checking indexes)
                if not constraint_exists:
                    # Cast attname to text to match the text[] parameter
                    cursor.execute(
                        """
                        SELECT COUNT(*) FROM pg_index i
                        JOIN pg_class c ON c.oid = i.indexrelid
                        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                        WHERE i.indrelid = %s::regclass
                        AND i.indisunique
                        AND array_length(i.indkey, 1) = %s
                        GROUP BY i.indexrelid
                        HAVING array_agg(a.attname::text ORDER BY a.attnum) = %s::text[]
                        """,
                        (f"{schema_name}.{ref_table}", len(ref_columns), ref_columns),
                    )
                    constraint_exists = cursor.fetchone() is not None
                
                if not constraint_exists:
                    # Double-check using the helper function as fallback
                    if not has_unique_constraint(pg_conn, schema_name, ref_table, ref_columns):
                        try:
                            columns_sql = ", ".join([f'"{col}"' for col in ref_columns])
                            alter_sql = f'ALTER TABLE "{schema_name}"."{ref_table}" ADD CONSTRAINT "{constraint_name}" UNIQUE ({columns_sql})'
                            cursor.execute(alter_sql)
                            pg_conn.commit()
                            actions.append(
                                f"✓ Added unique constraint on {ref_table}({','.join(ref_columns)})"
                            )
                        except Exception as e:
                            pg_conn.rollback()
                            error_msg = str(e)
                            # Only log if it's not a "already exists" error (which is expected)
                            if "already exists" not in error_msg.lower():
                                actions.append(
                                    f"⚠️  Could not add unique constraint on {ref_table}({','.join(ref_columns)}): {e}"
                                )
                            # Otherwise, silently skip - constraint already exists
        except Exception as e:
            # If there's an error processing this FK, rollback and log it
            try:
                pg_conn.rollback()
            except:
                # If rollback fails, try to reset the connection
                try:
                    pg_conn.reset()
                except:
                    pass
            actions.append(
                f"⚠️  Error processing FK {table}: {e}"
            )
        finally:
            cursor.close()
    
    return actions


def remove_foreign_keys_from_sql(schema_sql: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Remove foreign key definitions from SQL and return modified SQL + foreign keys.
    
    Returns:
        Tuple of (modified_sql_without_fks, list_of_foreign_key_definitions)
    """
    # Parse foreign keys first
    foreign_keys = parse_foreign_keys_from_sql(schema_sql)
    
    # Remove foreign key definitions from SQL
    # Pattern to match and remove: ,\s*foreign key(...) references ...
    fk_pattern = re.compile(
        r',\s*foreign\s+key\s*\([^)]+\)\s+references\s+["`]?\w+["`]?\s*\([^)]+\)',
        re.IGNORECASE
    )
    modified_sql = fk_pattern.sub('', schema_sql)
    
    # Also handle foreign keys at the end (without leading comma)
    fk_pattern_no_comma = re.compile(
        r'\s+foreign\s+key\s*\([^)]+\)\s+references\s+["`]?\w+["`]?\s*\([^)]+\)',
        re.IGNORECASE
    )
    modified_sql = fk_pattern_no_comma.sub('', modified_sql)
    
    return modified_sql, foreign_keys


def constraint_exists(
    pg_conn: psycopg2.extensions.connection,
    schema_name: str,
    table_name: str,
    constraint_name: str,
) -> bool:
    """Check if a constraint already exists."""
    cursor = pg_conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COUNT(*) FROM information_schema.table_constraints
            WHERE constraint_schema = %s
            AND table_name = %s
            AND constraint_name = %s
            """,
            (schema_name, table_name, constraint_name),
        )
        return cursor.fetchone()[0] > 0
    finally:
        cursor.close()


def add_foreign_key_constraint(
    pg_conn: psycopg2.extensions.connection,
    schema_name: str,
    fk_def: Dict[str, Any],
    constraint_suffix: str = "",
) -> bool:
    """Add a foreign key constraint to the database.
    
    Args:
        constraint_suffix: Optional suffix to make constraint name unique
    """
    cursor = pg_conn.cursor()
    try:
        table = fk_def['table']
        columns = fk_def['columns']
        ref_table = fk_def['ref_table']
        ref_columns = fk_def['ref_columns']
        
        # Build constraint name - include column names to make it unique
        # This handles cases where a table has multiple FKs to the same table
        col_suffix = "_".join(columns[:2])  # Use first 2 columns for uniqueness
        if constraint_suffix:
            constraint_name = f"{table}_{ref_table}_{constraint_suffix}_fk"
        else:
            constraint_name = f"{table}_{ref_table}_{col_suffix}_fk"
        
        if len(constraint_name) > 63:
            # Truncate while keeping it unique
            max_len = 63 - len(constraint_suffix) - 3 if constraint_suffix else 60
            constraint_name = f"{table[:max_len//2]}_{ref_table[:max_len//2]}_{col_suffix[:10]}_fk"
        
        # Check if constraint already exists
        if constraint_exists(pg_conn, schema_name, table, constraint_name):
            return True  # Already exists, skip
        
        # Build SQL
        columns_sql = ", ".join([f'"{col}"' for col in columns])
        ref_columns_sql = ", ".join([f'"{col}"' for col in ref_columns])
        
        alter_sql = (
            f'ALTER TABLE "{schema_name}"."{table}" '
            f'ADD CONSTRAINT "{constraint_name}" '
            f'FOREIGN KEY ({columns_sql}) '
            f'REFERENCES "{schema_name}"."{ref_table}" ({ref_columns_sql})'
        )
        
        cursor.execute(alter_sql)
        pg_conn.commit()
        return True
    except Exception as e:
        pg_conn.rollback()
        raise e
    finally:
        cursor.close()


def load_schema_from_file(
    pg_conn: psycopg2.extensions.connection,
    schema_name: str,
    schema_file: Path,
) -> bool:
    """Load schema from a PostgreSQL schema file.
    
    This function:
    1. Parses foreign keys from the SQL
    2. Creates tables without foreign keys
    3. Fixes type mismatches and adds missing unique constraints
    4. Adds foreign key constraints
    
    Returns True if successful, False otherwise.
    """
    try:
        with open(schema_file, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        
        # Parse and remove foreign keys from SQL
        schema_sql_no_fks, foreign_keys = remove_foreign_keys_from_sql(schema_sql)
        
        # Create schema if not exists
        old_isolation = pg_conn.isolation_level
        try:
            pg_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cursor = pg_conn.cursor()
            cursor.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(schema_name)
                )
            )
            cursor.close()
        finally:
            pg_conn.set_isolation_level(old_isolation)
        
        # Set search path and execute schema SQL (without foreign keys)
        cursor = pg_conn.cursor()
        try:
            cursor.execute(
                sql.SQL("SET search_path TO {}").format(
                    sql.Identifier(schema_name)
                )
            )
            
            # Execute the schema SQL without foreign keys
            cursor.execute(schema_sql_no_fks)
            pg_conn.commit()
        except Exception as e:
            pg_conn.rollback()
            raise e
        finally:
            cursor.close()
        
        # Fix foreign key issues (type mismatches, missing unique constraints)
        # Use a fresh transaction for FK fixes - ensure connection is in good state
        if foreign_keys:
            # Ensure we're in a clean transaction state
            try:
                pg_conn.rollback()
            except:
                pass
            
            print(f"  Fixing foreign key issues...")
            actions = fix_foreign_key_issues(pg_conn, schema_name, foreign_keys)
            for action in actions:
                if action.startswith("✓"):
                    print(f"    {action}")
                elif action.startswith("⚠️"):
                    print(f"    {action}")
            
            # Add foreign key constraints
            print(f"  Adding foreign key constraints...")
            # Track constraint names to ensure uniqueness
            constraint_names_used = {}
            for idx, fk_def in enumerate(foreign_keys):
                try:
                    # Generate unique suffix based on columns to handle multiple FKs from same table
                    col_suffix = "_".join(fk_def['columns'])
                    constraint_key = f"{fk_def['table']}_{fk_def['ref_table']}_{col_suffix}"
                    
                    # If we've seen this combination before, add index
                    if constraint_key in constraint_names_used:
                        constraint_names_used[constraint_key] += 1
                        suffix = str(constraint_names_used[constraint_key])
                    else:
                        constraint_names_used[constraint_key] = 0
                        suffix = ""
                    
                    add_foreign_key_constraint(pg_conn, schema_name, fk_def, suffix)
                except Exception as e:
                    # Check if it's a duplicate constraint error
                    error_msg = str(e)
                    if "already exists" in error_msg.lower():
                        print(f"    ⚠️  Warning: Foreign key constraint already exists for {fk_def['table']}({','.join(fk_def['columns'])}) -> {fk_def['ref_table']}({','.join(fk_def['ref_columns'])})")
                    else:
                        print(f"    ⚠️  Warning: Could not add foreign key {fk_def['table']}({','.join(fk_def['columns'])}) -> {fk_def['ref_table']}({','.join(fk_def['ref_columns'])}): {e}")
        
        return True
    except Exception as e:
        try:
            pg_conn.rollback()
        except:
            pass
        raise e


def load_database(
    sqlite_file: str,
    schema_name: str,
    pg_conn: psycopg2.extensions.connection,
    skip_if_exists: bool = True,
    schema_postgres_file: Optional[Path] = None,
) -> bool:
    """Load a single SQLite database into PostgreSQL schema.
    
    Args:
        sqlite_file: Path to SQLite database file
        schema_name: PostgreSQL schema name
        pg_conn: PostgreSQL connection
        skip_if_exists: Skip if schema already has tables
        schema_postgres_file: Optional path to schema_postgres.sql file
    """
    # Check if schema already has tables
    if skip_if_exists:
        cursor = pg_conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = %s
            """,
            (schema_name,),
        )
        table_count = cursor.fetchone()[0]
        cursor.close()
        
        if table_count > 0:
            print(f"⏭️  Skipping {schema_name} (already loaded, {table_count} tables)")
            return False
    
    # Step 1: Try to load schema from schema_postgres.sql if provided
    use_schema_file = False
    if schema_postgres_file and schema_postgres_file.exists():
        print(f"  Using schema_postgres.sql")
        print(f"  Creating schema from schema_postgres.sql...")
        try:
            if not load_schema_from_file(pg_conn, schema_name, schema_postgres_file):
                print(f"❌ Error: Failed to create schema from schema_postgres.sql")
                return False
            print(f"✅ Schema created successfully from schema_postgres.sql")
            use_schema_file = True
        except Exception as e:
            print(f"❌ Error creating schema from schema_postgres.sql: {e}")
            print(f"⚠️  Skipping data load for {schema_name} due to schema creation failure")
            return False
    
    # Connect to SQLite (needed for data loading)
    sqlite_conn = get_sqlite_connection(sqlite_file)
    
    try:
        # Get list of tables
        tables = get_sqlite_tables(sqlite_conn)
        
        if not tables:
            print(f"⚠️  No tables found in {sqlite_file}")
            return False
        
        print(f"🚀 Loading {schema_name} ({len(tables)} tables)")
        
        total_rows = 0
        
        # If schema was loaded from file, skip table creation and foreign key setup
        if not use_schema_file:
            # Create schema if not exists (only if not using schema file)
            cursor = pg_conn.cursor()
            # CREATE SCHEMA cannot run inside a transaction block, so use autocommit
            old_isolation = pg_conn.isolation_level
            try:
                pg_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
                cursor.execute(
                    sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                        sql.Identifier(schema_name)
                    )
                )
            finally:
                pg_conn.set_isolation_level(old_isolation)
                cursor.close()
            
            # First pass: Create all tables (without foreign keys)
            table_foreign_keys = {}  # Store foreign keys to add later
            
            for table_name in tables:
                try:
                    # Get table schema
                    columns = get_sqlite_table_schema(sqlite_conn, table_name)
                    
                    # Get foreign keys
                    foreign_keys = get_sqlite_foreign_keys(sqlite_conn, table_name)
                    if foreign_keys:
                        table_foreign_keys[table_name] = foreign_keys
                    
                    # Create table in PostgreSQL (without foreign keys for now)
                    create_postgres_table(pg_conn, schema_name, table_name, columns)
                    
                except Exception as e:
                    # Rollback any failed transaction
                    try:
                        pg_conn.rollback()
                    except:
                        pass
                    print(f"  ✗ Error creating table {table_name}: {e}")
                    # Continue with next table
                    continue
            
            # Second pass: Add foreign key constraints (after all tables exist)
            for table_name, foreign_keys in table_foreign_keys.items():
                try:
                    # Group foreign keys by constraint (same id = same constraint)
                    fk_groups = {}
                    for fk in foreign_keys:
                        fk_id = fk["id"]
                        if fk_id not in fk_groups:
                            fk_groups[fk_id] = []
                        fk_groups[fk_id].append(fk)
                    
                    # Add each foreign key constraint
                    for fk_id, fk_group in fk_groups.items():
                        # Get the first FK to get table info
                        first_fk = fk_group[0]
                        ref_table = first_fk["table"]
                        
                        # Build column lists for composite foreign keys
                        from_cols = [fk["from"] for fk in sorted(fk_group, key=lambda x: x["seq"])]
                        to_cols = [fk["to"] for fk in sorted(fk_group, key=lambda x: x["seq"])]
                        
                        # Build constraint name
                        constraint_name = f"{table_name}_{ref_table}_fk_{fk_id}"
                        if len(constraint_name) > 63:  # PostgreSQL limit
                            constraint_name = f"{table_name[:30]}_{ref_table[:30]}_fk"
                        
                        # Build ON DELETE/UPDATE clauses
                        on_delete = f"ON DELETE {first_fk['on_delete']}" if first_fk['on_delete'] != 'NO ACTION' else ""
                        on_update = f"ON UPDATE {first_fk['on_update']}" if first_fk['on_update'] != 'NO ACTION' else ""
                        action_clauses = " ".join(filter(None, [on_delete, on_update]))
                        
                        # Create foreign key constraint
                        from_cols_quoted = ", ".join([f'"{col}"' for col in from_cols])
                        to_cols_quoted = ", ".join([f'"{col}"' for col in to_cols])
                        
                        fk_sql = f'ALTER TABLE "{schema_name}"."{table_name}" ADD CONSTRAINT "{constraint_name}" FOREIGN KEY ({from_cols_quoted}) REFERENCES "{schema_name}"."{ref_table}" ({to_cols_quoted})'
                        if action_clauses:
                            fk_sql += f" {action_clauses}"
                        
                        cursor = pg_conn.cursor()
                        cursor.execute(fk_sql)
                        pg_conn.commit()
                        cursor.close()
                        
                except Exception as e:
                    # Rollback any failed transaction
                    try:
                        pg_conn.rollback()
                    except:
                        pass
                    print(f"  ⚠️  Warning: Could not add foreign key to {table_name}: {e}")
                    # Continue - foreign keys are not critical for data loading
        
        # Third pass: Copy data (after all tables and constraints exist)
        # This runs regardless of whether schema was loaded from file or SQLite
        for table_name in tables:
            try:
                # Get table schema
                columns = get_sqlite_table_schema(sqlite_conn, table_name)
                
                # Copy data
                row_count = copy_table_data(
                    sqlite_conn, pg_conn, schema_name, table_name, columns
                )
                total_rows += row_count
                print(f"  ✓ {table_name}: {row_count} rows")
                
            except Exception as e:
                # Rollback any failed transaction
                try:
                    pg_conn.rollback()
                except:
                    pass
                print(f"  ✗ Error loading data into {table_name}: {e}")
                # Continue with next table
                continue
        
        print(f"✅ Finished {schema_name} ({len(tables)} tables, {total_rows} total rows)")
        return True
        
    finally:
        sqlite_conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Load SQLite databases from Spider dataset into PostgreSQL"
    )
    parser.add_argument(
        "--host", default="localhost", help="PostgreSQL host (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=9432, help="PostgreSQL port (default: 9432)"
    )
    parser.add_argument(
        "--user", default="test", help="PostgreSQL user (default: test)"
    )
    parser.add_argument(
        "--password", default="secret", help="PostgreSQL password (default: secret)"
    )
    parser.add_argument(
        "--database",
        default="test",
        help="PostgreSQL database name (default: test)",
    )
    parser.add_argument(
        "--spider-root",
        default="database",
        help="Path to Spider database directory (default: database)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reload even if schema already has tables",
    )
    
    args = parser.parse_args()
    
    # Validate spider root directory
    spider_root = Path(args.spider_root)
    if not spider_root.exists() or not spider_root.is_dir():
        print(f"❌ Error: {spider_root} is not a valid directory")
        sys.exit(1)
    
    # Connect to PostgreSQL
    try:
        pg_conn = get_pg_connection(
            args.host, args.port, args.user, args.password, args.database
        )
        # Use autocommit for schema creation, but we'll manage transactions for data loading
    except Exception as e:
        print(f"❌ Error connecting to PostgreSQL: {e}")
        sys.exit(1)
    
    # Process each database directory
    db_dirs = sorted([d for d in spider_root.iterdir() if d.is_dir()])
    
    if not db_dirs:
        print(f"⚠️  No database directories found in {spider_root}")
        sys.exit(0)
    
    print(f"🔍 Found {len(db_dirs)} database directories")
    print("=" * 60)
    
    success_count = 0
    skip_count = 0
    error_count = 0
    
    for db_dir in db_dirs:
        db_name = db_dir.name
        sqlite_file = db_dir / f"{db_name}.sqlite"
        schema_postgres_file = db_dir / "schema_postgres.sql"
        
        if not sqlite_file.exists():
            print(f"⚠️  Skipping {db_name} (no .sqlite file found)")
            continue
        
        # Check for schema_postgres.sql, prefer it over reading from SQLite
        schema_file_to_use = None
        if schema_postgres_file.exists():
            schema_file_to_use = schema_postgres_file
        else:
            schema_file_to_use = None  # Will fall back to reading from SQLite
        
        try:
            result = load_database(
                str(sqlite_file),
                db_name,
                pg_conn,
                skip_if_exists=not args.force,
                schema_postgres_file=schema_file_to_use,
            )
            
            if result:
                success_count += 1
            else:
                skip_count += 1
                
        except Exception as e:
            print(f"❌ Error processing {db_name}: {e}")
            error_count += 1
        
        print("-" * 60)
    
    pg_conn.close()
    
    # Summary
    print("\n" + "=" * 60)
    print("🎉 Spider load complete")
    print(f"   ✅ Success: {success_count}")
    print(f"   ⏭️  Skipped: {skip_count}")
    print(f"   ❌ Errors: {error_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
