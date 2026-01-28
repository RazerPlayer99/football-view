# Local Development Guide

> **Note:** This guide describes an earlier local database approach.
> The current implementation uses **live API-Football data** instead.
> See "Current Quickstart" below for the active setup.

---

## Current Quickstart (Live API Mode)

### Prerequisites
- Python 3.10+
- API-Football API key (set in `.env` as `API_FOOTBALL_KEY`)

### Setup & Run
```bash
# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate          # Windows PowerShell
# OR: .\venv\Scripts\activate.bat  # Windows CMD

# Install dependencies
pip install -r requirements.txt

# Run the server
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### Available UI Pages
| Route | Description |
|-------|-------------|
| `/ui/search` | Search teams & players (with nickname support) |
| `/ui/standings` | League standings table |
| `/ui/matches` | Match results with cards |
| `/ui/top-scorers` | Top scorers table |

### API Endpoints (JSON)
| Route | Description |
|-------|-------------|
| `/standings?season=2025` | League standings |
| `/matches?season=2025&limit=10` | Match results |
| `/teams?season=2025` | All teams |
| `/players/top-scorers?season=2025` | Top scorers |
| `/search?q=salah` | Search teams/players |

### Key Features
- **Human-friendly search**: "man utd", "salah", "cold palmer", "vvd" all work
- **Alias system**: `app/aliases.json` maps nicknames → canonical names
- **View models**: `app/view_models.py` prevents raw JSON in UI
- **In-memory caching**: 5 minute TTL for API responses

### Current Folder Structure
```
app/
├── main.py           # FastAPI routes + UI pages
├── api_client.py     # API-Football integration + caching
├── search_utils.py   # Text normalization, alias resolution
├── aliases.json      # Team/player nickname mappings
└── view_models.py    # TeamView, StandingRowView, MatchCardView, PlayerView
```

---

## Legacy Documentation (Local Database Approach)

*The following sections describe a local SQLite database approach that is no longer the primary implementation. Kept for reference.*

---

## PHASE 1: Setup and Run (Legacy)

### Step 1: Create Virtual Environment

Open your terminal (PowerShell or Command Prompt) in this folder and run:

```bash
python -m venv venv
```

This creates a folder called `venv` with an isolated Python environment.

### Step 2: Activate Virtual Environment

**On Windows (PowerShell):**
```bash
.\venv\Scripts\Activate.ps1
```

**On Windows (Command Prompt):**
```bash
.\venv\Scripts\activate.bat
```

You should see `(venv)` at the start of your command line.

### Step 3: Install Dependencies

```bash
pip install -r requirements-webapp.txt
```

This installs FastAPI, Uvicorn, Pytest, and other tools.

### Step 4: Run the Server

```bash
uvicorn app.main:app --reload
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

### Step 5: Test It Works

**In your browser, visit:**
- http://127.0.0.1:8000 - See the welcome page
- http://127.0.0.1:8000/health - See `{"status":"ok"}`
- http://127.0.0.1:8000/docs - See auto-generated API documentation

**Success looks like:**
- Welcome page loads with "Server is running!"
- /health shows `{"status":"ok"}`
- No errors in the terminal

### Step 6: Run Tests

Open a **new terminal** (keep the server running), activate venv again, then run:

```bash
pytest
```

You should see:
```
====== test session starts ======
tests\test_health.py ...                [100%]
====== 3 passed in 0.XX s ======
```

**All 3 tests should pass!**

---

## Commands Cheat Sheet

| Task | Command |
|------|---------|
| Activate venv (PowerShell) | `.\venv\Scripts\Activate.ps1` |
| Activate venv (CMD) | `.\venv\Scripts\activate.bat` |
| **Import CSV data to database** | `python scripts/import_data.py` |
| Run server | `uvicorn app.main:app --reload` |
| Run tests | `pytest` |
| Run tests with details | `pytest -v` |
| Run specific test file | `pytest tests/test_import.py -v` |
| Stop server | Press `CTRL+C` in terminal |
| Deactivate venv | `deactivate` |

---

## Troubleshooting

### "uvicorn: command not found"
- Make sure venv is activated (you should see `(venv)` in terminal)
- Try: `python -m uvicorn app.main:app --reload`

### "Scripts cannot be run on this system" (PowerShell)
- Run: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
- Or use Command Prompt instead

### Tests fail with "ModuleNotFoundError"
- Make sure venv is activated
- Reinstall: `pip install -r requirements-webapp.txt`

### Port already in use
- Stop other running servers
- Or use different port: `uvicorn app.main:app --reload --port 8001`

---

## PHASE 2: Database + Import Pipeline

Phase 2 imports your CSV data into a local SQLite database.

### What We Built:

**Database Structure:**
- `teams` - Team identities (Liverpool, Arsenal, etc.)
- `standings` - Team performance per season
- `matches` - Match results and statistics
- `players` - Player stats per season

See [DATA_CONTRACT.md](DATA_CONTRACT.md) for full details.

### Step 1: Run Import Script

With venv activated, run:

```bash
python scripts/import_data.py
```

**What it does:**
- Creates `football_view.db` SQLite database
- Scans all CSV files in `output/` folder
- Imports teams, standings, matches, and players
- Safe to run multiple times (updates existing data)

**Success looks like:**
```
============================================================
Football View - Data Import Script
============================================================

1. Initializing database...
   ✓ Database tables created

2. Found 7 CSV files in output/

3. Importing Standings:
  Importing standings for 2024-25...
    ✓ 20 new standings, 0 updated

4. Importing Matches:
  Importing matches for 2024-25...
    ✓ 380 new matches, 0 updated

5. Importing Players:
  Importing players for 2024-25...
    ✓ 500 new players, 0 updated

============================================================
IMPORT SUMMARY
============================================================
Teams:     20 total
Standings: 20 new, 0 updated
Matches:   380 new, 0 updated
Players:   500 new, 0 updated

✓ Import complete! Database ready at: football_view.db
============================================================
```

### Step 2: Verify Import with Tests

```bash
pytest tests/test_import.py -v
```

You should see tests pass and database statistics printed.

### Step 3: Check Database

You can inspect the database using:
- **SQLite Browser**: Download [DB Browser for SQLite](https://sqlitebrowser.org/)
- **Python**: Run `python` and try:

```python
from app.db import get_session
from app.models import Team, Standing

session = get_session()
teams = session.query(Team).all()
print(f"Teams: {len(teams)}")
for team in teams[:5]:
    print(f"  - {team.name}")
```

### Troubleshooting

**"No module named 'app'"**
- Make sure you're in the project root folder
- Run: `python -m scripts.import_data` instead

**"Output directory not found"**
- Check that `output/` folder exists with CSV files
- Verify CSV files have correct naming (e.g., `standings_2024-25_*.csv`)

**Import runs but 0 rows imported**
- Check CSV column names match expected format
- Look for error messages in import output

---

## Questions?

If something isn't working, tell your pair-programmer:
1. What command you ran
2. What error you see
3. What step you're on
