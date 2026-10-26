#!/usr/bin/env python3
"""
migrate_week4.py - Safe database migration runner for Week 4 schema.
Applies migrations_week4.sql without modifying or dropping any existing tables.
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME", "campus_chat")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")


def run_migration():
    print("=" * 60)
    print("  Running Week 4 Database Migration on PostgreSQL")
    print(f"  Target: {DB_NAME} at {DB_HOST}:{DB_PORT} as {DB_USER}")
    print("=" * 60)

    sql_file = os.path.join(os.path.dirname(__file__), "migrations_week4.sql")
    if not os.path.exists(sql_file):
        print(f"[!] Migration script not found: {sql_file}")
        sys.exit(1)

    with open(sql_file, "r", encoding="utf-8") as f:
        sql = f.read()

    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
        print("[OK] Week 4 tables and indexes created successfully!")

        # Verify tables created
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        tables = [row[0] for row in cur.fetchall()]
        print(f"[OK] Current tables in {DB_NAME} ({len(tables)}):")
        for t in tables:
            print(f"    - {t}")

        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[X] Migration failed: {e}")
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
