# Football View Changelog

## v0.2.5 - Match Center & Live System Overhaul (2026-01-31)

### ⚽ New Match Center Page

**Complete Redesign**
- New dedicated Match Center page (`/match/{fixture_id}`) with premium dark UI
- Scoreboard header with team crests, score, and match status
- Team form indicators (last 5 results as W/D/L pips)
- Follow stars on team names to favorite teams

**Formation Display**
- Visual pitch representation with player positions
- Formation labels at top (home) and bottom (away) of pitch
- Player circles with jersey numbers
- Live player ratings with color-coded badges (green ≥7.5, yellow 6.5-7.4, red <6.5)
- Supports all common formations parsed dynamically from formation string

**Live Statistics**
- Real-time possession, shots, shots on target, corners, fouls
- Animated bar comparisons between teams
- Match momentum/pressure indicator using attacks data

**Events Timeline**
- Live events with minute markers
- Goal, card, substitution, VAR icons
- Player names and assist info
- Dynamically updates during live matches

**Head-to-Head Section**
- Win/draw/loss summary
- Last 5 meetings with scores

---

### 🔄 Tiered Live Polling System

**Smart Polling Rates**
- **Live matches**: 10 second intervals (aggressive)
- **Pre-match**: 60 second intervals (detect kickoff)
- **Post-match**: Polling stops after FT

**Auto State Transitions**
- Detects when match starts → switches to aggressive polling
- Detects when match ends → stops polling
- Updates UI elements (badge, timer) on state change

**Live Data Updates**
- Score and elapsed time
- Statistics bars (animated transitions)
- Events timeline (new events inserted at top)
- Player ratings (every 30 seconds to reduce API load)
- Momentum/attacks data
- xG when available (premium)

---

### ⭐ Favorites System

**localStorage Persistence**
- Favorites stored as JSON array with team id, name, logo
- Key: `matchday_favorites`

**Dashboard Integration**
- Favorites section appears at top of match list
- Matches with favorited teams extracted from league sections (no duplicates)
- Favorites section auto-expands when favorites have matches
- Collapsed with "0" count when no favorites playing

**Follow Buttons**
- Star icons on team names in Match Center
- Star icons in pre-match overlay team headers
- Star button in Team Hub header
- Click to toggle follow state

---

### 🏆 League Priority Sorting

**Top 5 Leagues First**
1. Premier League
2. Bundesliga
3. La Liga
4. Serie A
5. Ligue 1

All other leagues sorted by match count after Top 5.

---

### 📂 Collapsible League Sections

**Dashboard UX**
- League headers are now clickable cards
- Chevron arrow rotates on expand/collapse
- Match list hides when collapsed
- Favorites section starts collapsed (expands if matches exist)

---

### 🔮 Predicted XI → Official Lineup Transition

**Smart Lineup Detection**
- Pre-match API checks for official lineups first
- Falls back to predicted XI only if official not available
- Returns `lineups_type: "official"` or `"predicted"` flag
- Pre-match overlay shows "✓ Official Lineups" or "🔮 Predicted Lineups"

**Auto-Refresh on Lineup Release**
- Pre-match overlay polls when within 2 minutes of kickoff
- Detects when official lineups become available
- Refreshes pre-match data to show official lineup

**Pre-match → Match Center Redirect**
- Polls to detect when `state.is_live` becomes true
- Automatically redirects to Match Center when match starts

---

### 🐛 Bug Fixes

**API Pagination Fix**
- Sportmonks fixtures API was only returning 25 matches (first page)
- Now fetches all pages → 68 matches on a full matchday

**Formation Display Fix**
- Players were stacking vertically instead of in formation rows
- Added JavaScript to parse formation string and organize into proper rows
- Increased spacing between players

**Dashboard Scores**
- Fixed matches showing "-" instead of actual scores

---

### 📁 Files Modified

| File | Changes |
|------|---------|
| `app/main.py` | Version bump to v0.2.5, predicted XI fallback in match_center, official lineup detection in pre-match API, live endpoint enhancements |
| `app/sportmonks_client.py` | Pagination fix for fixtures, `lineups.details` include for ratings, rating extraction (type_id 118) |
| `app/templates/match-center.html` | **NEW** - Complete Match Center page with formations, stats, events, live polling |
| `app/templates/dashboard-v4.html` | Favorites system, league sorting, collapsible sections, pre-match polling, lineup type display |
| `app/templates/team-hub.html` | Follow button in header |

---

### 🔧 Technical Details

**New JavaScript (Match Center)**
```javascript
// Tiered Polling
const POLL_RATES = { LIVE: 10000, PRE_MATCH: 60000, POST_MATCH: 0 };
initPolling()          // Determine initial state
startPolling(rate)     // Start interval
stopPolling()          // Clear interval

// Live Updates
fetchLiveUpdate()      // API call with rating flag
updateUI(data)         // Update all UI elements
updateStatistics(stats) // Update stat bars
updateEvents(events)   // Add new events to timeline
updatePlayerRatings(ratings) // Update rating badges

// Formation Layout
organizeFormation(teamElement) // Parse formation, create rows
```

**New JavaScript (Dashboard)**
```javascript
// Favorites
getFavorites() / setFavorites()
isFavorite(teamId)
toggleFavorite(id, name, logo)

// Pre-match Polling
startPreMatchPolling(matchId)  // 15s interval near kickoff
// Auto-redirects to Match Center when match starts
// Auto-refreshes when official lineups available
```

**API Enhancements**
- `/api/match/{id}/live` now returns:
  - `has_official_lineups` flag
  - `lineups` and `formations` when official available
  - `statistics` for live stat updates
  - `events` for timeline updates

---

## v0.2.4 - UI Enhancements and Stability (2026-01-31)

### ✨ Pre-Match View

**Full Pre-Match Overlay**
- New slide-up overlay for upcoming matches with smooth Apple-esque transitions
- Hero section with team crests, names, and recent form (W/D/L badges)
- Live countdown timer to kickoff
- Match info section (venue, referee, competition, round)

**Predicted XI Integration**
- Pitch visualization with formation-based player positioning
- Supports common formations: 4-3-3, 4-4-2, 3-5-2, 4-2-3-1, 3-4-3, 5-3-2, 5-4-1
- Players displayed with names on interactive pitch graphic
- Powered by the existing prediction engine

**Head-to-Head Stats**
- H2H record bar showing wins/draws distribution
- Counts wins by team_id regardless of home/away position
- Ignores matches with null scores

**Season Stats Comparison**
- Side-by-side stats for both teams (rank, points, W/D/L, goals)
- Data pulled from current standings

**Coming Soon Sections**
- Weather and "Where to Watch" placeholders for future features

---

### 🔄 Live Match System

**Real-Time Polling**
- Dashboard now polls every 30 seconds when live matches are active
- Smart polling - only activates when matches are live or starting within 5 minutes
- Pauses when browser tab is hidden (Visibility API)
- Resumes with immediate refresh when tab becomes visible

**Client-Side Timer**
- Match elapsed time updates every second for smooth UX
- Syncs with server data every 30 seconds
- Detects halftime/break states and pauses timer appropriately
- Caps at reasonable bounds (+5 for first half, +10 for second half)

---

### 🎯 Payload Contracts & API Stability

**View Models Architecture**
- New `MatchCardPayload` - stable contract for match cards on dashboard
- New `PreMatchPayload` - complete pre-match data structure
- New `H2HPayload.aggregate()` - proper H2H calculation by team_id
- New `SeasonStatsPayload` - standings data extraction
- `get_team_form()` helper for W/D/L form extraction
- `find_team_in_standings()` helper for stats lookup

**API Endpoints**
- `/api/dashboard` now returns `MatchCardPayload[]` with normalized structure
- `/api/pre-match/{match_id}` returns comprehensive pre-match data
- Both endpoints use stable payload contracts, shielding UI from API changes

---

### 🐛 Bug Fixes

**Predicted XI Engine**
- Fixed `'PredictedLineup' object has no attribute 'predicted_xi'` - now uses `starting_xi`
- Fixed `'PredictedPlayer' object has no attribute 'name'` - now uses `player_name`
- Fixed `'number'` attribute - now uses `squad_number`

**Coming Up Section**
- Clicking upcoming match now opens pre-match overlay directly (was navigating to date)
- No more double-click required to see match preview

**Dashboard Compatibility**
- UI now supports both old and new payload formats for backward compatibility
- `renderMatchRow` and `renderLiveSection` updated for new structure

---

### 📁 Files Modified

| File | Changes |
|------|---------|
| `app/main.py` | Version bump to v0.2.4, fixed predicted XI attributes, added MatchCardPayload to dashboard |
| `app/view_models.py` | Added payload contracts (MatchCardPayload, H2HPayload, PreMatchPayload, etc.) |
| `app/templates/dashboard-v4.html` | Pre-match overlay, live polling, timer system, Coming Up fix |

---

### 🔧 Technical Details

**New JavaScript Functions**
```javascript
// Pre-Match Overlay
openPreMatch(matchId)      // Fetch and display pre-match view
closePreMatch()            // Dismiss overlay
renderPreMatch(data)       // Render pre-match content
renderPitchPlayers(lineup, side)  // Position players on pitch
startCountdown(kickoffDate)       // Live countdown timer

// Live Polling System
startLivePolling()         // Begin 30s API poll + 1s timer
stopLivePolling()          // Pause all polling
pollLiveUpdates()          // Fetch fresh data
syncLiveTimers(matches)    // Sync client timers with server
updateLiveTimerDisplays()  // Update DOM every second
getLiveDisplayTime(matchId) // Get interpolated elapsed time
```

**Formation Positioning**
```javascript
FORMATION_POSITIONS = {
    "4-3-3": { home: [...], away: [...] },
    "4-4-2": { ... },
    "3-5-2": { ... },
    // ... 7 formations supported
}
```

---

## v0.2.2 - Stability Update (2026-01-30)

### 🐛 Bug Fixes & Stability Improvements

**Dashboard Fixes**
- Fixed matches not displaying due to undefined `matchTime` variable in `renderMatchRow`
- Fixed "Today/Yesterday/Tomorrow" date labels now correctly reference simulated date (2026-01-30)
- Fixed match IDs not passing correctly (was sending `fixture_id=0`) - now uses `match.id`
- Dashboard now defaults to "Today" (2026-01-30) on load

**Season Configuration**
- Fixed `current_season` computation - now correctly returns 2025 for Jan-Jul months (football seasons run Aug-May)
- Centralized season logic in `config/settings.py` with `_compute_current_season()` function

**Search System Consolidation** (merged from Codex branch)
- Unified alias systems - deprecated `app/aliases.json` in favor of `data/aliases.json` via `AliasDatabase`
- Removed hardcoded Premier League defaults (`league_id=39`) throughout codebase
- New `/api/config` endpoint provides dynamic league list and current season to frontend
- `search_utils.py` now wraps modern `AliasDatabase` with deprecation warnings

**New API Endpoint**
- Added `/api/predicted-xi` endpoint for fetching predicted lineups
  - Accepts `fixture_id`, `home_team_id`, `away_team_id` parameters
  - Returns formation, players with positions, confidence scores
  - Parallel fetching for home/away teams

**Frontend Improvements**
- Dynamic league list loaded from `/api/config` instead of hardcoded
- Match detail panel now passes team IDs for predicted lineup fetching

---

## v0.2.2 - Multi-League & Major UX Update (2026-01-29)

**Most comprehensive update so far.** Complete multi-league support, major UX architecture update, and dozens of fixes across the entire stack.

---

### 🌍 Multi-League Support

Football View now supports all Top 5 European leagues plus Champions League:

| League | Country | ID |
|--------|---------|-----|
| Premier League | England | 39 |
| La Liga | Spain | 140 |
| Bundesliga | Germany | 78 |
| Serie A | Italy | 135 |
| Ligue 1 | France | 61 |
| Champions League | Europe | 2 |

**What's New:**
- Dashboard now shows matches from ALL supported leagues grouped by competition
- League selector in sidebar with league-specific standings and top scorers
- Cross-league team comparisons ("Bayern vs Barcelona" works!)
- Team cards now show league affiliation
- `aliases.json` updated with `league_id` for all major teams:
  - Bayern Munich → Bundesliga (78)
  - Barcelona, Real Madrid, Atletico Madrid → La Liga (140)
  - Inter Milan, Juventus, AC Milan, Napoli → Serie A (135)
  - PSG, Monaco, Lyon, Marseille → Ligue 1 (61)

---

### ✨ Major UX Architecture Update

**Core Philosophy: "Spatial Continuity"**
> Users stay in place while data comes to them.

**Detail Panel System**
- New slide-in panel from right (480px width)
- Replaces all hard page redirects
- Smooth cubic-bezier animations
- Semi-transparent overlay with click-to-close
- ESC key to dismiss
- Content types supported:
  - Team details with standings, fixtures, top players
  - Player cards with season stats
  - Match facts with H2H and predicted lineups
  - Standings tables
  - Team/player comparisons

**Search UX Overhaul**
- **Enter key now immediately resolves** - no second search step required
- `searchAndResolve()` function for instant results
- Debounced typing (300ms) for suggestions
- Results open directly in detail panel
- Search dropdown closes on outside click

**In-Context Navigation**
- "Back" = collapse/close, never browser back
- All drill-downs happen in place
- Progressive disclosure without context loss
- Click standings row → team detail in panel
- Click scorer → player detail in panel
- Click match → match facts in panel

---

### 🏆 Enhanced Competitions Page

Complete redesign of the "All Competitions" tab:

**Per-League Cards**
- Each league displayed as an expandable card
- **Top 5 Teams** section (expandable)
  - Team position, logo, name, points
  - Click to open team detail panel
- **Top 5 Scorers** section (expandable)
  - Gold/silver/bronze rank badges
  - Player name, team, goal count
  - Click to search and show player

**Global Top 20 Scorers**
- Consolidated section at bottom of page
- Aggregates top scorers across ALL 5 domestic leagues
- Shows player, team, league, and goals
- Beautiful card grid layout
- Click any player to see full details

**Visual Design**
- Gradient headers for league cards
- Smooth expand/collapse animations
- Hover effects with subtle transforms
- Loading spinner while fetching data

---

### ⚽ Match Facts Restoration

Fixed regression where match clicking stopped working:

**Match Detail Panel**
- Click any match → opens detail panel (not modal)
- Shows: teams, score, status, competition
- **H2H Section**: Last 5 head-to-head results (async loaded)
- **Predicted Lineups Section**: Formation and starting XI (async loaded)
- Works for live, upcoming, and finished matches

**Match Row Improvements**
- `showMatchDetail()` completely rewritten for panel system
- `showMatchDetailById()` for fixture ID lookups
- `loadMatchExtras()` for async H2H/lineup loading
- Competition name passed through for display

---

### 🔧 Search Pipeline Fixes

**Bruno Fernandes / J. Gomez Disambiguation**
- Removed incorrect aliases from Bruno Fernandes (ID 284)
- Was incorrectly matching "gomez", "j gomez", "j. gomez"
- Fixed team_id to 33 (Manchester United)
- Searching "Bruno" now correctly returns Bruno Fernandes

**Cross-League Team Lookup**
- `_execute_team_lookup()` now determines team's actual league
- Fetches standings from correct league (not just Premier League)
- Returns `league_id` and `league_name` in response

**Cross-League Comparisons**
- `_execute_comparison()` supports teams from different leagues
- "Inter vs PSG" fetches from Serie A and Ligue 1 respectively
- Returns `cross_league: true` flag for UI indication

**Response Formatting**
- `TeamCardPayload` now includes `league_name` and `league_id`
- `_format_team_lookup()` passes league info to frontend
- Multi-league search suggestions in pipeline

---

### 🎨 Dashboard Improvements

**Sidebar Stats Panel**
- Fixed duplicate "Top Scorers" sections
- "View Full Table" → opens standings in detail panel (not search redirect)
- "View All Scorers" → opens scorers in detail panel
- Proper toggle between Standings/Scorers tabs

**League Leaders View**
- When "All Leagues" selected, shows 1st place from each league
- Combined Top 10 scorers across Europe
- League name badges on scorer rows

**CSS Additions (300+ lines)**
- `.detail-panel-*` - Complete panel system styling
- `.competition-league-*` - League card components
- `.competition-section-*` - Expandable sections
- `.global-scorer-*` - Top 20 grid cards
- `.loading-state` / `.loading-spinner` - Loading states
- Gradient rank badges (gold/silver/bronze)
- Hover transforms and transitions

---

### 📁 Files Modified

| File | Changes |
|------|---------|
| `app/main.py` | Version bump to v0.2.2 |
| `app/templates/dashboard.html` | **MAJOR** - 1000+ lines added: detail panel system, search rewrite, competitions view, match facts, CSS |
| `app/utils/search/executor.py` | Multi-league team lookup, cross-league comparisons |
| `app/utils/search/formatter.py` | League info in TeamCardPayload |
| `app/utils/search/pipeline.py` | Multi-league suggestions |
| `app/utils/search/resolver.py` | League name mapping |
| `app/utils/search/models/responses.py` | Added league_name, league_id to TeamCardPayload |
| `data/aliases.json` | Fixed Bruno aliases, added league_id to 30+ teams |
| `CHANGELOG.md` | This changelog |

---

### 🧪 Technical Details

**New JavaScript Functions**
```javascript
// Detail Panel System
openDetailPanel(title, icon, content)
closeDetailPanel()

// Search System
performSearch(query, autoResolve = false)
searchAndResolve(query)  // Enter key handler
showDetailForSearchResult(data, type)

// Panel Content Renderers
showTeamInPanel(data)
showPlayerInPanel(data)
showComparisonInPanel(data)
showStandingsInPanel(query)
showMatchInPanel(data)

// Match Details
showMatchDetail(matchId, homeName, awayName, ...)
showMatchDetailById(fixtureId)
loadMatchExtras(matchId, homeName, awayName)

// Competitions View
renderCompetitionsView()  // async, fetches all leagues
renderGlobalTopScorers()  // async, aggregates scorers
toggleCompetitionSection(headerElement)
showTeamDetail(teamName, leagueId)
```

**CSS Variables Used**
- `--bg-secondary`, `--bg-tertiary`, `--bg-hover`
- `--text-primary`, `--text-secondary`
- `--accent-blue`, `--accent-green`
- `--border-color`, `--radius-md`, `--radius-lg`

**Animation Timings**
- Panel slide: 0.3s cubic-bezier(0.4, 0, 0.2, 1)
- Overlay fade: 0.3s ease
- Section expand: 0.3s ease
- Hover transforms: 0.15s - 0.2s

---

### 🔮 Coming in v0.3.0

- Favourites system (star teams/players)
- Push notifications for goals
- Historical stats and trends
- Player comparison improvements
- Mobile responsive optimizations

---

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
