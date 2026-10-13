#!/usr/bin/env python3
"""
migrate_sqlite_to_postgres.py — Database Migration Tool (SQLite -> PostgreSQL)

This script:
  1. Inspects the existing campus.db SQLite schema (read-only).
  2. Creates equivalent PostgreSQL tables (faculty, programs, cutoffs, locations, placements).
  3. Migrates all records from SQLite to PostgreSQL preserving IDs and handling NULLs.
  4. Prevents duplicate insertions on re-run (idempotent upsert).
  5. Uses transactions with automatic rollback on error.
  6. Verifies row counts and compares sample records.
  7. Leaves campus.db and campus_backup.db completely untouched.

Usage:
  # Inspect SQLite schema only (read-only):
  python3 migrate_sqlite_to_postgres.py --inspect

  # Create PostgreSQL tables (schema only):
  python3 migrate_sqlite_to_postgres.py --create-tables

  # Migrate data from SQLite to PostgreSQL (Day 2):
  python3 migrate_sqlite_to_postgres.py --migrate

  # Verify row counts and compare sample records:
  python3 migrate_sqlite_to_postgres.py --verify

Environment variables (loaded from .env if present):
  DB_HOST     (default: localhost)
  DB_PORT     (default: 5432)
  DB_NAME     (default: campus_chat)
  DB_USER     (default: campus_user)
  DB_PASSWORD (required)
"""

import argparse
import os
import sqlite3
import sys

# ---------------------------------------------------------------------------
# Load .env file if python-dotenv is available
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Import psycopg2
# ---------------------------------------------------------------------------
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SQLITE_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "campus.db")

EXPECTED_TABLES = ["faculty", "programs", "cutoffs", "locations", "placements"]

# ---------------------------------------------------------------------------
# PostgreSQL table DDL — derived from SQLite schema in campus.db
# ---------------------------------------------------------------------------
PG_CREATE_STATEMENTS = {
    "faculty": """
        CREATE TABLE IF NOT EXISTS faculty (
            id    SERIAL PRIMARY KEY,
            name  TEXT NOT NULL,
            department  TEXT,
            designation TEXT,
            email       TEXT,
            aliases     TEXT
        );
    """,

    "placements": """
        CREATE TABLE IF NOT EXISTS placements (
            id              SERIAL PRIMARY KEY,
            year            INTEGER,
            company         TEXT,
            branch          TEXT,
            package_lpa     DOUBLE PRECISION,
            students_placed INTEGER
        );
    """,

    "locations": """
        CREATE TABLE IF NOT EXISTS locations (
            id              SERIAL PRIMARY KEY,
            name            TEXT,
            aliases         TEXT,
            category        TEXT,
            latitude        DOUBLE PRECISION,
            longitude       DOUBLE PRECISION,
            parent_building TEXT,
            floor_info      TEXT,
            image_url       TEXT
        );
    """,

    "programs": """
        CREATE TABLE IF NOT EXISTS programs (
            id             SERIAL PRIMARY KEY,
            program_name   TEXT,
            level          TEXT,
            department     TEXT,
            intake         INTEGER,
            duration_years INTEGER
        );
    """,

    "cutoffs": """
        CREATE TABLE IF NOT EXISTS cutoffs (
            id         SERIAL PRIMARY KEY,
            year       INTEGER,
            branch     TEXT,
            category   TEXT,
            percentile DOUBLE PRECISION
        );
    """,

    "users": """
        CREATE TABLE IF NOT EXISTS users (
            id            SERIAL PRIMARY KEY,
            username      VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role          VARCHAR(50) NOT NULL CHECK (role IN ('student', 'faculty', 'admin')),
            email         VARCHAR(255),
            created_at    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers: Database connections
# ═══════════════════════════════════════════════════════════════════════════════
def connect_sqlite():
    """Return a read-only connection to the SQLite campus.db."""
    if not os.path.exists(SQLITE_DB_PATH):
        print(f"❌ SQLite database not found at: {SQLITE_DB_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(f"file:{SQLITE_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def connect_postgres():
    """Return a connection to the PostgreSQL campus_chat database."""
    if psycopg2 is None:
        print("❌ psycopg2 is not installed. Run: pip install psycopg2-binary")
        sys.exit(1)

    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")
    db_name = os.environ.get("DB_NAME", "campus_chat")
    db_user = os.environ.get("DB_USER", "campus_user")
    db_pass = os.environ.get("DB_PASSWORD")

    if not db_pass:
        print("❌ DB_PASSWORD environment variable is not set.")
        print("   Set it via .env file or: export DB_PASSWORD='your_password'")
        sys.exit(1)

    try:
        conn = psycopg2.connect(
            host=db_host,
            port=int(db_port),
            dbname=db_name,
            user=db_user,
            password=db_pass,
        )
        return conn
    except psycopg2.OperationalError as e:
        print(f"❌ Could not connect to PostgreSQL: {e}")
        print("   Make sure PostgreSQL is running and credentials match .env")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# --inspect : read-only SQLite schema inspection
# ═══════════════════════════════════════════════════════════════════════════════
def cmd_inspect():
    """Print SQLite schema and stats for all tables (read-only)."""
    print("=" * 60)
    print("  SQLite Schema Inspection  (read-only)")
    print("=" * 60)

    conn = connect_sqlite()
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    all_tables = [row[0] for row in cur.fetchall()]
    print(f"\nAll tables in {SQLITE_DB_PATH}:")
    for t in all_tables:
        marker = "✓" if t in EXPECTED_TABLES else " "
        print(f"  {marker} {t}")

    print()

    for table in EXPECTED_TABLES:
        if table not in all_tables:
            print(f"⚠  Table '{table}' NOT FOUND in SQLite database.\n")
            continue

        print(f"─── {table} ───")
        cur.execute(f"PRAGMA table_info('{table}');")
        columns = cur.fetchall()
        print(f"  {'Column':<20} {'Type':<15} {'NotNull':<8} {'PK'}")
        print(f"  {'─'*20} {'─'*15} {'─'*8} {'─'*4}")
        for col in columns:
            cid, cname, ctype, notnull, default, pk = col
            nn = "YES" if notnull else ""
            pk_str = "YES" if pk else ""
            print(f"  {cname:<20} {ctype:<15} {nn:<8} {pk_str}")

        cur.execute(f"SELECT COUNT(*) FROM \"{table}\";")
        count = cur.fetchone()[0]
        print(f"  Rows: {count}\n")

    conn.close()
    print("Inspection complete. No databases were modified.")


# ═══════════════════════════════════════════════════════════════════════════════
# --create-tables : create PostgreSQL tables (schema only)
# ═══════════════════════════════════════════════════════════════════════════════
def cmd_create_tables():
    """Create the campus tables in PostgreSQL."""
    print("=" * 60)
    print("  PostgreSQL Table Creation  (schema only — no data)")
    print("=" * 60)

    print("\n[1/4] Testing SQLite connection …")
    sqlite_conn = connect_sqlite()
    print("  SQLite connection: OK")

    print("\n[2/4] Testing PostgreSQL connection …")
    pg_conn = connect_postgres()
    print("  PostgreSQL connection: OK")

    print("\n[3/4] Creating tables …")
    pg_cur = pg_conn.cursor()
    try:
        for table, ddl in PG_CREATE_STATEMENTS.items():
            pg_cur.execute(ddl)
            print(f"  ✓ {table}")
        pg_conn.commit()
        print("\n  All tables created successfully (transaction committed).")
    except Exception as e:
        pg_conn.rollback()
        print(f"\n  ❌ Error creating tables — rolled back: {e}")
        pg_cur.close()
        pg_conn.close()
        sqlite_conn.close()
        sys.exit(1)

    print("\n[4/4] Verifying PostgreSQL tables …")
    pg_cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name;
    """)
    pg_tables = [row[0] for row in pg_cur.fetchall()]

    all_ok = True
    for table in EXPECTED_TABLES:
        if table in pg_tables:
            print(f"  ✓ {table}")
        else:
            print(f"  ✗ {table}  — MISSING")
            all_ok = False

    pg_cur.close()
    pg_conn.close()
    sqlite_conn.close()

    if all_ok:
        print("\n" + "=" * 60)
        print("  Database tables verified successfully.")
        print("=" * 60)
    else:
        print("\n❌ Some tables are missing — check errors above.")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# --migrate : Day 2 Complete Data Migration (SQLite -> PostgreSQL)
# ═══════════════════════════════════════════════════════════════════════════════
def cmd_migrate_data():
    """Migrate all records from SQLite to PostgreSQL with integrity checks."""
    print("=" * 60)
    print("  Day 2: SQLite -> PostgreSQL Data Migration")
    print("=" * 60)

    # 1. Connect to both databases
    sqlite_conn = connect_sqlite()
    pg_conn = connect_postgres()

    sqlite_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()

    # Ensure tables exist in PostgreSQL first
    for table, ddl in PG_CREATE_STATEMENTS.items():
        pg_cur.execute(ddl)
    pg_conn.commit()

    migration_counts = {}

    try:
        # Use a single transaction for all data migration
        print("\nMigrating tables...")
        for table in EXPECTED_TABLES:
            # Get columns from SQLite
            sqlite_cur.execute(f"PRAGMA table_info('{table}');")
            col_info = sqlite_cur.fetchall()
            col_names = [c[1] for c in col_info]

            # Fetch all rows from SQLite
            cols_quoted = ", ".join([f'"{col}"' for col in col_names])
            sqlite_cur.execute(f"SELECT {cols_quoted} FROM \"{table}\" ORDER BY id;")
            sqlite_rows = sqlite_cur.fetchall()
            row_count = len(sqlite_rows)

            if row_count == 0:
                print(f"  - {table}: 0 rows in SQLite (table is empty, schema ready)")
                migration_counts[table] = (0, 0)
                continue

            # Construct idempotent INSERT with ON CONFLICT (id) DO UPDATE
            placeholders = ", ".join(["%s"] * len(col_names))
            col_str = ", ".join([f'"{col}"' for col in col_names])
            
            # Non-PK columns to update if record already exists
            update_clauses = [f'"{col}" = EXCLUDED."{col}"' for col in col_names if col != "id"]
            if update_clauses:
                conflict_action = f"DO UPDATE SET {', '.join(update_clauses)}"
            else:
                conflict_action = "DO NOTHING"

            insert_sql = f"""
                INSERT INTO "{table}" ({col_str})
                VALUES ({placeholders})
                ON CONFLICT (id) {conflict_action}
            """

            # Convert SQLite rows to tuples, properly preserving None/NULLs
            data_tuples = []
            for row in sqlite_rows:
                tuple_vals = tuple(row[col] for col in col_names)
                data_tuples.append(tuple_vals)

            # Execute batch insert
            psycopg2.extras.execute_batch(pg_cur, insert_sql, data_tuples)

            # Sync PostgreSQL sequence so next auto-generated id is > max(id)
            pg_cur.execute(f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', 'id'),
                    COALESCE((SELECT MAX(id) FROM "{table}"), 1),
                    (SELECT COUNT(*) > 0 FROM "{table}")
                );
            """)

            # Verify row count in PostgreSQL
            pg_cur.execute(f'SELECT COUNT(*) FROM "{table}";')
            pg_count = pg_cur.fetchone()[0]

            migration_counts[table] = (row_count, pg_count)
            print(f"  ✓ {table}: migrated {row_count} rows successfully")

        # Commit all changes atomically
        pg_conn.commit()
        print("\nAll data committed successfully.")

    except Exception as e:
        pg_conn.rollback()
        print(f"\n❌ Migration failed — transaction rolled back: {e}")
        pg_cur.close()
        pg_conn.close()
        sqlite_conn.close()
        sys.exit(1)

    # Print Migration Report
    print("\n" + "=" * 60)
    print("  Migration Report")
    print("=" * 60)
    all_matched = True
    for table in EXPECTED_TABLES:
        sq_cnt, pg_cnt = migration_counts.get(table, (0, 0))
        # Ensure count from DB is current
        pg_cur.execute(f'SELECT COUNT(*) FROM "{table}";')
        pg_cnt = pg_cur.fetchone()[0]
        status = "✓" if sq_cnt == pg_cnt else "✗ MISMATCH"
        if sq_cnt != pg_cnt:
            all_matched = False
        print(f"{table}: SQLite {sq_cnt} → PostgreSQL {pg_cnt} {status}")

    # Compare sample records
    print("\n" + "=" * 60)
    print("  Sample Record Comparison (SQLite vs PostgreSQL)")
    print("=" * 60)
    compare_samples(sqlite_conn, pg_conn)

    pg_cur.close()
    pg_conn.close()
    sqlite_conn.close()

    if all_matched:
        print("\n✅ Day 2 SQLite → PostgreSQL migration completed successfully.")
    else:
        print("\n❌ Warning: Row count mismatch detected.")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# Sample comparison helper
# ═══════════════════════════════════════════════════════════════════════════════
def compare_samples(sqlite_conn, pg_conn):
    """Compare first and last sample records between SQLite and PostgreSQL."""
    sq_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()

    for table in EXPECTED_TABLES:
        sq_cur.execute(f"SELECT COUNT(*) FROM \"{table}\";")
        cnt = sq_cur.fetchone()[0]
        if cnt == 0:
            print(f"\n[{table}]: 0 records (skipped sample comparison)")
            continue

        print(f"\n[{table}] Samples:")
        # Fetch sample IDs: first record (min id) and last record (max id)
        sq_cur.execute(f"SELECT MIN(id), MAX(id) FROM \"{table}\";")
        min_id, max_id = sq_cur.fetchone()
        sample_ids = sorted(list({min_id, max_id}))

        sq_cur.execute(f"PRAGMA table_info('{table}');")
        cols = [c[1] for c in sq_cur.fetchall()]
        cols_sql = ", ".join([f'"{c}"' for c in cols])

        for sid in sample_ids:
            sq_cur.execute(f"SELECT {cols_sql} FROM \"{table}\" WHERE id = ?", (sid,))
            sq_row = dict(sq_cur.fetchone())

            pg_cur.execute(f"SELECT {cols_sql} FROM \"{table}\" WHERE id = %s;", (sid,))
            pg_row_vals = pg_cur.fetchone()
            pg_row = dict(zip(cols, pg_row_vals)) if pg_row_vals else None

            if pg_row is None:
                print(f"  ❌ ID {sid}: Missing in PostgreSQL!")
                continue

            match = True
            for col in cols:
                sq_val = sq_row[col]
                pg_val = pg_row[col]
                # Handle float rounding differences if any
                if isinstance(sq_val, float) and isinstance(pg_val, float):
                    if abs(sq_val - pg_val) > 1e-6:
                        match = False
                        break
                elif sq_val != pg_val:
                    match = False
                    break

            status = "✓ MATCH" if match else "✗ DIFF"
            summary_parts = []
            for col in cols[:3]:
                summary_parts.append(f"{col}={sq_row[col]}")
            print(f"  ID {sid:<4} {status} ({', '.join(summary_parts)})")


# ═══════════════════════════════════════════════════════════════════════════════
# --verify : verify both SQLite and PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════════
def cmd_verify():
    """Verify that both databases have matching tables and row counts."""
    print("=" * 60)
    print("  Database Verification")
    print("=" * 60)

    print("\nSQLite connection: ", end="")
    try:
        sqlite_conn = connect_sqlite()
        print("OK")
    except SystemExit:
        return

    cur = sqlite_conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    sqlite_tables = [row[0] for row in cur.fetchall()]

    sqlite_counts = {}
    print("\nDetected SQLite tables:")
    for table in EXPECTED_TABLES:
        marker = "✓" if table in sqlite_tables else "✗"
        if table in sqlite_tables:
            cur.execute(f"SELECT COUNT(*) FROM \"{table}\";")
            count = cur.fetchone()[0]
            sqlite_counts[table] = count
            print(f"  {marker} {table:<12} ({count} rows)")
        else:
            print(f"  {marker} {table:<12} (MISSING)")

    print("\nPostgreSQL connection: ", end="")
    try:
        pg_conn = connect_postgres()
        print("OK")
    except SystemExit:
        sqlite_conn.close()
        return

    pg_cur = pg_conn.cursor()
    pg_cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name;
    """)
    pg_tables = [row[0] for row in pg_cur.fetchall()]

    pg_counts = {}
    print("\nPostgreSQL schema:")
    all_matched = True
    for table in EXPECTED_TABLES:
        if table in pg_tables:
            pg_cur.execute(f"SELECT COUNT(*) FROM \"{table}\";")
            count = pg_cur.fetchone()[0]
            pg_counts[table] = count
            print(f"  ✓ {table:<12} ({count} rows)")
        else:
            print(f"  ✗ {table:<12} — MISSING")
            all_matched = False

    print("\n" + "=" * 60)
    print("  Table Row Comparison")
    print("=" * 60)
    for table in EXPECTED_TABLES:
        sq_c = sqlite_counts.get(table, -1)
        pg_c = pg_counts.get(table, -1)
        status = "✓" if sq_c == pg_c else "✗ MISMATCH"
        if sq_c != pg_c:
            all_matched = False
        print(f"{table:<12}: SQLite {sq_c} → PostgreSQL {pg_c} {status}")

    print("\n" + "=" * 60)
    print("  Sample Record Comparison")
    print("=" * 60)
    compare_samples(sqlite_conn, pg_conn)

    pg_cur.close()
    pg_conn.close()
    sqlite_conn.close()

    if all_matched:
        print("\n" + "=" * 60)
        print("  Database verification completed successfully.")
        print("=" * 60)
    else:
        print("\n⚠  Some differences were detected.")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="Campus Chat — SQLite → PostgreSQL migration tool"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--inspect",
        action="store_true",
        help="Inspect the SQLite schema (read-only, does NOT touch PostgreSQL).",
    )
    group.add_argument(
        "--create-tables",
        action="store_true",
        help="Create equivalent PostgreSQL tables (schema only, no data).",
    )
    group.add_argument(
        "--migrate",
        "--migrate-data",
        dest="migrate",
        action="store_true",
        help="Migrate all data from SQLite to PostgreSQL (Day 2).",
    )
    group.add_argument(
        "--verify",
        action="store_true",
        help="Verify both SQLite and PostgreSQL have matching tables and counts.",
    )

    args = parser.parse_args()

    if args.inspect:
        cmd_inspect()
    elif args.create_tables:
        cmd_create_tables()
    elif args.migrate:
        cmd_migrate_data()
    elif args.verify:
        cmd_verify()


if __name__ == "__main__":
    main()
