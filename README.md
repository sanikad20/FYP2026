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
