// List view interactivity: type/genre filtering, sorting, and live header counts.
// Works on the server-rendered rows; state survives HTMX poll re-renders.
(function () {
  const state = {
    type: "all",
    genre: "",
    sortKey: "title",
    dir: "asc",
    hideSeen: false,
  };

  const room = () => document.getElementById("room");

  // Push current state onto freshly-rendered controls (after an HTMX swap).
  function applyState() {
    const r = room();
    if (!r) return;
    r.dataset.filter = state.type;
    const g = r.querySelector(".genre-filter");
    if (g) {
      if (state.genre && ![...g.options].some((o) => o.value === state.genre))
        state.genre = "";
      g.value = state.genre;
    }
    const s = r.querySelector(".sort-key");
    if (s) {
      if (![...s.options].some((o) => o.value === state.sortKey))
        state.sortKey = "title";
      s.value = state.sortKey;
    }
    const d = r.querySelector(".sort-dir");
    if (d) {
      d.dataset.dir = state.dir;
      d.textContent = state.dir === "asc" ? "↑" : "↓";
    }
    const h = r.querySelector(".hide-seen");
    if (h) h.checked = state.hideSeen;
  }

  function cmp(a, b) {
    const mult = state.dir === "asc" ? 1 : -1;
    if (state.sortKey === "title") {
      return (
        mult * (a.dataset.title || "").localeCompare(b.dataset.title || "")
      );
    }
    let av = parseFloat(a.dataset[state.sortKey]);
    let bv = parseFloat(b.dataset[state.sortKey]);
    if (isNaN(av)) av = -Infinity;
    if (isNaN(bv)) bv = -Infinity;
    if (av === bv)
      return (a.dataset.title || "").localeCompare(b.dataset.title || "");
    return mult * (av - bv);
  }

  function applyView() {
    const r = room();
    if (!r) return;
    r.querySelectorAll(".list").forEach((list) => {
      const rows = [...list.children];
      let visible = 0;
      rows.forEach((row) => {
        const genres = (row.dataset.genres || "").split("|").filter(Boolean);
        const okType = state.type === "all" || row.dataset.type === state.type;
        const okGenre = !state.genre || genres.includes(state.genre);
        const okSeen = !state.hideSeen || row.dataset.seen !== "1";
        const show = okType && okGenre && okSeen;
        row.style.display = show ? "" : "none";
        if (show) visible++;
      });
      rows
        .filter((x) => x.style.display !== "none")
        .sort(cmp)
        .forEach((x) => list.appendChild(x));
      const head = list.previousElementSibling; // the <h2> for this list
      const count = head && head.querySelector(".count");
      if (count) count.textContent = visible;
    });
  }

  document.addEventListener("change", (e) => {
    if (!e.target.closest("#room")) return;
    if (e.target.classList.contains("genre-filter"))
      state.genre = e.target.value;
    else if (e.target.classList.contains("sort-key"))
      state.sortKey = e.target.value;
    else if (e.target.classList.contains("hide-seen"))
      state.hideSeen = e.target.checked;
    else return;
    applyView();
  });

  document.addEventListener("click", (e) => {
    const seg = e.target.closest(".seg-btn");
    if (seg && seg.closest("#room")) {
      state.type = seg.dataset.val;
      room().dataset.filter = state.type;
      applyView();
      return;
    }
    const dir = e.target.closest(".sort-dir");
    if (dir && dir.closest("#room")) {
      state.dir = state.dir === "asc" ? "desc" : "asc";
      dir.dataset.dir = state.dir;
      dir.textContent = state.dir === "asc" ? "↑" : "↓";
      applyView();
    }
  });

  // Copy the share link. Delegated so it survives HTMX re-renders.
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".copy-btn");
    if (!btn || !btn.closest("#room")) return;
    const input = btn.parentElement.querySelector(".share");
    if (!input || !navigator.clipboard) return;
    navigator.clipboard.writeText(input.value).then(() => {
      btn.classList.add("copied");
      btn.textContent = "Copied";
      clearTimeout(btn._t);
      btn._t = setTimeout(() => {
        btn.classList.remove("copied");
        btn.textContent = "Copy";
      }, 1600);
    });
  });

  // Re-apply whenever the room content is (re)rendered by HTMX.
  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.target && e.target.id === "room") {
      applyState();
      applyView();
    }
  });
})();
