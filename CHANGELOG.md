# Football View Changelog

## v0.2.0 - Search UI Overhaul (2026-01-28)

### New Features

**Autocomplete Search**
- Real-time dropdown suggestions as you type
- Shows player photos, team names, and entity type badges
- Keyboard navigation (arrow keys, Enter to select, Escape to close)
- 200ms debounce for performance
- New `/api/search/suggest` endpoint

**Fuzzy Name Matching**
- Integrated python-Levenshtein for better typo handling
- Last-name matching: "sesko" → "Benjamin Šeško"
- First-name matching: "mohamed" → "Mohamed Salah"
- Partial containment matching: "haal" → "Erling Haaland"
- Dynamic thresholds based on query length (shorter = more lenient)

**Comparison Feature**
- "salah vs haaland" now shows side-by-side stats
- Fixed disambiguation not triggering for comparison queries
- Added simple "X vs Y" pattern matching

### Bug Fixes

**Search Results Display**
- Top Scorers table now shows player names and team names (was showing empty columns)
- Player card stats now display actual goals/assists (was showing 0)
- Player card now shows team name (was showing just "|")
- Fixed data structure mismatch in `formatter.py` - stats are in `season_totals`, not top-level

**LLM Search Integration**
- Fixed `ANTHROPIC_API_KEY` not loading from `.env` (added `override=True` to `load_dotenv()`)
- Search UI now calls `/api/search` (unified pipeline) instead of `/search` (basic)

**UI Fixes**
- Search bar maintains full width with autocomplete wrapper
- Comparison metrics highlight winner correctly

### Technical Changes

**Files Modified**
- `app/main.py` - Rewrote search UI, added `/api/search/suggest` endpoint, autocomplete JS/CSS
- `app/utils/search/entities.py` - Added Levenshtein, last-name matching, dynamic thresholds
- `app/utils/search/formatter.py` - Fixed data extraction for top scorers, player cards, comparisons
- `app/utils/search/resolver.py` - Skip disambiguation for COMPARISON intent
- `app/utils/search/patterns.py` - Added simple "X vs Y" comparison patterns
- `app/utils/search/llm/__init__.py` - Fixed env loading with `override=True`

**New Dependencies**
- `python-Levenshtein` - For improved fuzzy string matching

### Search Pipeline Flow
```
User types "sesko"
    ↓
Autocomplete: /api/search/suggest?q=sesko
    ↓
fuzzy_match() checks:
  1. Exact match? No
  2. Last name match? "sesko" == "šeško" (normalized) → 0.95 confidence
  3. Levenshtein + SequenceMatcher ratio
    ↓
Returns: [{"name": "B. Šeško", "type": "player", "team": "Manchester United"}]
    ↓
User selects or presses Enter
    ↓
Full search: /api/search?q=B. Šeško
    ↓
Player card with stats displayed
```

---

## v0.1.0 - Initial Release

- Basic search functionality
- Team and player lookups
- Standings and top scorers tables
- Match center with live updates
- LLM fallback for intent classification
