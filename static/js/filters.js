(function () {
  let stack = [];
  let nextId = 1;
  const listeners = new Set();

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

  function defaultStack() {
    return [{ id: makeId(), type: "open", label: "Open applications" }];
  }

  function parseUrl(search) {
    const params = new URLSearchParams(search || location.search);
    const filters = [];
    params.getAll("q").forEach((v) => {
      const t = v.trim();
      if (t) filters.push({ id: makeId(), type: "search", value: t, label: t });
    });
    params.getAll("kw").forEach((v) => {
      const t = v.trim();
      if (t) filters.push({ id: makeId(), type: "keyword", value: t, label: t });
    });
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
    return filters;
  }

  function parseUrlOrDefaults(search) {
    const params = new URLSearchParams(search || location.search);
    if (!params.toString()) return defaultStack();
    return parseUrl(search);
  }

  function notify() {
    for (const fn of listeners) fn([...stack]);
  }

  function init(filters) {
    stack = (filters || []).map((f) => ({ ...f, id: f.id || makeId() }));
    notify();
  }

  function setStack(filters) {
    stack = (filters || []).map((f) => ({ ...f, id: f.id || makeId() }));
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
      stack.push({
        id: makeId(),
        type: "open",
        label: filter.label || "Open applications",
      });
      notify();
      return;
    }

    const val = (filter.value || "").trim();
    if (!val) return;
    if (stack.some((f) => f.type === filter.type && f.value.toLowerCase() === val.toLowerCase())) {
      return;
    }
    stack.push({
      id: makeId(),
      type: filter.type,
      value: val,
      label: filter.label || val,
    });
    notify();
  }

  function remove(id) {
    stack = stack.filter((f) => f.id !== id);
    notify();
  }

  function clear() {
    stack = [];
    notify();
  }

  function getAreaFilter() {
    return stack.find((f) => f.type === "area") || null;
  }

  function getDateFilter() {
    return stack.find((f) => f.type === "date") || null;
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

  function buildApiParams(source, sort, order) {
    const params = new URLSearchParams({ source, sort, order });
    for (const f of stack) {
      if (f.type === "search") params.append("q", f.value);
      else if (f.type === "keyword") params.append("kw", f.value);
      else if (f.type === "area" && f.bounds) {
        const b = f.bounds;
        params.set("bbox", `${b.south},${b.west},${b.north},${b.east}`);
      } else if (f.type === "date") {
        params.set("date_field", f.field === "apply_by" ? "apply_by" : "posted_at");
        if (f.from) params.set("from", f.from);
        if (f.to) params.set("to", f.to);
      } else if (f.type === "open") {
        params.set("open", "1");
      }
    }
    return params;
  }

  function toUrl() {
    const params = buildApiParams("all", "posted_at", "desc");
    params.delete("source");
    params.delete("sort");
    params.delete("order");
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
    defaultStack,
    parseBbox,
    formatDateLabel,
    init,
    setStack,
    add,
    remove,
    clear,
    getStack: () => [...stack],
    getAreaFilter,
    getDateFilter,
    isOpenFilterActive,
    toggleOpenFilter,
    buildApiParams,
    toUrl,
    onChange,
  };
})();
