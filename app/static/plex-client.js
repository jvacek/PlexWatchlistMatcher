// Browser-side Plex client. The Plex token is born here, lives only in this
// tab's sessionStorage, and is NEVER sent to our server — the browser does all
// Plex I/O directly (CORS-enabled) and POSTs back only the non-secret watchlist
// data. Security note: because the token is reachable from JS, any XSS would
// expose it. So: never write the token into the DOM, a URL, or an <img src>
// (posters are fetched and shown as blob: URLs), and never innerHTML a
// Plex-returned string.
(function () {
  "use strict";

  const APP = window.PLEX_APP || { product: "Plex Watchlist Matcher", version: "0.1.0" };
  const PLEX_TV = "https://plex.tv/api/v2";
  const AUTH_APP = "https://app.plex.tv/auth";
  const DISCOVER = "https://discover.provider.plex.tv";
  const METADATA = "https://metadata.provider.plex.tv";

  // --- tiny helpers ---------------------------------------------------------
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }
  const ss = window.sessionStorage;
  function clientId() {
    let cid = ss.getItem("client_id");
    if (!cid) {
      cid = uuid();
      ss.setItem("client_id", cid);
    }
    return cid;
  }
  function token() {
    return ss.getItem("token");
  }
  function headers(tok) {
    const h = {
      "X-Plex-Client-Identifier": clientId(),
      "X-Plex-Product": APP.product,
      "X-Plex-Version": APP.version,
      Accept: "application/json",
    };
    if (tok) h["X-Plex-Token"] = tok;
    return h;
  }
  const toInt = (v) => (v == null || v === "" || isNaN(+v) ? null : Math.trunc(+v));
  const toFloat = (v) => (v == null || v === "" || isNaN(+v) ? null : +v);
  const tags = (arr) => (arr || []).map((t) => t.tag).filter(Boolean);

  async function postJSON(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "same-origin",
    });
    if (!r.ok) throw new Error(`${url} -> ${r.status}`);
    return r.json();
  }

  // --- Plex API (all client-side, token in header only) ---------------------
  function normalize(m) {
    return {
      guid: m.guid,
      rating_key: m.ratingKey != null ? String(m.ratingKey) : null,
      title: m.title,
      type: m.type,
      year: toInt(m.year),
      thumb: m.thumb || m.art || null,
      rating: toFloat(m.rating),
      audience_rating: toFloat(m.audienceRating),
      content_rating: m.contentRating || null,
      duration: toInt(m.duration),
      studio: m.studio || null,
      tagline: m.tagline || null,
      genres: [],
      director: [],
      view_count: toInt(m.viewCount),
      view_offset: toInt(m.viewOffset),
    };
  }

  async function fetchWatchlist(tok) {
    const items = [];
    let start = 0;
    const page = 100; // Discover's max container size; larger 400s
    for (;;) {
      const url =
        `${DISCOVER}/library/sections/watchlist/all` +
        `?X-Plex-Container-Start=${start}&X-Plex-Container-Size=${page}`;
      const r = await fetch(url, { headers: headers(tok) });
      if (!r.ok) throw new Error(`watchlist ${r.status}`);
      const mc = (await r.json()).MediaContainer || {};
      const batch = mc.Metadata || [];
      items.push(...batch);
      const total = mc.totalSize != null ? mc.totalSize : mc.size != null ? mc.size : items.length;
      start += batch.length;
      if (!batch.length || start >= total) break;
    }
    return items.map(normalize);
  }

  // Batch per-item detail (genres/director/summary + user state). Plex caps the
  // multi-get response at 20 items, so chunk the keys. Returns {ratingKey: {...}}.
  async function fetchDetails(tok, ratingKeys) {
    const out = {};
    const keys = ratingKeys.filter(Boolean);
    for (let i = 0; i < keys.length; i += 20) {
      const chunk = keys.slice(i, i + 20);
      const url =
        `${DISCOVER}/library/metadata/${chunk.join(",")}?includeUserState=1`;
      let r;
      try {
        r = await fetch(url, { headers: headers(tok) });
      } catch {
        continue;
      }
      if (!r.ok) continue; // skip a bad batch rather than fail the whole fetch
      const meta = ((await r.json()).MediaContainer || {}).Metadata || [];
      for (const m of meta) {
        out[String(m.ratingKey)] = {
          summary: m.summary || null,
          genres: tags(m.Genre),
          director: tags(m.Director),
          view_count: toInt(m.viewCount),
          view_offset: toInt(m.viewOffset),
        };
      }
    }
    return out;
  }

  async function fetchUser(tok) {
    const r = await fetch(`${PLEX_TV}/user`, { headers: headers(tok) });
    if (!r.ok) throw new Error(`user ${r.status}`);
    const d = await r.json();
    return {
      uuid: d.uuid || String(d.id),
      username: d.username || d.title || "Plex user",
      thumb: d.thumb || null,
    };
  }

  // --- Auth (runs on /auth) -------------------------------------------------
  async function startAuth(role, room) {
    const r = await fetch(`${PLEX_TV}/pins?strong=true`, {
      method: "POST",
      headers: headers(),
    });
    const pin = await r.json();
    ss.setItem("pending", JSON.stringify({ pin_id: pin.id, role, room }));
    const q = new URLSearchParams({
      clientID: clientId(),
      code: pin.code,
      forwardUrl: location.origin + "/auth",
      "context[device][product]": APP.product,
    });
    location.href = `${AUTH_APP}#?${q.toString()}`;
  }

  function resumeAuth() {
    const pending = JSON.parse(ss.getItem("pending") || "null");
    if (!pending) return false;
    const tick = async () => {
      let d;
      try {
        const r = await fetch(`${PLEX_TV}/pins/${pending.pin_id}`, {
          headers: headers(),
        });
        d = await r.json();
      } catch {
        return; // transient; the interval will retry
      }
      if (!d || !d.authToken) return;
      clearInterval(timer);
      ss.setItem("token", d.authToken); // token born + stored here, this tab only
      ss.removeItem("pending");
      try {
        const user = await fetchUser(d.authToken);
        const reg = await postJSON("/participant", {
          plex_uuid: user.uuid,
          plex_username: user.username,
          plex_thumb: user.thumb,
          client_id: clientId(),
          role: pending.role,
          room: pending.room || null,
        });
        ss.setItem("pid:" + reg.slug, String(reg.participant_id));
        location.href = "/room/" + reg.slug;
      } catch (e) {
        const stage = document.getElementById("auth-flow");
        if (stage) stage.textContent = "Something went wrong linking your account. Please try again.";
      }
    };
    const timer = setInterval(tick, 2000);
    tick();
    return true;
  }

  function initAuth(stage) {
    // Returning from Plex (pending PIN present) → poll for the token. Fresh
    // visit → create a PIN and bounce to Plex to approve it.
    if (resumeAuth()) return;
    const role = stage.dataset.role || "host";
    const room = stage.dataset.room || "";
    startAuth(role, room).catch(() => {
      stage.textContent = "Couldn't reach Plex. Please try again.";
    });
  }

  // --- Room data flow (runs on /room/{slug}) --------------------------------
  const started = new Set(); // slugs whose fetch we've already kicked off this page-load
  const syncedKeys = new Set(); // rating_keys we've already queried watch-state for
  const watchStates = new Map(); // rating_key -> {view_count, view_offset} (accumulated)
  let wsInFlight = false;

  async function setStatus(slug, pid, status) {
    try {
      await postJSON(`/room/${slug}/participant/${pid}/status`, { status });
    } catch {
      /* best effort — the pill is cosmetic */
    }
  }

  async function runFetch(slug, pid, tok) {
    started.add(slug);
    await setStatus(slug, pid, "fetching");
    try {
      const items = await fetchWatchlist(tok);
      const keys = items.map((i) => i.rating_key).filter(Boolean);
      const details = await fetchDetails(tok, keys);
      for (const it of items) {
        const d = details[it.rating_key];
        if (d) {
          it.summary = d.summary;
          it.genres = d.genres;
          it.director = d.director;
          if (d.view_count != null) it.view_count = d.view_count;
          if (d.view_offset != null) it.view_offset = d.view_offset;
        }
      }
      await postJSON(`/room/${slug}/participant/${pid}/watchlist`, { items });
      // Remember we've loaded this room so a refresh / re-open of the tab does
      // NOT wipe and re-fetch the watchlist (upload replaces all rows). Survives
      // reloads, clears on tab close; retry clears it explicitly.
      ss.setItem("fetched:" + slug, "1");
    } catch (e) {
      await setStatus(slug, pid, "error");
      started.delete(slug); // allow a retry
    }
  }

  // Query Plex for this user's watch state on titles only others have on their
  // lists, so we can show "already seen by X". Only fetches keys not seen before;
  // posts the full accumulated set (the endpoint replaces prior rows).
  async function syncWatchState(slug, pid, tok) {
    if (wsInFlight) return;
    wsInFlight = true;
    try {
      const r = await fetch(`/room/${slug}/participant/${pid}/gap`, {
        credentials: "same-origin",
      });
      if (!r.ok) return;
      const gap = (await r.json()).rating_keys || [];
      const fresh = gap.filter((k) => !syncedKeys.has(k));
      if (!fresh.length) return;
      const details = await fetchDetails(tok, fresh);
      fresh.forEach((k) => syncedKeys.add(k));
      for (const [rk, d] of Object.entries(details)) {
        const vc = d.view_count || 0;
        const vo = d.view_offset || 0;
        if (vc > 0 || vo > 0) watchStates.set(rk, { view_count: vc, view_offset: vo });
      }
      const states = [...watchStates.entries()].map(([rating_key, v]) => ({
        rating_key,
        ...v,
      }));
      await postJSON(`/room/${slug}/participant/${pid}/watch-state`, { states });
    } catch {
      /* best effort */
    } finally {
      wsInFlight = false;
    }
  }

  function driveRoom() {
    const r = document.getElementById("room");
    if (!r) return;
    const slug = r.dataset.slug;
    const tok = token();
    const pid = ss.getItem("pid:" + slug);
    if (!slug || !tok || !pid) return; // not a logged-in member of this room
    // Fetch once per tab session. Without the sessionStorage guard, every page
    // (re)load would re-run runFetch, which replaces all watchlist rows — making
    // the list briefly vanish and reload on a simple refresh.
    if (!started.has(slug) && !ss.getItem("fetched:" + slug)) {
      runFetch(slug, parseInt(pid, 10), tok);
    }
    // Watch-state runs once our own upload exists and there are gap keys; the
    // gap grows as people join, so re-checking on each poll picks newcomers up.
    syncWatchState(slug, parseInt(pid, 10), tok);
  }

  // --- Posters: fetch with the token, show as blob URLs (token never in DOM) -
  const blobCache = new Map(); // src -> objectURL, reused across re-renders
  async function loadPosters(tok) {
    const imgs = document.querySelectorAll("img[data-poster-src]:not([data-loaded])");
    for (const img of imgs) {
      const src = img.dataset.posterSrc;
      img.dataset.loaded = "1";
      if (!src) continue;
      if (blobCache.has(src)) {
        img.src = blobCache.get(src);
        continue;
      }
      if (/^https?:\/\//.test(src)) {
        img.src = src; // absolute CDN art needs no token; let the browser load it
        continue;
      }
      if (!tok) continue; // metadata-path art needs a token we don't have (pre-join)
      try {
        const r = await fetch(METADATA + src, { headers: headers(tok) });
        if (!r.ok) continue;
        const url = URL.createObjectURL(await r.blob());
        blobCache.set(src, url);
        img.src = url;
      } catch {
        /* poster just won't show */
      }
    }
  }

  // --- Delegated UI: add-to-watchlist + retry -------------------------------
  document.addEventListener("click", (e) => {
    const add = e.target.closest(".add-btn");
    if (add && add.dataset.ratingKey) {
      e.preventDefault();
      const rk = add.dataset.ratingKey;
      const tok = token();
      if (!tok) return;
      fetch(`${DISCOVER}/actions/addToWatchlist?ratingKey=${encodeURIComponent(rk)}`, {
        method: "PUT",
        headers: headers(tok),
      })
        .then((r) => {
          add.outerHTML = r.ok
            ? '<span class="added">✓ On your watchlist</span>'
            : '<span class="add-failed">Couldn\'t add</span>';
        })
        .catch(() => {
          add.outerHTML = '<span class="add-failed">Couldn\'t add</span>';
        });
      return;
    }
    const retry = e.target.closest(".retry-btn");
    if (retry) {
      e.preventDefault();
      const r = document.getElementById("room");
      const slug = r && r.dataset.slug;
      const pid = retry.dataset.pid;
      const tok = token();
      if (slug && pid && tok) {
        started.delete(slug);
        ss.removeItem("fetched:" + slug); // explicit retry: allow a fresh fetch
        runFetch(slug, parseInt(pid, 10), tok);
      }
    }
  });

  // --- Boot -----------------------------------------------------------------
  function boot() {
    const stage = document.getElementById("auth-flow");
    if (stage) {
      initAuth(stage);
      return;
    }
    if (document.getElementById("room")) {
      loadPosters(token());
      driveRoom();
    }
  }

  // Re-hydrate after each HTMX status re-render (new rows/posters arrive).
  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.target && e.target.id === "room") {
      loadPosters(token());
      driveRoom();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
