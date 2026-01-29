# Football View Changelog

## v0.2.0 - Full Stabilization Sprint (2026-01-28)

Major release covering search overhaul, LLM integration, UI improvements, and crash prevention.

---

### Search System Overhaul

**Autocomplete Search**
- Real-time dropdown suggestions as you type
- Shows player photos, team names, and entity type badges (PLAYER/TEAM)
- Keyboard navigation (arrow keys, Enter to select, Escape to close)
- 200ms debounce for performance
- New `/api/search/suggest` endpoint for fast lookups

**Fuzzy Name Matching**
- Integrated `python-Levenshtein` for better typo handling
- Last-name matching: "sesko" → "Benjamin Šeško"
- First-name matching: "mohamed" → "Mohamed Salah"
- Partial containment matching: "haal" → "Erling Haaland"
- Dynamic thresholds based on query length (shorter queries = more lenient)

**Comparison Feature**
- "salah vs haaland" now shows side-by-side player stats
- "is Wirtz better than Haaland?" pattern matching
- Fixed disambiguation incorrectly triggering for comparison queries
- Winner highlighting on comparison metrics

**Search Results Display Fixes**
- Top Scorers table now shows player names and team names (was showing empty columns)
- Top Assists table - same fix applied
- Player card stats now display actual goals/assists (was showing 0)
- Player card now shows team name (was showing just "|")
- Fixed data structure mismatch - stats are in `season_totals`, not top-level

---

### LLM Integration

**Claude API Integration**
- Fixed `ANTHROPIC_API_KEY` not loading from `.env` (added `override=True` to `load_dotenv()`)
- LLM fallback for intent classification when pattern matching fails
- Search UI now calls `/api/search` (unified pipeline) instead of `/search` (basic endpoint)

**Intent Classification**
- Pattern-based matching for common queries (standings, top scorers, player lookups)
- LLM fallback for complex/ambiguous queries
- Intent types: STANDINGS, TOP_SCORERS, TOP_ASSISTS, PLAYER_LOOKUP, TEAM_LOOKUP, MATCH_LOOKUP, COMPARISON, SCHEDULE

---

### UI Improvements

**Search Page**
- Full-width search bar with autocomplete dropdown
- Search hints showing example queries
- LIVE badge indicator
- Responsive results rendering for all response types:
  - Tables (standings, top scorers)
  - Player cards with stats
  - Team cards with logo and info
  - Comparison view with side-by-side stats
  - Disambiguation options when multiple matches found
  - Error states with suggestions

**Response Types Supported**
- `table` - Sortable data tables
- `player_card` - Player info with season stats
- `team_card` - Team info with venue
- `comparison` - Side-by-side entity comparison
- `disambiguation` - "Which did you mean?" options
- `error` - Friendly error messages with suggestions

---

### Crash Prevention & Defensive Coding

**Null Safety**
- Added `safe_str()` and `safe_lower()` helper functions
- Protected `.lower()` calls on potentially None values
- Safe dictionary access with `.get()` defaults

**Files Hardened**
- `app/view_models.py` - Null checks on event properties
- `app/live_match/models.py` - Null checks on match properties
- `app/utils/search/normalizer.py` - Safe string operations
- `app/utils/search/entities.py` - Safe entity extraction

---

### Technical Details

**Files Modified**
| File | Changes |
|------|---------|
| `app/main.py` | Rewrote search UI, added `/api/search/suggest`, autocomplete JS/CSS |
| `app/utils/search/entities.py` | Levenshtein matching, last-name matching, dynamic thresholds |
| `app/utils/search/formatter.py` | Fixed top scorers, player cards, comparison data extraction |
| `app/utils/search/resolver.py` | Skip disambiguation for COMPARISON intent |
| `app/utils/search/patterns.py` | Added "X vs Y", "is X better than Y" patterns |
| `app/utils/search/llm/__init__.py` | Fixed env loading with `override=True` |
| `app/utils/search/pipeline.py` | Unified search pipeline improvements |
| `app/view_models.py` | Null safety, view model fixes |
| `app/live_match/models.py` | Null safety on match properties |
| `app/utils/helpers.py` | NEW - `safe_str()`, `safe_lower()` utilities |

**New Dependencies**
- `python-Levenshtein` - Improved fuzzy string matching

**API Endpoints**
- `GET/POST /api/search` - Unified search (all query types)
- `GET /api/search/suggest` - Autocomplete suggestions

---

### Search Pipeline Flow

```
User types "sesko"
    ↓
Autocomplete: /api/search/suggest?q=sesko
    ↓
fuzzy_match() checks:
  1. Exact alias match? No
  2. Last name match? "sesko" == "šeško" → 0.95 confidence
  3. Levenshtein + SequenceMatcher hybrid ratio
    ↓
Returns: [{"name": "B. Šeško", "type": "player", "team": "Arsenal"}]
    ↓
User selects from dropdown or presses Enter
    ↓
Full search: /api/search?q=sesko
    ↓
Intent classification → PLAYER_LOOKUP
    ↓
Entity resolution → Player ID 115589
    ↓
API fetch → get_player_by_id()
    ↓
Format response → PlayerCardPayload with season_totals
    ↓
Render player card with actual stats
```

---

## v0.1.0 - Initial Release

- Basic search functionality
- Team and player lookups
- Standings and top scorers tables
- Match center with live updates
- LLM fallback for intent classification
