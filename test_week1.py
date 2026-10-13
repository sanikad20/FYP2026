#!/usr/bin/env python3
"""
test_week1.py — Comprehensive End-to-End Test Suite for Week 1 (Days 1–7)

Tests:
  [Day 2] SQLite -> PostgreSQL Data Migration & Integrity
  [Day 3] Flask Backend PostgreSQL Database Layer (SQLDatabase & direct queries)
  [Day 4] Redis Session Storage (read/write, TTL, persistence)
  [Day 5–7] Authentication & RBAC (register, login, logout, roles, protected routes)
"""

import os
import sys
import json
import sqlite3
import psycopg2
import redis
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv

load_dotenv()

# Import the application
import backend_api_original as app_module
from backend_api_original import (
    app, db, sessions, get_db_connection,
    _try_faculty_directory_answer, _try_faculty_contact_answer,
    REDIS_HOST, REDIS_PORT, REDIS_DB
)

TEST_RESULTS = []

def record_test(name: str, passed: bool, detail: str = ""):
    status = "✓ PASS" if passed else "✗ FAIL"
    TEST_RESULTS.append((name, passed, detail))
    print(f"[{status}] {name}")
    if detail:
        print(f"        {detail}")


def test_day2_migration():
    print("\n" + "=" * 60)
    print("  Testing Day 2: SQLite -> PostgreSQL Migration")
    print("=" * 60)

    # 1. Check SQLite campus.db and campus_backup.db
    sq_path = "campus.db"
    bak_path = "campus_backup.db"
    record_test("campus.db exists", os.path.exists(sq_path))
    record_test("campus_backup.db exists", os.path.exists(bak_path))

    # 2. Check row counts match
    tables = ["faculty", "programs", "cutoffs", "locations", "placements"]
    sq_conn = sqlite3.connect(sq_path)
    sq_cur = sq_conn.cursor()

    pg_conn = get_db_connection()
    pg_cur = pg_conn.cursor()

    for table in tables:
        sq_cur.execute(f'SELECT COUNT(*) FROM "{table}";')
        sq_count = sq_cur.fetchone()[0]

        pg_cur.execute(f'SELECT COUNT(*) FROM "{table}";')
        pg_count = pg_cur.fetchone()[0]

        matched = (sq_count == pg_count)
        record_test(
            f"Row count match: {table}",
            matched,
            f"SQLite: {sq_count} | PostgreSQL: {pg_count}"
        )

    # 3. Check sample values
    pg_cur.execute("SELECT id, name, department, email FROM faculty WHERE id = 1;")
    f1 = pg_cur.fetchone()
    record_test("Faculty sample (id=1)", f1 and f1[1] == "Dr. Sachin D. Kore", f"{f1}")

    pg_cur.execute("SELECT id, program_name, intake FROM programs WHERE id = 1;")
    p1 = pg_cur.fetchone()
    record_test("Programs sample (id=1)", p1 and "Civil" in p1[1], f"{p1}")

    pg_cur.execute("SELECT id, branch, percentile FROM cutoffs WHERE id = 1;")
    c1 = pg_cur.fetchone()
    record_test("Cutoffs sample (id=1)", c1 and c1[2] > 90, f"{c1}")

    sq_conn.close()
    pg_conn.close()


def test_day3_postgres_backend():
    print("\n" + "=" * 60)
    print("  Testing Day 3: Flask Backend with PostgreSQL")
    print("=" * 60)

    # 1. LangChain SQLDatabase against PostgreSQL
    try:
        faculty_run = db.run("SELECT COUNT(*) FROM faculty;")
        record_test("SQLDatabase query faculty", "44" in str(faculty_run), f"Result: {faculty_run}")
    except Exception as e:
        record_test("SQLDatabase query faculty", False, str(e))

    try:
        programs_run = db.run("SELECT COUNT(*) FROM programs;")
        record_test("SQLDatabase query programs", "30" in str(programs_run), f"Result: {programs_run}")
    except Exception as e:
        record_test("SQLDatabase query programs", False, str(e))

    try:
        cutoffs_run = db.run("SELECT COUNT(*) FROM cutoffs;")
        record_test("SQLDatabase query cutoffs", "106" in str(cutoffs_run), f"Result: {cutoffs_run}")
    except Exception as e:
        record_test("SQLDatabase query cutoffs", False, str(e))

    # 2. Test direct faculty directory resolver (uses ILIKE %s)
    ans_dir = _try_faculty_directory_answer("faculty in computer")
    record_test(
        "Faculty directory query (computer)",
        ans_dir is not None and "Nikam" in ans_dir,
        f"Answer: {ans_dir[:80]}..." if ans_dir else "None"
    )

    # 3. Test direct faculty contact resolver (uses ILIKE %s)
    ans_contact = _try_faculty_contact_answer("what is the email of director?")
    record_test(
        "Faculty contact query (director email)",
        ans_contact is not None and "director@vjti.ac.in" in ans_contact,
        f"Answer: {ans_contact}" if ans_contact else "None"
    )

    ans_dean = _try_faculty_contact_answer("email id of dean")
    record_test(
        "Faculty contact query (dean email)",
        ans_dean is not None and "@vjti.ac.in" in ans_dean,
        f"Answer: {ans_dean}" if ans_dean else "None"
    )


def test_day4_redis_sessions():
    print("\n" + "=" * 60)
    print("  Testing Day 4: Redis Session Storage")
    print("=" * 60)

    # 1. Redis connectivity
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB)
    ping_ok = r.ping()
    record_test("Redis ping", ping_ok, f"Connected to {REDIS_HOST}:{REDIS_PORT}")

    # 2. Store messages in RedisSessionStore
    from langchain_core.messages import HumanMessage, AIMessage
    test_sid = "test_e2e_session_week1"
    test_msgs = [
        HumanMessage(content="Hello Campus Bot"),
        AIMessage(content="Hello! How can I assist you today?")
    ]
    sessions[test_sid] = test_msgs

    # 3. Verify key exists in Redis with TTL
    redis_key = f"campus_chat:session:{test_sid}"
    exists_in_redis = bool(r.exists(redis_key))
    ttl = r.ttl(redis_key)
    record_test(
        "Session written to Redis with TTL",
        exists_in_redis and ttl > 0,
        f"Key: {redis_key}, TTL: {ttl}s"
    )

    # 4. Retrieve back through sessions
    retrieved = sessions[test_sid]
    record_test(
        "Session retrieved from Redis",
        len(retrieved) == 2 and retrieved[0].content == "Hello Campus Bot" and retrieved[1].content == "Hello! How can I assist you today?",
        f"Retrieved {len(retrieved)} messages"
    )

    # 5. Clear session
    popped = sessions.pop(test_sid)
    key_cleared = not bool(r.exists(redis_key))
    record_test("Session cleared from Redis", key_cleared, f"Key removed: {key_cleared}")


def test_day5_7_auth_and_rbac():
    print("\n" + "=" * 60)
    print("  Testing Day 5–7: Authentication and RBAC")
    print("=" * 60)

    client = app.test_client()

    # Clean up test users if existing
    pg_conn = get_db_connection()
    pg_cur = pg_conn.cursor()
    pg_cur.execute("DELETE FROM users WHERE username IN ('test_student', 'test_faculty', 'test_admin');")
    pg_conn.commit()
    pg_conn.close()

    # 1. Registration
    r_student = client.post("/api/auth/register", json={
        "username": "test_student",
        "password": "password123",
        "role": "student",
        "email": "student@vjti.ac.in"
    })
    record_test("Register Student", r_student.status_code == 201, f"{r_student.get_json()}")

    r_privileged = client.post("/api/auth/register", json={
        "username": "test_admin",
        "password": "adminpassword123",
        "role": "admin",
        "email": "admin@vjti.ac.in"
    })
    record_test("Self-registration cannot grant admin role (403)", r_privileged.status_code == 403)

    pg_conn = get_db_connection()
    pg_cur = pg_conn.cursor()
    pg_cur.executemany(
        "INSERT INTO users (username, password_hash, role, email) VALUES (%s, %s, %s, %s);",
        [
            ("test_faculty", generate_password_hash("password123"), "faculty", "faculty@vjti.ac.in"),
            ("test_admin", generate_password_hash("adminpassword123"), "admin", "admin@vjti.ac.in"),
        ],
    )
    pg_conn.commit()
    pg_cur.close()
    pg_conn.close()

    # 2. Duplicate registration rejected
    r_dup = client.post("/api/auth/register", json={
        "username": "test_student",
        "password": "password123",
        "role": "student"
    })
    record_test("Duplicate registration rejected (409)", r_dup.status_code == 409, f"{r_dup.get_json()}")

    # 3. Invalid inputs rejected
    r_short_pass = client.post("/api/auth/register", json={
        "username": "newuser",
        "password": "123",
        "role": "student"
    })
    record_test("Short password rejected (400)", r_short_pass.status_code == 400)

    r_bad_role = client.post("/api/auth/register", json={
        "username": "newuser2",
        "password": "password123",
        "role": "superuser"
    })
    record_test("Invalid role rejected (400)", r_bad_role.status_code == 400)

    # 4. Verify password hashing in PostgreSQL
    pg_conn = get_db_connection()
    pg_cur = pg_conn.cursor()
    pg_cur.execute("SELECT password_hash FROM users WHERE username = 'test_student';")
    stored_hash = pg_cur.fetchone()[0]
    is_hashed = (
        not stored_hash.startswith("password123")
        and ("pbkdf2" in stored_hash or "scrypt" in stored_hash)
        and check_password_hash(stored_hash, "password123")
    )
    record_test("Password securely hashed in DB (never plaintext)", is_hashed, f"Hash starts with: {stored_hash[:20]}...")
    pg_conn.close()

    # 5. Invalid login rejected
    r_bad_pass = client.post("/api/auth/login", json={
        "username": "test_student",
        "password": "wrongpassword"
    })
    record_test("Wrong password rejected (401)", r_bad_pass.status_code == 401)

    r_no_user = client.post("/api/auth/login", json={
        "username": "nonexistent_user",
        "password": "password123"
    })
    record_test("Nonexistent user rejected (401)", r_no_user.status_code == 401)

    # 6. Unauthenticated access to admin route rejected
    r_unauth_admin = client.get("/api/admin/status")
    record_test("Unauthenticated admin route rejected (401)", r_unauth_admin.status_code == 401, f"{r_unauth_admin.get_json()}")

    # 7. Student Login & Permissions
    student_client = app.test_client()
    login_s = student_client.post("/api/auth/login", json={
        "username": "test_student",
        "password": "password123"
    })
    record_test("Student login success (200)", login_s.status_code == 200, f"{login_s.get_json()}")

    me_s = student_client.get("/api/auth/me")
    record_test("Student identity verified", me_s.get_json().get("user", {}).get("role") == "student")

    admin_s = student_client.get("/api/admin/status")
    record_test("Student denied admin route (403)", admin_s.status_code == 403, f"{admin_s.get_json()}")

    # 8. Faculty Login & Permissions
    faculty_client = app.test_client()
    login_f = faculty_client.post("/api/auth/login", json={
        "username": "test_faculty",
        "password": "password123"
    })
    record_test("Faculty login success (200)", login_f.status_code == 200)

    me_f = faculty_client.get("/api/auth/me")
    record_test("Faculty role recognized", me_f.get_json().get("user", {}).get("role") == "faculty")

    admin_f = faculty_client.get("/api/admin/status")
    record_test("Faculty denied admin route (403)", admin_f.status_code == 403, f"{admin_f.get_json()}")

    # 9. Admin Login & Permissions
    admin_client = app.test_client()
    login_a = admin_client.post("/api/auth/login", json={
        "username": "test_admin",
        "password": "adminpassword123"
    })
    record_test("Admin login success (200)", login_a.status_code == 200)

    admin_status = admin_client.get("/api/admin/status")
    as_json = admin_status.get_json()
    record_test(
        "Admin accesses /api/admin/status (200)",
        admin_status.status_code == 200 and as_json.get("active_database") == "PostgreSQL (campus_chat)",
        f"Counts: {as_json.get('table_counts')}"
    )

    admin_page = admin_client.get("/admin")
    record_test("Admin accesses /admin (200)", admin_page.status_code == 200)

    # 10. Logout
    logout_res = admin_client.post("/api/auth/logout")
    record_test("Logout succeeds (200)", logout_res.status_code == 200)

    after_logout = admin_client.get("/api/admin/status")
    record_test("Logged out user denied admin route (401)", after_logout.status_code == 401)


def main():
    print("=" * 60)
    print("  CAMPUS CHAT — WEEK 1 TEST SUITE (DAYS 2–7)")
    print("=" * 60)

    test_day2_migration()
    test_day3_postgres_backend()
    test_day4_redis_sessions()
    test_day5_7_auth_and_rbac()

    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)
    total = len(TEST_RESULTS)
    passed = sum(1 for _, p, _ in TEST_RESULTS if p)
    failed = total - passed

    for name, p, detail in TEST_RESULTS:
        mark = "✓" if p else "✗"
        print(f" {mark} {name}")

    print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed}")

    if failed == 0:
        print("\n🎉 ALL WEEK 1 TESTS PASSED PERFECTLY!")
        sys.exit(0)
    else:
        print(f"\n❌ {failed} tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
