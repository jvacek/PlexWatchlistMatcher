# Frontend design brief — Plex Watchlist Matcher

Handoff for a dedicated design pass. The app is **feature-complete** (M0–M4);
the current UI is functional but unstyled scaffolding. Your job is to make it
beautiful **without changing the structure or the functional hooks** the
backend and `app.js` depend on.

## Stack reality (don't fight it)
- Server-rendered **Jinja2 + HTMX**, not a SPA. Templates in `app/templates/`,
  styles/JS in `app/static/` (`app.css`, `app.js`). No build step — plain CSS
  and one vanilla-JS file.
- The body uses `hx-boost` so internal navigation swaps without full reloads.
  The **only** unavoidable full-page hops are the external redirects to
  `app.plex.tv` and back — those links carry `hx-boost="false"` (don't remove).
- Two regions **poll** via HTMX and have their innerHTML replaced. **Keep these
  container IDs and the elements `app.js` queries stable** (see "Functional
  hooks" below):
  - `#linking` in `linking.html` → polls `/auth/poll`, auto-advances on auth.
  - `#room` in `room.html` → polls `/room/{slug}/status` every 3s → renders
    `partials/status.html`, which `{% include %}`s `partials/row.html` per title.
  - A hidden `#sig` input echoes a state signature so an unchanged poll returns
    `204` and the DOM isn't torn down each tick (loaded posters stay put).
- Provide **loading skeletons** for the polled regions (`#linking`, and the
  room while watchlists fetch).

## Layout direction — LOCKED: rich rows
Results are an **information-dense vertical row list**, not a poster grid.
Decided deliberately (see commit "switch to rows"). Each row shows everything
without hover/interaction — closer to Letterboxd/Sonarr than a poster wall.
Make the rows *gorgeous and scannable*; do **not** convert them to a poster
grid. (The poster column can grow/shrink, but the row remains the unit.)

## Visual direction
- Media/cinema feel, **dark theme**, **mobile-first** (friends open the share
  link on phones — rows must collapse gracefully to narrow screens).
- Plex-adjacent but its own identity. The current accent is Plex amber
  (`#e5a00d`) on near-black (`#18181b`); you may evolve this.
- Deliver **design tokens** as CSS custom properties on `:root` (color,
  spacing, radius, type scale, shadow) so the system is reusable and themeable.

## Screens
1. **Landing** (`index.html`) — one strong "Start comparing" CTA → Plex login.
2. **Linking interstitial** (`linking.html`) — spinner/skeleton; auto-advances
   when auth completes. Currently just "Linking your Plex account…".
3. **Room lobby** (`partials/status.html`, top section) — prominent **share
   link + copy affordance** (currently a click-to-select `<input>`; a real copy
   button would be an improvement), a **participant list** with avatars and
   **status pills** (`pending` / `fetching` / `ready` / `error`), a per-member
   **retry** link on error, a "Join with Plex" CTA shown only to non-members,
   and a "share the link / waiting for 2+ people" hint.
4. **Results** (`partials/status.html`, lower section) — a **controls bar** then
   **three sections**, each a row list with a live count in its `<h2>`:
   - **Everyone wants** (strict intersection — the hero/payoff)
   - **Some of you want** (partial overlaps, ≥2 but not all)
   - **Just one person wants**
   Plus empty states ("Nothing is on everyone's watchlist yet").
5. **Waiting preview** — before 2+ people are `ready`, each ready member's own
   watchlist renders in the same row format ("{name}'s watchlist (N)") so the
   screen isn't empty while waiting.
6. **Error / expired room** (`state == "expired"`) — "Room not found", CTA to
   start a new comparison.

## Components to design
- **Row** (`partials/row.html`): poster (2:3) · title + year + type badge ·
  ratings line (critic ★, audience 👥, content rating, runtime, director) ·
  genre tags · truncated summary · a **side column** with the who-wants-it
  avatar stack + watch-status badges + "+ Watchlist" action.
- **Avatar stack** (`r.people`): per-person avatar ringed/badged by state —
  wants it, **watched** (✓, green ring), **in progress** (◐, amber ring),
  "watched but no longer on list" (dimmed). Plus a `count/total` label.
- **Status pill** (lobby): `pending` / `fetching` / `ready` / `error`.
- **Controls bar**: segmented **All / Movies / TV** filter, **genre** select,
  **sort** select (Name / Year / Critic rating / Audience rating / Most wanted),
  **sort-direction** toggle (↑/↓), and a **"hide items seen by anyone"**
  checkbox.
- **Copy-link button**, **skeleton loaders**, empty states.

## Functional hooks — DO NOT rename or restructure these
`app.js` does client-side filter/sort/count over the server-rendered rows and
must survive HTMX poll re-renders. It depends on:
- Container `#room` with `data-filter` attribute; hidden `#sig` input.
- `.seg-btn[data-val]`, `.genre-filter`, `.sort-key`, `.sort-dir[data-dir]`,
  `.hide-seen` in the controls bar (these are queried by class).
- Each list is a `.list` whose **immediately-preceding sibling is the `<h2>`**
  containing a `.count` span (the live count is written there).
- Each row is `.row` carrying `data-type`, `data-genres` (pipe-joined),
  `data-title`, `data-year`, `data-rating`, `data-audience`, `data-want`,
  `data-seen`. Rows are shown/hidden via `style.display` and reordered.
You may restyle these freely and add markup around them — just keep the class
names, the `<h2>.count` → `.list` adjacency, and the `data-*` attributes intact.
If you want to change a hook, flag it so the JS is updated in lockstep.

## Data the templates expose (per result `r`)
- `r.count`, `r.total`, `r.who` (set of participant ids), `r.seen_any`.
- `r.people[]`: `username`, `thumb`, `wants`, `watched`, `in_progress`.
- `r.item`: `title`, `year`, `type` (`movie`/`show`), `summary`, `thumb`,
  `genres[]`, `rating` (critic), `audience_rating`, `content_rating`,
  `duration` (ms), `director[]`, `rating_key`, `watched`, `in_progress`.
- Lobby `participants[]`: `plex_username`, `plex_thumb`, `status`, `id`.
- **Posters/avatars load through the proxy**: `/img?room={slug}&src={thumb}`
  (URL-encoded). Never hit Plex hosts directly from the browser — tokens stay
  server-side.

## Out of scope
No new features. The feature set is intentionally settling (only deploy/M5
remains). This pass is visual: tokens, type, spacing, color, the row and its
sub-components, skeletons, and responsive behavior down to phone widths.
