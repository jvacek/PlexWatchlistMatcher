# Frontend design brief — Watchlist Compare

Handoff for a dedicated design pass. The current UI is deliberately unstyled
scaffolding that just proves the flow works.

## Stack reality (don't fight it)
- Server-rendered **Jinja2 + HTMX**, not a SPA framework. Templates live in
  `app/templates/`, CSS/JS in `app/static/`.
- The body uses `hx-boost` so internal navigation swaps without full reloads.
  The **only** unavoidable full-page hop is the external redirect to
  `app.plex.tv` and back (links to `/auth/login` carry `hx-boost="false"`).
- Two regions **poll** via HTMX and get their innerHTML replaced every few
  seconds. Keep these container IDs/structure stable:
  - `#linking` in `linking.html` (polls `/auth/poll`)
  - `#room` in `room.html` (polls `/room/{slug}/status` → renders
    `partials/status.html`, which includes `partials/card.html` per title)
- Provide **loading skeletons** for the polled regions.

## Screens
1. **Landing** (`index.html`) — one strong "Start comparing" CTA → Plex login.
2. **Linking interstitial** (`linking.html`) — spinner; auto-advances when auth
   completes.
3. **Room lobby** (`partials/status.html`) — prominent **share link + copy
   button**, **participant list** with **status pills**
   (`pending`/`fetching`/`ready`/`error`), a "Join with Plex" CTA shown only to
   non-members, and a "waiting for 2+ people" hint.
4. **Results** (same partial) — **"Everyone wants" hero** then a **"Some of you
   want" grid** of poster cards. Each card: poster (2:3), title, year, and a
   `count/total · who` line. Empty state when no overlap yet.
5. **Error / expired room** (same partial, `state == "expired"`).

## Visual direction
- Media/cinema feel, **dark theme**, **poster-forward**, **mobile-first**
  (friends open the share link on phones). Plex-adjacent but its own identity.
- Deliver **design tokens** as CSS custom properties (color, spacing, radius,
  type scale) so they're reusable.
- Components to design: poster card, avatar stack (use `Participant.plex_thumb`),
  status pill, copy-link button, segmented movie/show filter, skeleton loader.

## Data the templates expose
- `participants[]`: `plex_username`, `plex_thumb`, `status`.
- `results.intersection[]` / `results.partials[]`: each has `count`, `total`,
  `who_users[]`, and `item` (`title`, `year`, `type`, `summary`, `thumb`).
- Posters load through the proxy: `/img?room={slug}&src={item.thumb}` — never
  hit Plex hosts directly from the browser.

## Nice-to-haves (not yet built)
- Movie/show segmented filter (data has `item.type`).
- Avatar stack on each card for "who wants it".
- Sort/space the two result sections; show per-person counts in the lobby.
