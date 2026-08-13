(function () {
  let stack = [];
  let nextId = 1;
  const listeners = new Set();
  const SESSION_KEY = "jobboards-session-v3";
  const SOURCES = new Set(["ecoevojobs", "evoldir", "sciencecareers"]);

  function makeId() {
    return String(nextId++);
  }

  function parseBbox(raw) {
    if (!raw) return null;
    const parts = raw.split(",").map((s) => parseFloat(s.trim()));
    if (parts.length !== 4 || parts.some((n) => Number.isNaN(n))) return null;
    return { south: parts[0], west: parts[1], north: parts[2], east: parts[3] };
  }

  function formatDateLabel(field, from, to) {
    const name = field === "apply_by" ? "Apply by" : "Posted";
    const start = from || "…";
    const end = to || "…";
    return `${name}: ${start} – ${end}`;
  }

  function validSource(s) {
    return SOURCES.has(s) ? s : "all";
  }

  function makeClause(partial) {
    const phrase = String(partial.phrase || partial.value || "").trim();
    return {
      id: partial.id || makeId(),
      type: "clause",
      phrase,
      value: phrase,
      label: phrase || "Filter",
      source: validSource(partial.source),
      join: partial.join === "AND" ? "AND" : "OR",
    };
  }

  function clauseIsBlank(f) {
    return !String(f.phrase || "").trim() && (!f.source || f.source === "all");
  }

  function normalizeFilter(f) {
    if (!f) return null;
    if (f.type === "clause" || f.type === "search" || f.type === "keyword") {
      return makeClause(f);
    }
    return { ...f, id: f.id || makeId() };
  }

  function defaultStack() {
    return [
      { id: makeId(), type: "open", label: "Open applications" },
      makeClause({}),
    ];
  }

  function defaultViewPrefs() {
    return { sort: "apply_by", order: "asc" };
  }

  function serializeFilter(f) {
    const out = { type: f.type, label: f.label };
    if (f.value != null) out.value = f.value;
    if (f.phrase != null) out.phrase = f.phrase;
    if (f.source != null) out.source = f.source;
    if (f.type === "date") {
      if (f.field != null) out.field = f.field;
      if (f.from != null) out.from = f.from;
      if (f.to != null) out.to = f.to;
    }
    if (f.join != null) out.join = f.join;
    if (f.bounds != null) out.bounds = f.bounds;
    return out;
  }

  function deserializeStack(filters) {
    return (filters || []).map((f) => normalizeFilter(f)).filter(Boolean);
  }

  function encodeClause(f) {
    return JSON.stringify({
      p: f.phrase || "",
      s: f.source || "all",
      j: f.join || "OR",
    });
  }

  function decodeClause(raw) {
    try {
      const o = JSON.parse(raw);
      if (o && typeof o === "object") {
        return makeClause({
          phrase: o.p || o.phrase || "",
          source: o.s || o.source,
          join: o.j || o.join,
        });
      }
    } catch (_) {}
    const parts = String(raw || "").split("~").map((p) => {
      try {
        return decodeURIComponent(p);
      } catch {
        return p;
      }
    });
    return makeClause({
      phrase: parts[0] || "",
      join: parts[4] || parts[1],
    });
  }

  function parseUrl(search) {
    const params = new URLSearchParams(search || location.search);
    const filters = [];
    const encoded = params.getAll("c");
    if (encoded.length) {
      encoded.forEach((raw) => {
        const clause = decodeClause(raw);
        if (clause.phrase || (clause.source && clause.source !== "all")) {
          filters.push(clause);
        }
      });
    } else {
      params.getAll("q").forEach((v) => {
        const t = v.trim();
        if (t) filters.push(makeClause({ phrase: t }));
      });
      params.getAll("kw").forEach((v) => {
        const t = v.trim();
        if (t) filters.push(makeClause({ phrase: t }));
      });
    }
    const src = validSource(params.get("source"));
    if (src !== "all") {
      const clauses = filters.filter((f) => f.type === "clause");
      if (clauses.length) {
        clauses.forEach((c) => {
          if (!c.source || c.source === "all") c.source = src;
        });
      } else {
        filters.push(makeClause({ source: src }));
      }
    }
    const bbox = parseBbox(params.get("bbox"));
    if (bbox) filters.push({ id: makeId(), type: "area", bounds: bbox, label: "Map area" });
    const from = (params.get("from") || "").trim();
    const to = (params.get("to") || "").trim();
    if (from || to) {
      const field = params.get("date_field") === "apply_by" ? "apply_by" : "posted_at";
      filters.push({
        id: makeId(),
        type: "date",
        field,
        from,
        to,
        label: formatDateLabel(field, from, to),
      });
    }
    if (params.get("open") === "1") {
      filters.push({ id: makeId(), type: "open", label: "Open applications" });
    }
    if (params.get("recent") === "1") {
      filters.push({ id: makeId(), type: "recent", label: "New since yesterday" });
    }
    return filters;
  }

  function parseViewPrefs(search) {
    const params = new URLSearchParams(search || location.search);
    return {
      source: params.get("source"),
      sort: params.get("sort"),
      order: params.get("order"),
    };
  }

  function parseUrlOrDefaults(search) {
    const params = new URLSearchParams(search || location.search);
    const filters = !params.toString() ? defaultStack() : parseUrl(search);
    if (!filters.some((f) => f.type === "clause")) filters.push(makeClause({}));
    return filters;
  }

  function stackToParams(filters) {
    const params = new URLSearchParams();
    for (const f of filters) {
      if (f.type === "clause") {
        if (!clauseIsBlank(f)) params.append("c", encodeClause(f));
      }
      else if (f.type === "area" && f.bounds) {
        const b = f.bounds;
        params.set("bbox", `${b.south},${b.west},${b.north},${b.east}`);
      } else if (f.type === "date") {
        params.set("date_field", f.field === "apply_by" ? "apply_by" : "posted_at");
        if (f.from) params.set("from", f.from);
        if (f.to) params.set("to", f.to);
      } else if (f.type === "open") {
        params.set("open", "1");
      } else if (f.type === "recent") {
        params.set("recent", "1");
      }
    }
    return params;
  }

  function buildIndexQuery(filters, view) {
    const params = stackToParams(filters);
    const v = { ...defaultViewPrefs(), ...(view || {}) };
    if (v.sort) params.set("sort", v.sort);
    if (v.order) params.set("order", v.order);
    return params.toString();
  }

  function getViewPrefs() {
    if (typeof document !== "undefined" && document.getElementById("sort-filter")) {
      return {
        sort: document.getElementById("sort-filter")?.value || "apply_by",
        order: document.getElementById("order-filter")?.value || "asc",
      };
    }
    return loadSession()?.view || defaultViewPrefs();
  }

  function loadSession() {
    try {
      const raw = sessionStorage.getItem(SESSION_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  function saveSession(view) {
    try {
      sessionStorage.setItem(
        SESSION_KEY,
        JSON.stringify({
          stack: stack.map(serializeFilter),
          view: view || getViewPrefs(),
        })
      );
    } catch (_) {}
  }

  function indexUrlAddingKeyword(term) {
    const session = loadSession();
    let filters = session?.stack?.length ? deserializeStack(session.stack) : defaultStack();
    const val = (term || "").trim();
    if (
      val &&
      !filters.some(
        (f) => f.type === "clause" && String(f.phrase || "").toLowerCase() === val.toLowerCase()
      )
    ) {
      filters.push(makeClause({ phrase: val }));
    }
    const view = session?.view || defaultViewPrefs();
    const qs = buildIndexQuery(filters, view);
    return qs ? `index.html?${qs}` : "index.html";
  }

  function notify() {
    saveSession();
    for (const fn of listeners) fn([...stack]);
  }

  function init(filters) {
    stack = deserializeStack(filters);
    notify();
  }

  function setStack(filters) {
    stack = deserializeStack(filters);
    notify();
  }

  function add(filter) {
    if (filter.type === "area") {
      stack = stack.filter((f) => f.type !== "area");
      stack.push({
        id: makeId(),
        type: "area",
        bounds: filter.bounds,
        label: filter.label || "Map area",
      });
      notify();
      return;
    }

    if (filter.type === "date") {
      stack = stack.filter((f) => f.type !== "date");
      const field = filter.field === "apply_by" ? "apply_by" : "posted_at";
      const from = (filter.from || "").trim();
      const to = (filter.to || "").trim();
      if (!from && !to) return;
      stack.push({
        id: makeId(),
        type: "date",
        field,
        from,
        to,
        label: filter.label || formatDateLabel(field, from, to),
      });
      notify();
      return;
    }

    if (filter.type === "open") {
      if (stack.some((f) => f.type === "open")) return;
      stack.push({ id: makeId(), type: "open", label: "Open applications" });
      notify();
      return;
    }

    if (filter.type === "recent") {
      if (stack.some((f) => f.type === "recent")) return;
      stack.push({ id: makeId(), type: "recent", label: "New since yesterday" });
      notify();
      return;
    }

    if (filter.type === "clause" || filter.type === "search" || filter.type === "keyword") {
      const clause = makeClause(filter);
      if (clauseIsBlank(clause)) {
        if (stack.some((f) => f.type === "clause" && clauseIsBlank(f))) return;
        stack.push(clause);
        notify();
        return;
      }
      if (clause.phrase) {
        const blank = stack.find((f) => f.type === "clause" && clauseIsBlank(f));
        if (blank) {
          updateClause(blank.id, {
            phrase: clause.phrase,
            source: clause.source,
            join: clause.join,
          });
          return;
        }
      }
      if (
        stack.some(
          (f) =>
            f.type === "clause" &&
            String(f.phrase || "").toLowerCase() === String(clause.phrase || "").toLowerCase() &&
            (f.source || "all") === clause.source
        )
      ) {
        return;
      }
      stack.push(clause);
      notify();
    }
  }

  function updateClause(id, patch) {
    const idx = stack.findIndex((f) => f.id === id && f.type === "clause");
    if (idx < 0) return;
    stack[idx] = makeClause({ ...stack[idx], ...patch, id });
    notify();
  }

  function moveClause(fromId, toId) {
    if (!fromId || fromId === toId) return;
    const clauses = stack.filter((f) => f.type === "clause");
    const others = stack.filter((f) => f.type !== "clause");
    const fromIdx = clauses.findIndex((f) => f.id === fromId);
    const toIdx = clauses.findIndex((f) => f.id === toId);
    if (fromIdx < 0 || toIdx < 0) return;
    const [moved] = clauses.splice(fromIdx, 1);
    clauses.splice(toIdx, 0, moved);
    stack = [...clauses, ...others];
    notify();
  }

  function remove(id) {
    stack = stack.filter((f) => f.id !== id);
    if (!stack.some((f) => f.type === "clause")) stack.push(makeClause({}));
    notify();
  }

  function clear() {
    stack = [makeClause({})];
    notify();
  }

  function getAreaFilter() {
    return stack.find((f) => f.type === "area") || null;
  }

  function getDateFilter() {
    return stack.find((f) => f.type === "date") || null;
  }

  function getClauses() {
    return stack.filter((f) => f.type === "clause");
  }

  function isOpenFilterActive() {
    return stack.some((f) => f.type === "open");
  }

  function toggleOpenFilter() {
    if (isOpenFilterActive()) {
      stack = stack.filter((f) => f.type !== "open");
    } else {
      stack.push({ id: makeId(), type: "open", label: "Open applications" });
    }
    notify();
  }

  function isRecentFilterActive() {
    return stack.some((f) => f.type === "recent");
  }

  function toggleRecentFilter() {
    if (isRecentFilterActive()) {
      stack = stack.filter((f) => f.type !== "recent");
    } else {
      stack.push({ id: makeId(), type: "recent", label: "New since yesterday" });
    }
    notify();
  }

  function buildApiParams(source, sort, order) {
    const params = stackToParams(stack);
    params.set("source", source);
    params.set("sort", sort);
    params.set("order", order);
    return params;
  }

  function toUrl() {
    const params = stackToParams(stack);
    const view = getViewPrefs();
    if (view.sort) params.set("sort", view.sort);
    if (view.order) params.set("order", view.order);
    const qs = params.toString();
    return qs ? `/?${qs}` : "/";
  }

  function onChange(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  }

  window.JobBoardsFilters = {
    parseUrl,
    parseUrlOrDefaults,
    parseViewPrefs,
    defaultStack,
    defaultViewPrefs,
    parseBbox,
    formatDateLabel,
    init,
    setStack,
    add,
    updateClause,
    moveClause,
    remove,
    clear,
    getStack: () => [...stack],
    getClauses,
    getAreaFilter,
    getDateFilter,
    isOpenFilterActive,
    toggleOpenFilter,
    isRecentFilterActive,
    toggleRecentFilter,
    buildApiParams,
    buildIndexQuery,
    indexUrlAddingKeyword,
    saveSession,
    loadSession,
    getViewPrefs,
    toUrl,
    onChange,
  };
})();
