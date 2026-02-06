# Team Dashboard UI Link Audit

Scope: `app/templates/team-hub.html` (route: `/team/{team_id}`).

## Confirmed dead-end links

1. **`/team/{{ team.id }}/squad` (`Full Squad →`)**
   - Rendered in the Squad Pulse section.
   - There is no server UI route for `/team/{team_id}/squad` in `app/main.py`; only `/api/team/{team_id}/squad` exists.
   - **Impact:** this CTA resolves to a 404 in the current app.

2. **`/standings/{{ league.id }}` (`Full Table →`)**
   - Rendered in the League Standing section.
   - There is no route matching `/standings/{league_id}`. Existing routes are `/standings` (JSON API) and `/ui/standings` (UI).
   - **Impact:** this CTA resolves to a 404 in the current app.

## Valid links currently in the Team Hub

- `/` (back button and Matches nav)
- `/search` (Search nav)
- `/team/{team_id}` (team links in next match and standings mini-table)
- `/match/{fixture_id}` (clicking recent match rows)

These all have matching server routes in `app/main.py`.

## Places that should likely be links but are currently static

> Player click-through is intentionally excluded per request.

1. **Recent Form header: `All Matches →`**
   - Currently rendered as plain text (`<span>`), not an anchor.
   - Should link to the team’s fixtures list (candidate target: `/ui/matches?team_id={{ team.id }}` or a future `/team/{{ team.id }}/fixtures`).

2. **Bottom-nav `News` item**
   - Rendered as a static `<div>` and appears tappable but has no destination.
   - Should either be disabled styling or linked when a news page exists.

3. **Bottom-nav `Following` item**
   - Rendered as a static `<div>` and appears tappable but has no destination.
   - Should link to a favorites/following page if available (or be visually disabled until implemented).

4. **Hero “more” (three dots) action button**
   - Interactive button styling, but no click handler or destination.
   - Should open an action sheet/menu or be removed until wired.

5. **League label in status bar**
   - Shows competition context but is not clickable.
   - Could link to league hub (`/league/{{ league.id }}`) for stronger navigation continuity.

6. **Venue (next match card) and club stadium (Club section)**
   - Presented as high-value entities but non-interactive.
   - Could be linked in future to match details/venue pages when those views are available.

## Suggested implementation order

1. **Fix broken links first (P0):**
   - Replace `/team/{{ team.id }}/squad` with a valid target (temporary fallback to API route is not ideal for UI).
   - Replace `/standings/{{ league.id }}` with `/league/{{ league.id }}` or `/ui/standings` depending on desired UX.

2. **Resolve deceptive taps (P1):**
   - Convert `News` + `Following` nav items and “more” button into either real actions or explicitly disabled non-tappable UI states.

3. **Improve discoverability (P2):**
   - Link `All Matches →` and league status context.

4. **Future enrichment (P3):**
   - Venue and stadium deep links once corresponding UI pages exist.
