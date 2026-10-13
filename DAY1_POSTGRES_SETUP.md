# Day 1 — PostgreSQL Setup & Migration Foundation

> **Date:** 2026-10-06  
> **Goal:** Set up the project for migration from SQLite to a local PostgreSQL database.  
> **Status:** Schema only — no data migration, no backend switch.

---

## 1. Files Inspected

| File | Purpose |
|------|---------|
| `campus.db` | Existing SQLite database (45 KB) |
| `setup.py` | Creates SQLite tables and inserts seed data |
| `backend_api_original.py` | Flask backend — uses `sqlite3.connect("campus.db")` and `SQLDatabase.from_uri("sqlite:///campus.db")` |
| `db_config.json` | Unique-key config for CSV upsert pipeline |
| `python csv_loader.py` | CSV → SQLite import pipeline |
| `trial.py` | Dev/test script using `SQLDatabase.from_uri("sqlite:///campus.db")` |
| `navigation.py` | Flask blueprint — does NOT use SQLite (hardcoded graph) |
| `.gitignore` | Version control exclusions |
| `setup_linux.txt` | Original Linux setup instructions |

---

## 2. Existing SQLite Schema

### faculty
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| name | TEXT | NOT NULL |
| department | TEXT | |
| designation | TEXT | |
| email | TEXT | |
| aliases | TEXT | |
**Rows:** 44

### programs
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| program_name | TEXT | |
| level | TEXT | |
| department | TEXT | |
| intake | INTEGER | |
| duration_years | INTEGER | |
**Rows:** 30

### cutoffs
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| year | INTEGER | |
| branch | TEXT | |
| category | TEXT | |
| percentile | REAL | |
**Rows:** 106

### locations
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| name | TEXT | |
| aliases | TEXT | |
| category | TEXT | |
| latitude | REAL | |
| longitude | REAL | |
| parent_building | TEXT | |
| floor_info | TEXT | |
| image_url | TEXT | |
**Rows:** 9

### placements
| Column | Type | Constraints |
|--------|------|-------------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT |
| year | INTEGER | |
| company | TEXT | |
| branch | TEXT | |
| package_lpa | REAL | |
| students_placed | INTEGER | |
**Rows:** 0

---

## 3. Files Created / Modified

### Created
| File | Purpose |
|------|---------|
| `campus_backup.db` | Safety backup of `campus.db` (identical MD5) |
| `migrate_sqlite_to_postgres.py` | Migration script with `--inspect`, `--create-tables`, `--verify` modes |
| `.env.example` | Environment variable template (no real password) |
| `requirements.txt` | Python dependencies including `psycopg2-binary` and `python-dotenv` |
| `DAY1_POSTGRES_SETUP.md` | This documentation file |

### Modified
| File | Change |
|------|--------|
| `.gitignore` | Added `.env` and `campus_backup.db` to exclusions |

### NOT Modified
- `campus.db` — untouched (verified by MD5 checksum)
- `backend_api_original.py` — no changes (still uses SQLite)
- `setup.py` — no changes
- `db_config.json` — no changes

---

## 4. PostgreSQL Installation (Ubuntu)

```bash
# Install PostgreSQL
sudo apt update
sudo apt install -y postgresql postgresql-contrib

# Verify it is running
sudo systemctl status postgresql
```

---

## 5. Create PostgreSQL User and Database

```bash
# Switch to the postgres system user
sudo -u postgres psql

# Inside the psql prompt, run:
CREATE USER campus_user WITH PASSWORD 'your_secure_password_here';
CREATE DATABASE campus_chat OWNER campus_user;
GRANT ALL PRIVILEGES ON DATABASE campus_chat TO campus_user;
\q
```

---

## 6. Required Environment Variables

Create a `.env` file in the project root (it is git-ignored):

```bash
cp .env.example .env
```

Then edit `.env` and set your actual password:

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=campus_chat
DB_USER=campus_user
DB_PASSWORD=your_secure_password_here
```

Alternatively, export them in your shell:

```bash
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=campus_chat
export DB_USER=campus_user
export DB_PASSWORD='your_secure_password_here'
```

---

## 7. Install Python Dependencies

```bash
pip3 install psycopg2-binary python-dotenv
# Or install everything:
pip3 install -r requirements.txt
```

---

## 8. Run Inspection Mode (Read-Only)

This reads the SQLite schema and displays table info. It does **not** connect to PostgreSQL or modify anything.

```bash
python3 migrate_sqlite_to_postgres.py --inspect
```

Expected output includes detected tables, columns, types, primary keys, and row counts for all five tables.

---

## 9. Run Schema Creation

This connects to both SQLite (read-only) and PostgreSQL, then creates the five tables in PostgreSQL:

```bash
python3 migrate_sqlite_to_postgres.py --create-tables
```

Expected output:
```
SQLite connection: OK
PostgreSQL connection: OK
  ✓ faculty
  ✓ programs
  ✓ cutoffs
  ✓ locations
  ✓ placements
Day 1 database setup completed successfully.
```

---

## 10. Verify PostgreSQL Tables Using psql

```bash
# Connect to the database
psql -h localhost -U campus_user -d campus_chat

# List tables
\dt

# Check a specific table's schema
\d faculty
\d programs
\d cutoffs
\d locations
\d placements

# Verify row counts (should all be 0 — data migration is Day 2)
SELECT 'faculty' AS tbl, COUNT(*) FROM faculty
UNION ALL SELECT 'programs', COUNT(*) FROM programs
UNION ALL SELECT 'cutoffs', COUNT(*) FROM cutoffs
UNION ALL SELECT 'locations', COUNT(*) FROM locations
UNION ALL SELECT 'placements', COUNT(*) FROM placements;

# Exit psql
\q
```

Or use the migration script's verify mode:

```bash
python3 migrate_sqlite_to_postgres.py --verify
```

---

## 11. Errors / Issues

| Issue | Status |
|-------|--------|
| No `requirements.txt` existed | Created one with existing + new dependencies |
| `placements` table has 0 rows in SQLite | Expected — schema was created correctly |
| PostgreSQL `--create-tables` and `--verify` require a running PostgreSQL instance with `campus_user`/`campus_chat` configured | User must run sudo commands from Sections 4–5 first |

---

## What's Next

| Day | Task |
|-----|------|
| **Day 2** | Migrate actual data from SQLite → PostgreSQL |
| **Day 3** | Switch the Flask backend to use PostgreSQL |
