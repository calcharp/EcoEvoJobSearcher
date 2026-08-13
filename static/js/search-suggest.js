(function () {
  const list = document.createElement("ul");
  list.id = "search-suggest";
  list.className = "search-suggest";
  list.setAttribute("role", "listbox");
  list.hidden = true;
  document.body.appendChild(list);

  let input = null;
  let terms = [];
  let aliases = {};
  let items = [];
  let active = -1;
  let timer = null;
  let pickedWithKeys = false;

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function norm(s) {
    return String(s || "")
      .toLowerCase()
      .replace(/\./g, "")
      .replace(/-/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function editDistance(a, b) {
    const s = String(a || "");
    const t = String(b || "");
    if (s === t) return 0;
    if (!s.length) return t.length;
    if (!t.length) return s.length;
    if (Math.abs(s.length - t.length) > 3) return 99;
    const rows = s.length + 1;
    const cols = t.length + 1;
    const d = Array.from({ length: rows }, () => new Array(cols));
    for (let i = 0; i < rows; i++) d[i][0] = i;
    for (let j = 0; j < cols; j++) d[0][j] = j;
    for (let i = 1; i < rows; i++) {
      for (let j = 1; j < cols; j++) {
        const cost = s[i - 1] === t[j - 1] ? 0 : 1;
        d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost);
      }
    }
    return d[s.length][t.length];
  }

  function expand(value) {
    const q = norm(value);
    if (!q) return [];
    const out = [];
    const seen = new Set();
    const add = (s) => {
      const n = norm(s);
      if (!n || seen.has(n)) return;
      seen.add(n);
      out.push(s);
    };
    add(value);

    // Short aliases (evo, ai, gis, …) expand to their cluster.
    // Full phrases do not — on an eco/evo board, peer "related" terms are too broad.
    const aliasTarget = aliases[q];
    if (aliasTarget) {
      const hit = terms.find((t) => t.key === aliasTarget || t.key === q);
      if (hit) {
        add(hit.term);
        (hit.related || []).forEach(add);
      } else {
        add(aliasTarget);
      }
      return out;
    }

    // Exact known term: only pull near-duplicates / spelling variants from related.
    const hit = terms.find((t) => t.key === q);
    if (hit) {
      add(hit.term);
      (hit.related || []).forEach((r) => {
        const rn = norm(r);
        if (!rn || rn === q) return;
        if (rn.includes(q) || q.includes(rn) || editDistance(rn, q) <= 2) add(r);
      });
    }
    return out;
  }

  function hide() {
    items = [];
    active = -1;
    pickedWithKeys = false;
    list.hidden = true;
    list.innerHTML = "";
    if (input) {
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }
  }

  function placeList() {
    if (!input || list.hidden) return;
    const r = input.getBoundingClientRect();
    list.style.left = `${Math.max(8, r.left)}px`;
    list.style.top = `${r.bottom + 4}px`;
    list.style.width = `${Math.max(r.width, 220)}px`;
  }

  function paint() {
    list.innerHTML = "";
    if (!items.length || !input) {
      hide();
      return;
    }
    items.forEach((item, idx) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.id = `search-suggest-${idx}`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "search-suggest-item" + (idx === active ? " is-active" : "");
      const hint = item.why === "related" ? `<span class="search-suggest-why">related</span>` : "";
      const count = item.count ? `<span class="search-suggest-count">${item.count}</span>` : "";
      btn.innerHTML = `
        <span class="search-suggest-main">
          <span class="search-suggest-term">${esc(item.term)}</span>
          ${hint}
        </span>
        ${count}`;
      btn.addEventListener("mousedown", (e) => {
        e.preventDefault();
        choose(idx);
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    if (active >= 0) input.setAttribute("aria-activedescendant", `search-suggest-${active}`);
    else input.removeAttribute("aria-activedescendant");
    placeList();
  }

  function otherPhrases() {
    const stack = window.JobBoardsFilters?.getStack() || [];
    const currentId = input?.closest(".clause-row")?.dataset.clauseId;
    return new Set(
      stack
        .filter((f) => f.type === "clause" && f.id !== currentId)
        .map((f) => norm(f.phrase || f.value || f.label))
        .filter(Boolean)
    );
  }

  function applyPhrase(value) {
    if (!input) return;
    const val = String(value || "").trim();
    input.value = val;
    const row = input.closest(".clause-row");
    if (row && window.JobBoardsFilters) {
      JobBoardsFilters.updateClause(row.dataset.clauseId, { phrase: val });
    }
  }

  function choose(idx) {
    const item = items[idx];
    if (!item) return;
    applyPhrase(item.term);
    hide();
  }

  function scoreTerm(term, q) {
    const key = term.key;
    const label = norm(term.term);
    if (!q) return 0;
    if (key === q || label === q) return 240;
    if (key.startsWith(q) || label.startsWith(q)) return 140;
    if (key.includes(q) || label.includes(q)) return 90;
    const dist = Math.min(editDistance(key, q), editDistance(label, q));
    if (dist === 1) return 80;
    if (dist === 2 && q.length >= 4) return 55;
    if (key.split(" ").some((w) => w.startsWith(q) || editDistance(w, q) <= 1)) return 50;
    return 0;
  }

  function refresh() {
    if (!input) return;
    const raw = input.value.trim();
    const q = norm(raw);
    if (q.length < 1) {
      hide();
      return;
    }
    const aliasTarget = aliases[q];
    const ranked = [];
    const seen = new Set();
    terms.forEach((t) => {
      let score = scoreTerm(t, q);
      if (aliasTarget && t.key === aliasTarget) score = Math.max(score, 230);
      if (score <= 0) return;
      seen.add(t.key);
      ranked.push({ ...t, score, why: aliasTarget && t.key === aliasTarget ? "related" : "match" });
    });
    ranked.sort((a, b) => b.score - a.score || b.count - a.count);
    const top = ranked.slice(0, 8);
    top.forEach((hit) => {
      (hit.related || []).forEach((rel) => {
        const key = norm(rel);
        if (!key || seen.has(key)) return;
        const src = terms.find((t) => t.key === key);
        seen.add(key);
        ranked.push({
          term: rel,
          key,
          count: src ? src.count : 0,
          related: src ? src.related : [],
          score: Math.max(40, hit.score - 80),
          why: "related",
        });
      });
    });
    ranked.sort((a, b) => b.score - a.score || b.count - a.count);
    const used = otherPhrases();
    items = ranked.filter((item) => !used.has(norm(item.term))).slice(0, 10);
    active = -1;
    pickedWithKeys = false;
    paint();
  }

  function consumeEnter(e) {
    if (pickedWithKeys && !list.hidden && items.length && active >= 0) {
      e.preventDefault();
      choose(active);
      return true;
    }
    return false;
  }

  function bind(next) {
    if (input === next) return;
    hide();
    input = next;
    if (!input) return;
    input.setAttribute("autocomplete", "off");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-controls", "search-suggest");
    input.setAttribute("aria-expanded", "false");
  }

  document.addEventListener("focusin", (e) => {
    const next = e.target.closest?.(".clause-phrase");
    if (next) bind(next);
  });
  document.addEventListener("input", (e) => {
    if (!e.target.classList?.contains("clause-phrase")) return;
    bind(e.target);
    pickedWithKeys = false;
    clearTimeout(timer);
    timer = setTimeout(refresh, 80);
  });
  document.addEventListener("focusout", (e) => {
    if (!e.target.classList?.contains("clause-phrase")) return;
    setTimeout(() => {
      if (document.activeElement !== input) hide();
    }, 140);
  });
  document.addEventListener("keydown", (e) => {
    if (!e.target.classList?.contains("clause-phrase")) return;
    bind(e.target);
    const open = !list.hidden && items.length;
    if (e.key === "ArrowDown" && open) {
      e.preventDefault();
      pickedWithKeys = true;
      active = active < 0 ? 0 : (active + 1) % items.length;
      paint();
      return;
    }
    if (e.key === "ArrowUp" && open) {
      e.preventDefault();
      pickedWithKeys = true;
      active = active < 0 ? items.length - 1 : (active - 1 + items.length) % items.length;
      paint();
      return;
    }
    if (e.key === "Enter") {
      consumeEnter(e);
      return;
    }
    if (e.key === "Escape") hide();
  });
  window.addEventListener("scroll", hide, true);
  window.addEventListener("resize", hide);

  async function load() {
    try {
      const res = await fetch(JobBoardsDataUrl("search-suggest.json"), { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      terms = data.terms || [];
      aliases = data.aliases || {};
    } catch (_) {}
  }

  window.JobBoardsSearchSuggest = {
    expand,
    consumeEnter,
    ready: load(),
  };
})();
