# VJTI Smart Campus Assistant

A VJTI campus assistant with a React/TypeScript frontend and a Flask backend. The frontend uses Vite, Tailwind CSS, and React Leaflet/OpenStreetMap. The backend connects to PostgreSQL, Ollama, ChromaDB, and Redis (with an in-memory session fallback when Redis is unavailable).

## Current functionality

- Chatbot for campus questions, with text and browser speech-to-text input.
- User authentication and role-aware access to administrator map tools.
- PostgreSQL-backed campus information and placement-data lookup. If verified placement statistics are unavailable, the chatbot links to the official [VJTI Training and Placement Office](https://vjti.ac.in/training-and-placement-office/) page.
- The sidebar's **Placements** item opens the official TPO page in a new tab and leaves the assistant open.
- Interactive campus map with search, source/destination selectors, campus boundary, location details, route reset, and administrator controls for saving verified building entrance pins.
- Chat navigation requests open the map and search or select known locations. Voice transcripts use the same chat flow.
- Known place names can be offered as unpinned directory entries. These are clearly marked as needing verification; they are not represented as building markers or used to fabricate directions.
- Walking routes use shortest-path search over the graph in `campus_pathways.json`. Only saved location pins connected to verified pathway geometry can be routed.

## Current map data limitations

- The map's campus reference and boundary come from OpenStreetMap way [112781811](https://www.openstreetmap.org/way/112781811). Its reference point represents the campus feature, not a building entrance.
- Additional directory names (for example, Main Gate, Central Library, Canteen, EXTC, and TPO) help with search and chatbot recognition, but their individual pins are not yet verified.
- Exact internal building entrances, including the physical TPO office location, still need confirmation and administrator entry on the map.
- `campus_pathways.json` currently has empty `nodes`, `edges`, and `location_access` sections. Walking routes therefore remain unavailable until verified paths and location-to-path connections are added. The application does not draw a straight-line substitute.
- The SQLite `locations` seed data contains coordinates that have not been verified. It is not automatically used as authoritative map data.

## Requirements

- Node.js and npm.
- Python 3.10+ (Python 3.12 has been used for local development).
- PostgreSQL with the `campus_chat` database and credentials configured.
- Ollama installed and running, with the `llama3.2:1b` and `llama3` models available.
- Redis is optional for session persistence; without it, sessions use an in-memory fallback and are not persistent across backend restarts.

## Configure the backend

In PowerShell, from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with your PostgreSQL password, a private Flask `SECRET_KEY`, and any non-default database or Redis settings. Do not commit `.env` or share its credentials.

The migration utility can create the PostgreSQL schema and migrate the existing SQLite data when required:

```powershell
python migrate_sqlite_to_postgres.py --inspect
python migrate_sqlite_to_postgres.py --create-tables
python migrate_sqlite_to_postgres.py --migrate
python migrate_sqlite_to_postgres.py --verify
```

Do not run the migration unless you intend to initialize/update the PostgreSQL data. `setup.py` creates and reseeds the local SQLite database; it does not initialize PostgreSQL.

The Hugging Face embedding stack may probe for TensorFlow on some installations. To avoid the Transformers TensorFlow/Keras import path, set `USE_TF=0` in the same terminal before starting Flask:

```powershell
$env:USE_TF = "0"
python backend_api_original.py
```

In Command Prompt, use `set USE_TF=0` instead of the PowerShell `$env:` command.

The API runs at `http://127.0.0.1:5000`. Its health endpoint is `http://127.0.0.1:5000/api/health`.

## Run the frontend

Open a second terminal at the repository root:

```powershell
npm install
npm run dev
```

Open the Vite URL printed in the terminal (normally `http://localhost:8080`). Sign in to use authenticated chat and map features.

## Build and checks

```powershell
npm run build
npx eslint src/components/campus/CampusMapPanel.tsx
python -m py_compile backend_api_original.py
git diff --check
```

The full-project ESLint command is `npm run lint`; it may also report pre-existing issues in unrelated components.

## Verify campus locations

1. Sign in with an administrator account.
2. Open **Campus Map** and search for a known place, such as `TPO` or `Central Library`.
3. Select **Verify map pin**, choose the confirmed building entrance on the map, provide a verification source (such as an OSM URL or campus survey), and confirm it is verified.
4. Save the location. Verified pins are stored in PostgreSQL and become selectable map markers.
5. Add verified pathway nodes, edges, and location access mappings to `campus_pathways.json` before expecting walking directions. Each edge's ordered coordinate list must follow an actual walkable path.

The chatbot recognizes text and voice requests such as “Where is TPO?”, “Show me the library,” and “How do I reach the canteen from the library?”. If a destination or pathway is not verified, it explains the limitation rather than inventing a pin or route.

## Week 4: Document Ingestion, Predictive Prefetching & Administration

Week 4 introduces an automated enterprise RAG document lifecycle, predictive prefetching intelligence, website crawling, and role-based administration:

### 1. Key Capabilities
- **Automated PDF Ingestion Pipeline** (`document_ingestion.py`):
  - Ingestion via PyMuPDF (`fitz`), text chunking (`RecursiveCharacterTextSplitter`), and embedding generation (`all-MiniLM-L6-v2`).
  - Automatic deduplication via SHA-256 file hashing.
  - Storage in ChromaDB vector database and relational metadata in PostgreSQL (`documents`, `document_versions`, `document_chunks`, `document_ingestion_jobs`).
- **Dedicated Watchdog Worker** (`run_watchdog.py`, `watchdog_service.py`):
  - Monitors `documents/incoming/` using Python Watchdog.
  - Implements size-stability and file-lock verification before processing.
  - Automatically moves files through `documents/processing/` to `documents/processed/` (or `documents/failed/`).
  - Runs as a dedicated background worker to prevent duplicate threads in Flask web workers.
- **Predictive Prefetch Engine** (`prefetch_engine.py`):
  - Markov chain model trained on user query transitions (`query_transitions`).
  - Predicts likely follow-up queries when transition probability exceeds confidence threshold (`PREFETCH_CONFIDENCE_THRESHOLD=0.40`).
  - Pre-warms CacheMind semantic cache in the background using the secure RAG pipeline (`pdf_search()`).
  - Enforces per-minute prefetch budget (`PREFETCH_BUDGET_PER_MINUTE=20`) and prevents session or role privilege bleed.
- **VJTI Website Periodic Sync** (`sync_service.py`):
  - Periodically checks configured official VJTI web pages (notices, circulars, syllabi, admissions) using APScheduler.
  - Strict security with domain allowlist (`vjti.ac.in`), SSRF prevention, and rate-limiting.
  - Detects new/updated PDFs by SHA-256 and triggers ingestion.
- **Admin Dashboard API** (`admin_api.py`):
  - RBAC protected endpoints (`/api/admin/*`) requiring `admin` role.
  - Endpoints for overview metrics, document listing/approval/archiving, prefetch telemetry, and manual sync triggers.
- **Database Migrations** (`migrate_week4.py`, `migrations_week4.sql`):
  - 9 relational tables: `documents`, `document_versions`, `document_chunks`, `document_ingestion_jobs`, `document_sync_sources`, `document_sync_history`, `document_audit_logs`, `query_transitions`, `prefetch_metrics`.

### 2. Week 4 Environment Variables
Configure the following in `.env`:
```ini
# Predictive Prefetching
PREFETCH_CONFIDENCE_THRESHOLD=0.40
PREFETCH_TTL=86400
PREFETCH_BUDGET_PER_MINUTE=20

# Website Synchronization
SYNC_INTERVAL_HOURS=6
SYNC_ENABLED=true

# Upload Limits
MAX_PDF_SIZE_MB=25
```

### 3. Running Week 4 Services

**Run the Database Migration:**
```powershell
python migrate_week4.py
```

**Run the Dedicated Ingestion Watchdog:**
```powershell
python run_watchdog.py
```
Drop any PDF into `documents/incoming/` to test automatic ingestion.

**Run the Comprehensive Week 4 Test Suite:**
```powershell
python test_week4.py
```

