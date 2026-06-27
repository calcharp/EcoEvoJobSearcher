(function () {
  const THEME_KEY = "jobboards-theme";

  const themeToggle = document.getElementById("theme-toggle");
  const lastUpdated = document.getElementById("last-updated");

  let mapCtrl = null;
  let focusedJobId = null;
  let allJobsCache = [];
  let allMapJobsCache = [];
  let mapStats = { mapped: 0, missing: 0, filteredTotal: 0 };
  let geoSummary = null;
  let jobsLoadedOnce = false;
  let dateRangeCtrl = null;
  let resultsInFlight = false;
  let pendingReloadOpts = null;
  let reloadTimer = null;

  const FILTER_TYPE_LABELS = { search: "Search", keyword: "Keyword", area: "Area", date: "Date", open: "Open", recent: "Recent" };

  function jobDetailHref(jobId) {
    return JobBoardsJobUrl(jobId);
  }

  function applyViewPrefsFromUrl() {
    if (!window.JobBoardsFilters) return;
    const prefs = JobBoardsFilters.parseViewPrefs();
    const sourceEl = document.getElementById("source-filter");
    const sortEl = document.getElementById("sort-filter");
    const orderEl = document.getElementById("order-filter");
    if (prefs.source && sourceEl) sourceEl.value = prefs.source;
    if (prefs.sort && sortEl) sortEl.value = prefs.sort;
    if (prefs.order && orderEl) orderEl.value = prefs.order;
  }

  function syncFilterUrl() {
    if (window.JobBoardsFilters && window.JobBoardsPage === "index") {
      window.history.replaceState(null, "", JobBoardsFilters.toUrl());
    }
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  function applyTheme(theme) {
    const isLight = theme === "light";
    if (isLight) {
      document.documentElement.setAttribute("data-theme", "light");
      localStorage.setItem(THEME_KEY, "light");
    } else {
      document.documentElement.removeAttribute("data-theme");
      localStorage.removeItem(THEME_KEY);
    }
    if (themeToggle) {
      themeToggle.setAttribute("aria-label", isLight ? "Switch to dark mode" : "Switch to light mode");
      themeToggle.title = isLight ? "Light mode" : "Dark mode";
    }
  }

  function toggleTheme() {
    applyTheme(currentTheme() === "light" ? "dark" : "light");
  }

  function formatLastUpdated(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return "Updated " + d.toLocaleString(undefined, {
        month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
      });
    } catch {
      return iso;
    }
  }

  function esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function deadlineClass(days) {
    if (days == null) return "";
    if (days < 0) return "deadline-past";
    if (days <= 14) return "deadline-soon";
    return "deadline-ok";
  }

  function deadlineLabel(days) {
    if (days == null) return "";
    if (days < 0) return `${-days}d ago`;
    if (days === 0) return "Today";
    return `${days}d left`;
  }

  function sourceLabel(s) {
    if (s === "ecoevojobs") return "ecoevo";
    if (s === "evoldir") return "evoldir";
    if (s === "sciencecareers") return "Sci Careers";
    return s;
  }

  function renderBadges(sources) {
    return (sources || []).map((s) => `<span class="badge badge-${s}">${sourceLabel(s)}</span>`).join("");
  }

  function jobMapStatus(job) {
    if (job.map_status) return job.map_status;
    if (job.map_geo) return "mapped";
    if (allMapJobsCache.some((m) => m.id === job.id)) return "mapped";
    return "unresolved";
  }

  function filteredMapBreakdown(jobs) {
    let onMap = 0;
    let unresolved = 0;
    let pending = 0;
    for (const job of jobs) {
      const status = jobMapStatus(job);
      if (status === "mapped") onMap += 1;
      else if (status === "pending") pending += 1;
      else unresolved += 1;
    }
    return { onMap, unresolved, pending, total: jobs.length };
  }

  function describeUnmappedCounts(unresolved, pending) {
    const parts = [];
    if (unresolved) {
      parts.push(
        `${unresolved} listing${unresolved === 1 ? "" : "s"} have no map pin — institution/location couldn't be matched to coordinates (this isn't a loading delay)`
      );
    }
    if (pending) {
      parts.push(
        `${pending} listing${pending === 1 ? "" : "s"} from new institutions may appear on the map after the next site update`
      );
    }
    return parts.join(". ");
  }

  function renderJobCard(job) {
    const dc = deadlineClass(job.days_until);
    const dl = deadlineLabel(job.days_until);
    const mapStatus = jobMapStatus(job);
    const onMap = mapStatus === "mapped";
    const locateTitle = onMap
      ? "Show on map"
      : mapStatus === "pending"
        ? "Map location not available yet"
        : "No map location — institution couldn't be matched";
    const notes = job.has_notes_thread || (job.notes_thread && job.notes_thread.length > 1)
      ? `<span class="note-indicator">💬 notes</span>`
      : job.source === "evoldir" && job.post_size
        ? `<span class="note-indicator">${job.post_size}</span>`
        : "";

    return `
      <div class="job-card-wrap" data-job-id="${esc(job.id)}">
        <a class="job-card" href="${jobDetailHref(job.id)}">
          <div class="job-card-top">
            <div>
              <h3 class="job-card-title">${esc(job.subject_area || job.title || job.institution)}</h3>
              <p class="job-card-institution">${esc(job.institution)}${job.rank_or_pi ? " · " + esc(job.rank_or_pi) : ""}${job.location ? " · " + esc(job.location) : ""}</p>
            </div>
            <div class="source-badges">${renderBadges(job.sources)}</div>
          </div>
          <div class="job-card-meta">
            <span class="meta-chip ${dc}"><strong>Apply</strong> ${esc(job.apply_display)}${dl ? `<span class="deadline-chip">${dl}</span>` : ""}</span>
            <span class="meta-chip"><strong>Posted</strong> ${esc(job.posted_display)}</span>
            ${notes}
          </div>
        </a>
        <div class="job-card-actions">
          <button type="button" class="job-card-action job-card-locate${onMap ? "" : " is-unmapped"}" data-job-id="${esc(job.id)}" data-map-status="${mapStatus}" title="${esc(locateTitle)}" aria-label="${esc(locateTitle)}"${onMap ? "" : " disabled"}>⌖</button>
        </div>
      </div>`;
  }

  function updateStats(stats) {
    const map = {
      total: "stat-total",
      ecoevojobs: "stat-ecoevo",
      evoldir: "stat-evoldir",
      sciencecareers: "stat-sciencecareers",
      with_deadline: "stat-deadlines",
    };
    for (const [k, id] of Object.entries(map)) {
      const el = document.getElementById(id);
      if (el && stats[k] != null) el.textContent = stats[k];
    }
    if (lastUpdated && stats.last_fetched_at) {
      lastUpdated.textContent = formatLastUpdated(stats.last_fetched_at);
    }
  }

  function getFilterOpts() {
    const stack = window.JobBoardsFilters?.getStack() || [];
    const terms = [];
    let dateRange = null;
    for (const f of stack) {
      if (f.type === "search" || f.type === "keyword") terms.push(f.value);
      if (f.type === "date") {
        dateRange = {
          field: f.field === "apply_by" ? "apply_by" : "posted_at",
          from: f.from || "",
          to: f.to || "",
        };
      }
    }
    return {
      source: document.getElementById("source-filter")?.value || "all",
      sort: document.getElementById("sort-filter")?.value || "apply_by",
      order: document.getElementById("order-filter")?.value || "asc",
      terms,
      dateRange: dateRange && (dateRange.from || dateRange.to) ? dateRange : null,
      openOnly: stack.some((f) => f.type === "open"),
      recentOnly: stack.some((f) => f.type === "recent"),
    };
  }

  function getMapJobsForList() {
    const area = window.JobBoardsFilters?.getAreaFilter();
    const visibleIds = new Set(
      JobBoardsStaticQuery.filterJobs(allJobsCache, getFilterOpts()).map((j) => j.id)
    );
    let jobs = allMapJobsCache.filter((j) => visibleIds.has(j.id));
    if (area?.bounds) {
      const b = area.bounds;
      jobs = jobs.filter(
        (j) => b.south <= j.lat && j.lat <= b.north && b.west <= j.lon && j.lon <= b.east
      );
    }
    return jobs;
  }

  function listJobsForDisplay() {
    let jobs = JobBoardsStaticQuery.filterJobs(allJobsCache, getFilterOpts());
    if (!window.JobBoardsFilters?.getAreaFilter()) return jobs;
    const ids = new Set(getMapJobsForList().map((j) => j.id));
    return jobs.filter((j) => ids.has(j.id));
  }

  function updateResultCount(count, loading) {
    const el = document.getElementById("jobs-result-count");
    if (!el) return;
    if (loading) {
      el.textContent = "Loading…";
      return;
    }
    const n = count || 0;
    el.textContent = n === 1 ? "1 result" : `${n} results`;
  }

  function emptyListMessage(hasArea) {
    if (hasArea) return "No jobs in the selected map area.";
    return "No jobs match your filters.";
  }

  function updateMapFootnote(highlightJob) {
    const footnote = document.getElementById("map-footnote");
    const detail = document.getElementById("map-footnote-detail");
    if (!footnote) return;

    if (highlightJob) {
      const job = typeof highlightJob === "object"
        ? highlightJob
        : allJobsCache.find((j) => j.id === highlightJob);
      if (job && detail) {
        const status = jobMapStatus(job);
        const place = [job.institution, job.location].filter(Boolean).join(", ");
        if (status === "pending") {
          detail.textContent = `${place} hasn't been mapped yet. New institutions are added when the site is rebuilt.`;
        } else if (status === "unresolved") {
          detail.textContent = `${place} couldn't be matched to map coordinates. The job is still listed above — use the institution and location fields to search elsewhere.`;
        } else {
          detail.textContent = "";
          detail.hidden = true;
          return;
        }
        detail.hidden = false;
        return;
      }
    }

    if (detail && !highlightJob) {
      detail.textContent = "";
      detail.hidden = true;
    }

    const filtered = JobBoardsStaticQuery.filterJobs(allJobsCache, getFilterOpts());
    const { onMap, unresolved, pending, total } = filteredMapBreakdown(filtered);
    const offMap = total - onMap;
    const filterCount = window.JobBoardsFilters?.getStack().length || 0;
    const filterNote = filterCount
      ? ` · ${filterCount} active filter${filterCount === 1 ? "" : "s"}`
      : "";
    const hasArea = !!window.JobBoardsFilters?.getAreaFilter();
    const listCount = listJobsForDisplay().length;

    if (hasArea) {
      footnote.textContent = listCount
        ? `${listCount} listing${listCount === 1 ? "" : "s"} in the selected map area`
          + (total > listCount
            ? ` (${total - listCount} filtered listing${total - listCount === 1 ? "" : "s"} outside this area or without a map pin)`
            : "")
        : total
          ? `${total} matching listing${total === 1 ? "" : "s"}, but none with a map pin fall in this area.`
          : "No jobs match the current filters.";
      if (detail && offMap > 0 && !listCount) {
        detail.textContent = describeUnmappedCounts(unresolved, pending);
        detail.hidden = !detail.textContent;
      }
      return;
    }

    if (!total) {
      footnote.textContent = "No jobs match the current filters.";
      return;
    }

    if (!onMap) {
      footnote.textContent = `${total} matching listing${total === 1 ? "" : "s"}, none with a map pin.${filterNote}`;
      if (detail) {
        detail.textContent = describeUnmappedCounts(unresolved, pending);
        detail.hidden = !detail.textContent;
      }
      return;
    }

    footnote.textContent = `${onMap} of ${total} matching listing${total === 1 ? "" : "s"} on the map${filterNote}`;

    if (detail && offMap > 0) {
      detail.textContent = describeUnmappedCounts(unresolved, pending);
      detail.hidden = !detail.textContent;
    } else if (detail && geoSummary && geoSummary.jobs_unmapped > 0 && filterCount === 0) {
      detail.textContent = describeUnmappedCounts(
        geoSummary.jobs_unresolved || 0,
        geoSummary.jobs_pending || 0
      );
      detail.hidden = !detail.textContent;
    }
  }

  function renderJobsList(list, jobs) {
    const CHUNK = 40;
    let index = 0;
    list.innerHTML = "";
    function paint() {
      const end = Math.min(index + CHUNK, jobs.length);
      list.insertAdjacentHTML("beforeend", jobs.slice(index, end).map(renderJobCard).join(""));
      index = end;
      if (index < jobs.length) requestAnimationFrame(paint);
    }
    requestAnimationFrame(paint);
  }

  function applyDisplay(opts = {}) {
    const list = document.getElementById("jobs-list");
    if (!list) return;

    const listJobs = listJobsForDisplay();
    const hasArea = !!window.JobBoardsFilters?.getAreaFilter();

    if (!listJobs.length) {
      list.innerHTML = `<p class="empty-state">${emptyListMessage(hasArea)}</p>`;
    } else {
      renderJobsList(list, listJobs);
    }

    updateResultCount(listJobs.length);

    if (mapCtrl) {
      const focusId = opts.focusId || new URLSearchParams(window.location.search).get("focus");
      mapCtrl.setMarkers(getMapJobsForList(), {
        focusId: focusId || undefined,
        skipFit: !!(hasArea || focusId),
      });
      if (focusId && focusJobOnMap(focusId, { openPopup: true })) {
        setFocusedCard(focusId);
      } else if (focusedJobId && !mapCtrl.hasJob(focusedJobId)) {
        setFocusedCard(null);
      }
    }

    updateMapFootnote();
  }

  function renderFilterStack(filters) {
    const el = document.getElementById("filter-stack");
    const clearBtn = document.getElementById("filter-stack-clear");
    if (!el) return;
    el.innerHTML = filters
      .map(
        (f) => `
      <span class="filter-chip filter-chip-${f.type}">
        <span class="filter-chip-type">${FILTER_TYPE_LABELS[f.type] || f.type}</span>
        <span class="filter-chip-value">${esc(f.type === "area" ? "map selection" : f.label)}</span>
        <button type="button" class="filter-chip-remove" data-filter-id="${esc(f.id)}" aria-label="Remove filter">×</button>
      </span>`
      )
      .join("");
    if (clearBtn) clearBtn.disabled = !filters.length;
  }

  function restoreMapAreaFromFilters() {
    if (!mapCtrl || !window.JobBoardsFilters) return;
    const area = JobBoardsFilters.getAreaFilter();
    if (area?.bounds) mapCtrl.setAreaBounds(area.bounds);
    else mapCtrl.clearAreaBounds();
  }

  function scheduleReloadResults(opts = {}) {
    pendingReloadOpts = { ...(pendingReloadOpts || {}), ...opts };
    clearTimeout(reloadTimer);
    const delay = opts.immediate ? 0 : 180;
    reloadTimer = setTimeout(() => {
      const next = pendingReloadOpts;
      pendingReloadOpts = null;
      reloadResults(next || {});
    }, delay);
  }

  async function loadStaticDatasets() {
    const [jobsRes, mapRes, metaRes] = await Promise.all([
      fetch(JobBoardsDataUrl("jobs.json"), { cache: "no-store" }),
      fetch(JobBoardsDataUrl("map-jobs.json"), { cache: "no-store" }),
      fetch(JobBoardsDataUrl("meta.json"), { cache: "no-store" }),
    ]);
    if (!jobsRes.ok) throw new Error("jobs fetch failed");
    const jobsData = await jobsRes.json();
    const mapData = mapRes.ok ? await mapRes.json() : { jobs: [], mapped: 0, missing: 0 };
    const meta = metaRes.ok ? await metaRes.json() : {};
    updateStats(jobsData.stats || meta.stats || {});
    if (lastUpdated && (meta.last_fetched_at || jobsData.stats?.last_fetched_at)) {
      lastUpdated.textContent = formatLastUpdated(meta.last_fetched_at || jobsData.stats.last_fetched_at);
    }
    const note = document.getElementById("static-site-note");
    if (note && meta.generated_at) {
      note.textContent = `Listings updated ${formatLastUpdated(meta.generated_at)}`;
    }
    allJobsCache = jobsData.jobs || [];
    allMapJobsCache = mapData.jobs || [];
    geoSummary = mapData.geo_summary || meta.map_summary || null;
    mapStats = {
      mapped: mapData.mapped || allMapJobsCache.length,
      missing: mapData.missing || 0,
      filteredTotal: allJobsCache.length,
    };
    jobsLoadedOnce = true;
  }

  async function reloadResults(opts = {}) {
    const list = document.getElementById("jobs-list");
    const footnote = document.getElementById("map-footnote");
    if (!list || window.JobBoardsPage !== "index") return;

    if (resultsInFlight) {
      pendingReloadOpts = { ...(pendingReloadOpts || {}), ...opts };
      return;
    }

    const quiet = opts.quiet === true;
    const hasArea = !!window.JobBoardsFilters?.getAreaFilter();

    if (!quiet && !list.querySelector(".job-card")) {
      list.innerHTML = '<p class="empty-state">Loading jobs…</p>';
      updateResultCount(null, true);
    } else if (!quiet) {
      updateResultCount(listJobsForDisplay().length);
    }

    if (opts.resetFit && mapCtrl && !hasArea) mapCtrl.resetFit();

    resultsInFlight = true;
    try {
      if (!jobsLoadedOnce) await loadStaticDatasets();
      applyDisplay({ focusId: opts.focusId });
    } catch {
      list.innerHTML = '<p class="empty-state">Failed to load jobs.</p>';
      if (footnote) footnote.textContent = "Failed to load map data.";
      updateResultCount(0);
    } finally {
      resultsInFlight = false;
      if (pendingReloadOpts) {
        const next = pendingReloadOpts;
        pendingReloadOpts = null;
        scheduleReloadResults(next);
      }
    }
  }

  function onFiltersChanged(filters) {
    renderFilterStack(filters);
    const openToggle = document.getElementById("open-jobs-toggle");
    if (openToggle && window.JobBoardsFilters) {
      const active = JobBoardsFilters.isOpenFilterActive();
      openToggle.classList.toggle("is-active", active);
      openToggle.setAttribute("aria-pressed", active ? "true" : "false");
    }
    const recentToggle = document.getElementById("recent-jobs-toggle");
    if (recentToggle && window.JobBoardsFilters) {
      const active = JobBoardsFilters.isRecentFilterActive();
      recentToggle.classList.toggle("is-active", active);
      recentToggle.setAttribute("aria-pressed", active ? "true" : "false");
    }
    if (window.JobBoardsFilters) {
      window.history.replaceState(null, "", JobBoardsFilters.toUrl());
    }
    restoreMapAreaFromFilters();
    if (dateRangeCtrl) {
      const dateFilter = filters.find((f) => f.type === "date");
      dateRangeCtrl.setFromFilter(dateFilter || null);
    }
    if (window.JobBoardsPage !== "index") return;
    applyDisplay();
    scheduleReloadResults({ resetFit: !JobBoardsFilters?.getAreaFilter() });
  }

  function onAreaSelected(bounds) {
    if (!window.JobBoardsFilters) return;
    if (!bounds) {
      const area = JobBoardsFilters.getAreaFilter();
      if (area) JobBoardsFilters.remove(area.id);
      return;
    }
    JobBoardsFilters.add({
      type: "area",
      bounds: {
        south: bounds.getSouth(),
        west: bounds.getWest(),
        north: bounds.getNorth(),
        east: bounds.getEast(),
      },
    });
  }

  function setFocusedCard(jobId) {
    focusedJobId = jobId || null;
    document.querySelectorAll(".job-card-wrap").forEach((wrap) => {
      wrap.classList.toggle("is-map-focused", !!jobId && wrap.dataset.jobId === jobId);
    });
  }

  function focusJobOnMap(jobId, opts = {}) {
    if (!mapCtrl || !jobId) return false;
    if (mapCtrl.hasJob(jobId)) {
      mapCtrl.focusJob(jobId, opts.zoom || 12, opts.openPopup !== false);
      setFocusedCard(jobId);
      return true;
    }
    return false;
  }

  function wireJobsListMapEvents() {
    const list = document.getElementById("jobs-list");
    if (!list || list.dataset.mapWired === "1") return;
    list.dataset.mapWired = "1";

    list.addEventListener("click", (e) => {
      const btn = e.target.closest(".job-card-locate");
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      const jobId = btn.dataset.jobId;
      if (!focusJobOnMap(jobId)) {
        const job = allJobsCache.find((j) => j.id === jobId);
        if (job) updateMapFootnote(job);
      }
    });

    list.addEventListener("mouseover", (e) => {
      const wrap = e.target.closest(".job-card-wrap");
      if (!wrap || !mapCtrl) return;
      const jobId = wrap.dataset.jobId;
      if (jobId && mapCtrl.hasJob(jobId)) mapCtrl.highlightJob(jobId);
    });
  }

  function initIndexMap() {
    const el = document.getElementById("job-map");
    if (!el || !window.JobBoardsMap || !window.L) return;
    mapCtrl = JobBoardsMap.create(el, {
      areaSelect: true,
      fullscreenTarget: el.closest(".map-panel"),
    });
    mapCtrl.onAreaSelected(onAreaSelected);
    document.getElementById("filter-stack")?.addEventListener("click", (e) => {
      const btn = e.target.closest(".filter-chip-remove");
      if (!btn || !window.JobBoardsFilters) return;
      const filterId = btn.dataset.filterId;
      const removed = JobBoardsFilters.getStack().find((f) => f.id === filterId);
      JobBoardsFilters.remove(filterId);
      if (removed?.type === "date" && dateRangeCtrl) dateRangeCtrl.resetToFull();
    });
    document.getElementById("filter-stack-clear")?.addEventListener("click", () => {
      if (!window.JobBoardsFilters) return;
      JobBoardsFilters.clear();
      if (mapCtrl) mapCtrl.clearAreaBounds();
      if (dateRangeCtrl) dateRangeCtrl.resetToFull();
    });
    document.getElementById("open-jobs-toggle")?.addEventListener("click", () => {
      if (!window.JobBoardsFilters) return;
      JobBoardsFilters.toggleOpenFilter();
    });
    document.getElementById("recent-jobs-toggle")?.addEventListener("click", () => {
      if (!window.JobBoardsFilters) return;
      JobBoardsFilters.toggleRecentFilter();
    });
    wireJobsListMapEvents();
    restoreMapAreaFromFilters();
  }

  function csvEscape(value) {
    const s = value == null ? "" : String(value);
    if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  }

  function exportVisibleJobsCsv() {
    const jobs = listJobsForDisplay();
    if (!jobs.length) {
      window.alert("No jobs to export for the current filters.");
      return;
    }

    const headers = [
      "Title",
      "Institution",
      "Location",
      "Position",
      "Sources",
      "Posted",
      "Apply by",
      "Days until deadline",
      "URL",
    ];
    const rows = jobs.map((job) => [
      job.subject_area || job.title || "",
      job.institution || "",
      job.location || "",
      job.rank_or_pi || job.position_type || "",
      (job.sources || [job.source]).filter(Boolean).join("; "),
      job.posted_at || job.posted_display || "",
      job.apply_by || job.apply_display || "",
      job.days_until != null ? job.days_until : "",
      job.url || "",
    ]);

    const csv = [headers, ...rows].map((row) => row.map(csvEscape).join(",")).join("\r\n");
    const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `ecoevo-jobs-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  if (themeToggle) {
    applyTheme(currentTheme());
    themeToggle.addEventListener("click", toggleTheme);
  }

  ["source-filter", "sort-filter", "order-filter"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => {
      if (window.JobBoardsFilters) JobBoardsFilters.saveSession();
      syncFilterUrl();
      scheduleReloadResults({ resetFit: true });
    });
  });

  const searchInput = document.getElementById("search-input");
  if (searchInput) {
    searchInput.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || !window.JobBoardsFilters) return;
      e.preventDefault();
      const val = searchInput.value.trim();
      if (!val) return;
      JobBoardsFilters.add({ type: "search", value: val });
      searchInput.value = "";
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.JobBoardsFilters) {
      const origToUrl = JobBoardsFilters.toUrl.bind(JobBoardsFilters);
      JobBoardsFilters.toUrl = function () {
        const raw = origToUrl();
        const qs = raw.startsWith("/?") ? raw.slice(2) : raw.replace(/^\//, "");
        return qs ? JobBoardsPageUrl(`index.html?${qs}`) : JobBoardsPageUrl("index.html");
      };
    }

    if (window.JobBoardsPage === "index") {
      initIndexMap();
      if (window.JobBoardsDateRange) {
        dateRangeCtrl = JobBoardsDateRange.create(document.getElementById("date-range-panel"));
      }
      if (window.JobBoardsFilters) {
        applyViewPrefsFromUrl();
        const initial =
          window.JobBoardsInitialFilters?.length
            ? window.JobBoardsInitialFilters
            : JobBoardsFilters.parseUrlOrDefaults();
        JobBoardsFilters.onChange(onFiltersChanged);
        JobBoardsFilters.init(initial);
      } else {
        reloadResults();
      }
      document.getElementById("export-csv-btn")?.addEventListener("click", exportVisibleJobsCsv);
    }

    if (window.JobBoardsPage !== "index") {
      fetch(JobBoardsDataUrl("meta.json"), { cache: "no-store" })
        .then((r) => r.json())
        .then((meta) => {
          updateStats(meta.stats || {});
          if (lastUpdated && meta.last_fetched_at) {
            lastUpdated.textContent = formatLastUpdated(meta.last_fetched_at);
          }
          const note = document.getElementById("static-site-note");
          if (note && meta.generated_at) {
            note.textContent = `Listings updated ${formatLastUpdated(meta.generated_at)}`;
          }
        })
        .catch(() => {});
    }
  });
})();
