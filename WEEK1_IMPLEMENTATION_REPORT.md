# Week 1 Implementation Report — Campus Chat Migration & Foundation

> **Project:** Campus Chat  
> **Milestone:** Week 1 Checkpoint Completed (Days 1–7)  
> **Final Status:** Campus Chat runs end-to-end on PostgreSQL + Redis with login & RBAC verified.

---

## 1. Day 1 Work Already Completed

During Day 1:
- Inspected the project architecture, dependencies, and SQLite database `campus.db`.
- Created safety backup `campus_backup.db` (MD5: `07e0470b8c20b7d1a21901c3daf83564`).
- Created `.env.example` defining database parameters (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`).
- Created `requirements.txt` containing existing dependencies plus `psycopg2-binary` and `python-dotenv`.
- Added `.env` and `campus_backup.db` to `.gitignore`.
- Created `migrate_sqlite_to_postgres.py` with schema extraction, inspection, and PostgreSQL table DDL.
- Documented findings in `DAY1_POSTGRES_SETUP.md`.

---

## 2. Day 2 Database Migration (SQLite → PostgreSQL)

On Day 2:
- Extended `migrate_sqlite_to_postgres.py` with complete data migration functionality (`--migrate`).
- Implemented transactional batch migration preserving original primary key `id` values.
- Handled `NULL` values correctly between SQLite and PostgreSQL types.
- Used idempotent SQL:
  ```sql
  INSERT INTO "<table>" (<columns>) VALUES (%s, ...)
  ON CONFLICT (id) DO UPDATE SET ...
  ```
  allowing the migration script to be executed multiple times without duplicate errors or data corruption.
- Synchronized PostgreSQL sequence generators post-migration:
  ```sql
  SELECT setval(pg_get_serial_sequence('<table>', 'id'), COALESCE(MAX(id), 1), COUNT(*) > 0) FROM "<table>";
  ```
- Kept `campus.db` and `campus_backup.db` completely read-only and unmodified (verified by MD5 checksum `07e0470b8c20b7d1a21901c3daf83564`).

### Migration Report
| Table | SQLite Count | PostgreSQL Count | Status | Sample ID Matches |
|-------|--------------|------------------|--------|-------------------|
| `faculty` | 44 | 44 | ✓ MATCH | ID 1 (`Dr. Sachin D. Kore`), ID 44 (`Dr. Nilima Chaudhary`) |
| `programs` | 30 | 30 | ✓ MATCH | ID 1 (`B.Tech Civil Engineering`), ID 30 (`MCA`) |
| `cutoffs` | 106 | 106 | ✓ MATCH | ID 1 (2025 Computer Engg), ID 106 (2024 Textile Tech) |
| `locations` | 9 | 9 | ✓ MATCH | ID 1 (`Main Gate`), ID 9 (`Seminar Hall`) |
| `placements` | 0 | 0 | ✓ MATCH | Schema created, 0 rows in source SQLite |

---

## 3. Day 3 Flask PostgreSQL Integration

On Day 3:
- Updated the backend application in `backend_api_original.py` (and symlinked `backend_api.py`).
- Switched LangChain's `SQLDatabase` connection from SQLite to PostgreSQL:
  ```python
  PG_URI = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
  db = SQLDatabase.from_uri(PG_URI)
  ```
- Created reusable database helper `get_db_connection()` using environment variables.
- Replaced direct `sqlite3.connect("campus.db")` calls in:
  - `_try_faculty_directory_answer`: parameterized with `ILIKE %s` and safe cursor closing.
  - `_try_faculty_contact_answer`: parameterized with `ILIKE %s`, escaped literal `%` in `ORDER BY CASE` clauses, and safe cursor closing.
- Preserved 100% of existing query logic and RAG vector search functionality.
- Original `campus.db` remains untouched as a read-only reference.

---

## 4. Day 4 Redis Integration

On Day 4:
- Integrated Redis for session storage via environment variables:
  - `REDIS_HOST=localhost`
  - `REDIS_PORT=6379`
  - `REDIS_DB=0`
  - `SESSION_TTL=86400` (24 hours expiration)
- Replaced the in-memory `sessions = {}` dictionary with `RedisSessionStore`:
  - Stores message history serialized in Redis under key `campus_chat:session:<session_id>`.
  - Serializes and deserializes LangChain message instances (`HumanMessage`, `AIMessage`, `SystemMessage`).
  - Supports dictionary interface (`__getitem__`, `__setitem__`, `__contains__`, `get`, `pop`, `items`) to keep backend routing transparent.
  - Automatically sets key TTL on save.
  - Transparent fallback: in case of Redis downtime, gracefully falls back to an in-memory dictionary without crashing the chatbot.

---

## 5. Day 5–7 Authentication & Role-Based Access Control (RBAC)

On Days 5–7:
- Created the PostgreSQL `users` table:
  ```sql
  CREATE TABLE IF NOT EXISTS users (
      id            SERIAL PRIMARY KEY,
      username      VARCHAR(100) UNIQUE NOT NULL,
      password_hash VARCHAR(255) NOT NULL,
      role          VARCHAR(50) NOT NULL CHECK (role IN ('student', 'faculty', 'admin')),
      email         VARCHAR(255),
      created_at    TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
  );
  ```
- Implemented secure password hashing via `werkzeug.security` (`generate_password_hash` / `check_password_hash`). Plaintext passwords are never stored.
- Implemented server-side Flask sessions for session-based authentication backed by secret key.
- Created reusable protection decorators:
  - `@login_required`: Rejects unauthenticated requests with `401 Unauthorized`.
  - `@role_required(*allowed_roles)`: Rejects users lacking required roles with `403 Forbidden`.
- Implemented authentication endpoints:
  - `POST /api/auth/register`: Validates username, password length, and role; hashes password; stores user in PostgreSQL. Returns 201 Created.
  - `POST /api/auth/login`: Validates credentials; initializes server session with `user_id`, `username`, `role`. Returns 200 OK.
  - `POST /api/auth/logout`: Clears session. Returns 200 OK.
  - `GET /api/auth/me`: Returns current user identity and authentication status.
  - `GET /api/admin/status` and `GET /admin`: Admin-only diagnostic routes protected by `@role_required("admin")`.
- Protected chat endpoints (`/api/chat`, `/api/chat/stream`) with `@login_required`.

---

## 6. Files Created

| File | Purpose |
|------|---------|
| `campus_backup.db` | Safety backup of initial SQLite database |
| `migrate_sqlite_to_postgres.py` | Complete database schema and data migration tool |
| `.env.example` | Environment variable template with PostgreSQL, Redis, and Secret Key placeholders |
| `.env` | Local configuration (ignored by Git) |
| `requirements.txt` | Python dependency manifest including PostgreSQL, Redis, and LangChain dependencies |
| `backend_api.py` | Symlink to backend API for convenient invocation |
| `backend_api_original.py.bak` | Safety backup of original backend file |
| `test_week1.py` | Automated end-to-end test suite for Days 2–7 |
| `DAY1_POSTGRES_SETUP.md` | Day 1 setup documentation |
| `WEEK1_IMPLEMENTATION_REPORT.md` | This Week 1 comprehensive implementation report |

---

## 7. Files Modified

| File | Description of Changes |
|------|------------------------|
| `backend_api_original.py` | Replaced SQLite database layer with PostgreSQL (`SQLDatabase` + `psycopg2`); added Redis session management; added user registration, login, logout, me, and admin endpoints; added `@login_required` and `@role_required` decorators |
| `.gitignore` | Added `.env` and `campus_backup.db` exclusions |

---

## 8. Database Changes

### PostgreSQL (`campus_chat` database)
- **`faculty`**: 44 rows migrated from SQLite.
- **`programs`**: 30 rows migrated from SQLite.
- **`cutoffs`**: 106 rows migrated from SQLite.
- **`locations`**: 9 rows migrated from SQLite.
- **`placements`**: Schema created (0 rows in source SQLite).
- **`users`**: Added authentication table with `id`, `username`, `password_hash`, `role`, `email`, `created_at`.

---

## 9. Redis Configuration

- **Host:** `localhost`
- **Port:** `6379`
- **Database Index:** `0`
- **Session Key Format:** `campus_chat:session:<session_id>`
- **TTL:** 86,400 seconds (24 hours)

---

## 10. Authentication Architecture

```
User / Frontend
      │
      ▼
POST /api/auth/login ──> Authenticate against PostgreSQL (users table)
      │
      ▼
Server sets session cookie (user_id, username, role)
      │
      ├──> /api/chat (Student, Faculty, Admin permitted)
      │       └──> Chat session stored in Redis with TTL
      │
      └──> /api/admin/status (Admin ONLY)
              ├──> Admin: 200 OK (Diagnostics & counts)
              ├──> Student / Faculty: 403 Forbidden
              └──> Unauthenticated: 401 Unauthorized
```

---

## 11. Role-Based Authorization Matrix

| Route | Unauthenticated | Student | Faculty | Admin |
|-------|-----------------|---------|---------|-------|
| `/api/auth/login` | 200 (Permitted) | 200 | 200 | 200 |
| `/api/auth/register` | 201 (Permitted) | 201 | 201 | 201 |
| `/api/auth/me` | 200 (`authenticated: false`) | 200 (`role: student`) | 200 (`role: faculty`) | 200 (`role: admin`) |
| `/api/chat` | 401 Unauthorized | 200 OK | 200 OK | 200 OK |
| `/api/history` | 200 OK | 200 OK | 200 OK | 200 OK |
| `/api/admin/status` | 401 Unauthorized | 403 Forbidden | 403 Forbidden | 200 OK |
| `/admin` | 401 Unauthorized | 403 Forbidden | 403 Forbidden | 200 OK |

---

## 12. Tests Performed & 13. Test Results

Executed via automated test suite `python3 test_week1.py`:

```
============================================================
  CAMPUS CHAT — WEEK 1 TEST SUITE (DAYS 2–7)
============================================================

============================================================
  Testing Day 2: SQLite -> PostgreSQL Migration
============================================================
[✓ PASS] campus.db exists
[✓ PASS] campus_backup.db exists
[✓ PASS] Row count match: faculty (SQLite: 44 | PostgreSQL: 44)
[✓ PASS] Row count match: programs (SQLite: 30 | PostgreSQL: 30)
[✓ PASS] Row count match: cutoffs (SQLite: 106 | PostgreSQL: 106)
[✓ PASS] Row count match: locations (SQLite: 9 | PostgreSQL: 9)
[✓ PASS] Row count match: placements (SQLite: 0 | PostgreSQL: 0)
[✓ PASS] Faculty sample (id=1: Dr. Sachin D. Kore)
[✓ PASS] Programs sample (id=1: B.Tech Civil Engineering)
[✓ PASS] Cutoffs sample (id=1: Computer Engineering)

============================================================
  Testing Day 3: Flask Backend with PostgreSQL
============================================================
[✓ PASS] SQLDatabase query faculty (44 rows)
[✓ PASS] SQLDatabase query programs (30 rows)
[✓ PASS] SQLDatabase query cutoffs (106 rows)
[✓ PASS] Faculty directory query (computer)
[✓ PASS] Faculty contact query (director email)
[✓ PASS] Faculty contact query (dean email)

============================================================
  Testing Day 4: Redis Session Storage
============================================================
[✓ PASS] Redis ping
[✓ PASS] Session written to Redis with TTL
[✓ PASS] Session retrieved from Redis
[✓ PASS] Session cleared from Redis

============================================================
  Testing Day 5–7: Authentication and RBAC
============================================================
[✓ PASS] Register Student
[✓ PASS] Register Faculty
[✓ PASS] Register Admin
[✓ PASS] Duplicate registration rejected (409)
[✓ PASS] Short password rejected (400)
[✓ PASS] Invalid role rejected (400)
[✓ PASS] Password securely hashed in DB (scrypt hash, never plaintext)
[✓ PASS] Wrong password rejected (401)
[✓ PASS] Nonexistent user rejected (401)
[✓ PASS] Unauthenticated admin route rejected (401)
[✓ PASS] Student login success (200)
[✓ PASS] Student identity verified
[✓ PASS] Student denied admin route (403)
[✓ PASS] Faculty login success (200)
[✓ PASS] Faculty role recognized
[✓ PASS] Faculty denied admin route (403)
[✓ PASS] Admin login success (200)
[✓ PASS] Admin accesses /api/admin/status (200)
[✓ PASS] Admin accesses /admin (200)
[✓ PASS] Logout succeeds (200)
[✓ PASS] Logged out user denied admin route (401)

============================================================
  TEST SUMMARY: Total: 41 | Passed: 41 | Failed: 0
  Result: ALL WEEK 1 TESTS PASSED PERFECTLY!
============================================================
```

---

## 14. Problems Encountered & Resolutions

1. **PostgreSQL Service Status:** Host-level native PostgreSQL service was inactive and required root credentials.  
   *Resolution:* Deployed dedicated Docker PostgreSQL container (`campus_postgres`) mapped to port `5432` with user `campus_user` and database `campus_chat`.
2. **psycopg2 Literal Percent Signs in ORDER BY:** In `_try_faculty_contact_answer`, raw `%` symbols inside the SQL `CASE WHEN designation ILIKE '%Director%'` triggered parameter formatting errors.  
   *Resolution:* Escaped literal `%` signs as `%%Director%%` in accordance with `psycopg2` query syntax.
3. **LangChain Ollama Import Deprecation:** In newer LangChain versions, `ChatOllama` moved to `langchain_ollama`.  
   *Resolution:* Added `langchain-ollama` and implemented dual import handling with graceful fallback.

---

## 15. Remaining Issues

None. All Week 1 criteria are met, tested, and passing.

---

## How to Run the Completed Application

### 1. Ensure Services Are Running
```bash
# Redis
redis-cli ping   # Should return PONG

# PostgreSQL
docker ps | grep campus_postgres
```

### 2. Run Database Migration Script (if re-syncing)
```bash
# Inspect SQLite schema:
python3 migrate_sqlite_to_postgres.py --inspect

# Migrate data to PostgreSQL:
python3 migrate_sqlite_to_postgres.py --migrate

# Verify row counts and samples:
python3 migrate_sqlite_to_postgres.py --verify
```

### 3. Run Automated Week 1 Test Suite
```bash
python3 test_week1.py
```

### 4. Start the Flask Backend
```bash
python3 backend_api.py
# (or: python3 backend_api_original.py)
```
The server starts on port `5000` with PostgreSQL active database, Redis session storage, and RBAC enabled.
