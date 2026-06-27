(function () {
  const isStatic = !!window.JobBoardsStatic;
  const HEARTBEAT_MS = 3000;
  const POLL_MS_RUNNING = 800;
  const POLL_MS_IDLE = 3000;

  function sendHeartbeat() {
    fetch("/api/heartbeat", { method: "POST", keepalive: true }).catch(() => {});
  }

  function sendShutdown() {
    navigator.sendBeacon("/api/shutdown", "");
  }

  if (!isStatic) {
    sendHeartbeat();
    setInterval(sendHeartbeat, HEARTBEAT_MS);
    window.addEventListener("pagehide", (e) => {
      if (e.persisted) return;
      sendShutdown();
    });
  }

  function jobDetailHref(jobId) {
    if (window.JobBoardsJobUrl) return JobBoardsJobUrl(jobId);
    if (window.JobBoardsStatic) {
      return JobBoardsPageUrl(`job.html?id=${encodeURIComponent(jobId)}`);
    }
    return `/jobs/${jobId}`;
  }

  const overlay = document.getElementById("loading-overlay");
  const loadingMsg = document.getElementById("loading-message");
  const loadingCounts = document.getElementById("loading-counts");
  const progressBanner = document.getElementById("progress-banner");
  const progressMessage = document.getElementById("progress-message");
  const progressBarFill = document.getElementById("progress-bar-fill");
  const progressDetail = document.getElementById("progress-detail");
  const progressHideBtn = document.getElementById("progress-hide-btn");
  const themeToggle = document.getElementById("theme-toggle");
  const lastUpdated = document.getElementById("last-updated");
  const PROGRESS_HIDE_KEY = "jobboards-hide-progress";
  const THEME_KEY = "jobboards-theme";

  let hasCache = window.JobBoardsHasPreview === true;
  let jobsLoadedOnce = hasCache;
  let lastReloadKey = "";
  let pollTimer = null;
  let loadInFlight = false;
  let scrapeRunning = false;
  let progressHidden = localStorage.getItem(PROGRESS_HIDE_KEY) === "1";
  let progressWanted = false;

  function showBlockingLoad(show) {
    if (overlay) overlay.hidden = !show;
  }

  function showProgressBanner(show) {
    if (!progressBanner) return;
    if (show && progressHidden) {
      progressBanner.hidden = true;
      return;
    }
    progressBanner.hidden = !show;
  }

  function setProgressHidden(hidden) {
    progressHidden = hidden;
    if (hidden) {
      localStorage.setItem(PROGRESS_HIDE_KEY, "1");
      showProgressBanner(false);
    } else {
      localStorage.removeItem(PROGRESS_HIDE_KEY);
      if (progressWanted) showProgressBanner(true);
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
    return (sources || []).map((s) => {
      return `<span class="badge badge-${s}">${sourceLabel(s)}</span>`;
    }).join("");
  }

  function renderJobCard(job) {
    const dc = deadlineClass(job.days_until);
    const dl = deadlineLabel(job.days_until);
    const view = document.getElementById("view-filter")?.value || "all";
    const saved = !!job.is_saved;
    const dismissAction = view === "dismissed" ? "restore" : "dismiss";
    const dismissLabel = dismissAction === "restore" ? "Restore listing" : "Dismiss listing";
    const dismissIcon = dismissAction === "restore" ? "↩" : "×";
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
          <button type="button" class="job-card-action job-card-save${saved ? " is-saved" : ""}" data-action="save" data-job-id="${esc(job.id)}" title="${saved ? "Unsave job" : "Save job"}" aria-label="${saved ? "Unsave job" : "Save job"}">${saved ? "★" : "☆"}</button>
          <button type="button" class="job-card-action job-card-dismiss" data-action="${dismissAction}" data-job-id="${esc(job.id)}" title="${dismissLabel}" aria-label="${dismissLabel}">${dismissIcon}</button>
          <button type="button" class="job-card-action job-card-locate" data-job-id="${esc(job.id)}" title="Show on map" aria-label="Show on map">⌖</button>
        </div>
      </div>`;
  }

  function esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
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
    if (stats.total > 0) hasCache = true;
  }

  function setStatsBarRefreshing(active) {
    const bar = document.getElementById("stats-bar");
    if (!bar) return;
    bar.classList.toggle("is-refreshing", active);
    const label = bar.querySelector(".stat-card:first-child .stat-label");
    if (label) {
      label.textContent = active ? "Saved this refresh" : "Total listings";
    }
  }

  function updateProgressUI(data) {
    const pct = Math.min(100, Math.max(0, data.progress_percent || 0));
    if (progressMessage) progressMessage.textContent = data.message || "Updating…";
    if (progressBarFill) progressBarFill.style.width = pct + "%";
    if (progressDetail) progressDetail.textContent = data.progress_detail || "";
    if (loadingMsg) loadingMsg.textContent = data.message || "…";
    if (loadingCounts) loadingCounts.textContent = data.running ? `${pct}%` : "";
  }

  function reloadKey(data) {
    const filters = window.JobBoardsFilters?.toUrl() || "";
    const view = currentView();
    return `${data.phase}:${data.ecoevo_done || 0}:${data.evoldir_done || 0}:${data.sciencecareers_done || 0}:${data.running}:${view}:${filters}`;
  }

  function maybeRefreshJobs(data) {
    if (window.JobBoardsPage !== "index") return;
    // While scraping, avoid reloading the full list — it locks the DB and freezes progress
    if (data.running) return;
    const key = reloadKey(data);
    if (key === lastReloadKey && jobsLoadedOnce) return;
    lastReloadKey = key;
    scheduleReloadResults({ quiet: true });
  }

  let mapCtrl = null;
  let focusedJobId = null;
  let mapInFlight = false;
  let mapRefreshTimer = null;
  let allJobsCache = [];
  let allMapJobsCache = [];
  let mapStats = { mapped: 0, missing: 0, filteredTotal: 0 };

  const FILTER_TYPE_LABELS = { search: "Search", keyword: "Keyword", area: "Area", date: "Date" };

  let dateRangeCtrl = null;
  let savedSearches = [];

  function currentView() {
    return document.getElementById("view-filter")?.value || "all";
  }

  function renderSavedSearchSelect() {
    const sel = document.getElementById("saved-search-select");
    const delBtn = document.getElementById("delete-search-btn");
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML =
      '<option value="">Saved searches…</option>' +
      savedSearches
        .map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`)
        .join("");
    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
    if (delBtn) delBtn.hidden = !sel.value;
  }

  async function refreshUserData() {
    if (window.JobBoardsStatic && window.JobBoardsStore) {
      const data = JobBoardsStore.userDataSnapshot();
      savedSearches = data.saved_searches || [];
      renderSavedSearchSelect();
      return data;
    }
    try {
      const res = await fetch("/api/user-data", { cache: "no-store" });
      const data = await res.json();
      savedSearches = data.saved_searches || [];
      renderSavedSearchSelect();
      return data;
    } catch {
      return null;
    }
  }

  function buildSearchPayload() {
    const filters = window.JobBoardsFilters?.getStack() || [];
    return {
      source: document.getElementById("source-filter")?.value || "all",
      sort: document.getElementById("sort-filter")?.value || "posted_at",
      order: document.getElementById("order-filter")?.value || "desc",
      view: currentView(),
      filters: filters.map((f) => {
        const copy = { type: f.type, label: f.label };
        if (f.value) copy.value = f.value;
        if (f.bounds) copy.bounds = f.bounds;
        if (f.field) copy.field = f.field;
        if (f.from) copy.from = f.from;
        if (f.to) copy.to = f.to;
        return copy;
      }),
    };
  }

  function applySavedSearch(searchId) {
    const search = savedSearches.find((s) => s.id === searchId);
    if (!search || !window.JobBoardsFilters) return;
    const payload = search.payload || {};
    const sourceEl = document.getElementById("source-filter");
    const sortEl = document.getElementById("sort-filter");
    const orderEl = document.getElementById("order-filter");
    const viewEl = document.getElementById("view-filter");
    if (sourceEl) sourceEl.value = payload.source || "all";
    if (sortEl) sortEl.value = payload.sort || "posted_at";
    if (orderEl) orderEl.value = payload.order || "desc";
    if (viewEl) viewEl.value = payload.view || "all";
    JobBoardsFilters.setStack(payload.filters || []);
    const dateFilter = (payload.filters || []).find((f) => f.type === "date");
    if (dateRangeCtrl) {
      if (dateFilter) dateRangeCtrl.setFromFilter(dateFilter);
      else dateRangeCtrl.resetToFull();
    }
    history.replaceState(null, "", JobBoardsFilters.toUrl());
    scheduleReloadResults({ resetFit: true });
  }

  async function saveCurrentSearch() {
    const name = window.prompt("Name this search:");
    if (!name || !name.trim()) return;
    try {
      if (window.JobBoardsStatic && window.JobBoardsStore) {
        const entry = {
          id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
          name: name.trim(),
          payload: buildSearchPayload(),
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        savedSearches = JobBoardsStore.saveSearch(entry);
        renderSavedSearchSelect();
        const sel = document.getElementById("saved-search-select");
        if (sel) sel.value = entry.id;
        const delBtn = document.getElementById("delete-search-btn");
        if (delBtn) delBtn.hidden = false;
        return;
      }
      const res = await fetch("/api/saved-searches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "save", name: name.trim(), payload: buildSearchPayload() }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Could not save search");
      }
      const data = await res.json();
      savedSearches = data.saved_searches || [];
      renderSavedSearchSelect();
      const sel = document.getElementById("saved-search-select");
      if (sel && data.search?.id) sel.value = data.search.id;
      const delBtn = document.getElementById("delete-search-btn");
      if (delBtn) delBtn.hidden = false;
    } catch (err) {
      window.alert(err.message || "Could not save search.");
    }
  }

  async function deleteSelectedSearch() {
    const sel = document.getElementById("saved-search-select");
    if (!sel?.value) return;
    if (!window.confirm("Delete this saved search?")) return;
    try {
      if (window.JobBoardsStatic && window.JobBoardsStore) {
        savedSearches = JobBoardsStore.deleteSavedSearch(sel.value);
        sel.value = "";
        renderSavedSearchSelect();
        return;
      }
      const res = await fetch("/api/saved-searches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "delete", id: sel.value }),
      });
      if (!res.ok) throw new Error("Could not delete search");
      const data = await res.json();
      savedSearches = data.saved_searches || [];
      sel.value = "";
      renderSavedSearchSelect();
    } catch (err) {
      window.alert(err.message || "Could not delete search.");
    }
  }

  async function mutateSavedJob(jobId, save) {
    if (window.JobBoardsStatic && window.JobBoardsStore) {
      if (save) JobBoardsStore.saveJob(jobId);
      else JobBoardsStore.unsaveJob(jobId);
      const job = allJobsCache.find((j) => j.id === jobId);
      if (job) job.is_saved = save;
      if (currentView() === "saved" && !save) {
        scheduleReloadResults({ quiet: true });
        return;
      }
      const btn = document.querySelector(`.job-card-wrap[data-job-id="${jobId}"] .job-card-save`);
      if (btn) {
        btn.classList.toggle("is-saved", save);
        btn.textContent = save ? "★" : "☆";
        btn.title = save ? "Unsave job" : "Save job";
        btn.setAttribute("aria-label", save ? "Unsave job" : "Save job");
      }
      if (currentView() === "saved") applyDisplay();
      return;
    }
    const res = await fetch("/api/saved-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, action: save ? "save" : "unsave" }),
    });
    if (!res.ok) throw new Error("Could not update saved job");
    const job = allJobsCache.find((j) => j.id === jobId);
    if (job) job.is_saved = save;
    if (currentView() === "saved" && !save) {
      scheduleReloadResults({ quiet: true });
      return;
    }
    const btn = document.querySelector(`.job-card-wrap[data-job-id="${jobId}"] .job-card-save`);
    if (btn) {
      btn.classList.toggle("is-saved", save);
      btn.textContent = save ? "★" : "☆";
      btn.title = save ? "Unsave job" : "Save job";
      btn.setAttribute("aria-label", save ? "Unsave job" : "Save job");
    }
    if (currentView() === "saved") applyDisplay();
  }

  async function mutateDismissedJob(jobId, dismiss) {
    if (window.JobBoardsStatic && window.JobBoardsStore) {
      if (dismiss) JobBoardsStore.dismissJob(jobId);
      else JobBoardsStore.restoreJob(jobId);
      scheduleReloadResults({ quiet: true });
      return;
    }
    const res = await fetch("/api/dismissed-jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, action: dismiss ? "dismiss" : "restore" }),
    });
    if (!res.ok) throw new Error("Could not update listing");
    scheduleReloadResults({ quiet: true });
  }

  function onViewFilterChange() {
    applyDisplay();
    scheduleReloadResults({ resetFit: true, immediate: true });
  }

  function emptyListMessage(hasArea) {
    const view = currentView();
    if (view === "saved") return "No saved jobs yet. Star listings to save them.";
    if (view === "dismissed") return "No dismissed listings.";
    if (hasArea) return "No jobs in the selected map area.";
    return "No jobs match your filters.";
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
      "Saved",
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
      job.is_saved ? "yes" : "",
    ]);

    const csv = [headers, ...rows].map((row) => row.map(csvEscape).join(",")).join("\r\n");
    const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const view = currentView();
    const viewPart = view === "all" ? "" : `-${view}`;
    link.href = url;
    link.download = `job-boards${viewPart}-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function renderFilterStack(filters) {
    const wrap = document.getElementById("filter-stack-wrap");
    const el = document.getElementById("filter-stack");
    if (!wrap || !el) return;
    wrap.hidden = !filters.length;
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
  }

  function restoreMapAreaFromFilters() {
    if (!mapCtrl || !window.JobBoardsFilters) return;
    const area = JobBoardsFilters.getAreaFilter();
    if (area?.bounds) mapCtrl.setAreaBounds(area.bounds);
    else mapCtrl.clearAreaBounds();
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

  function jobMatchesTerm(job, term) {
    const q = term.toLowerCase();
    const hay = [
      job.institution,
      job.subject_area,
      job.title,
      job.location,
      job.notes_raw,
      job.description_raw,
    ]
      .map((s) => (s || "").toLowerCase())
      .join(" ");
    return hay.includes(q);
  }

  function applyClientStackFilters(jobs) {
    const stack = window.JobBoardsFilters?.getStack() || [];
    let out = jobs;
    for (const f of stack) {
      if (f.type === "date") {
        const field = f.field === "apply_by" ? "apply_by" : "posted_at";
        out = out.filter((j) => {
          const raw = j[field];
          if (!raw) return false;
          const day = field === "posted_at" ? raw.slice(0, 10) : raw;
          if (f.from && day < f.from) return false;
          if (f.to && day > f.to) return false;
          return true;
        });
      } else if (f.type === "search" || f.type === "keyword") {
        out = out.filter((j) => jobMatchesTerm(j, f.value));
      }
    }
    return out;
  }

  function getStaticFilterOpts() {
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
      sort: document.getElementById("sort-filter")?.value || "posted_at",
      order: document.getElementById("order-filter")?.value || "desc",
      view: currentView(),
      terms,
      dateRange: dateRange && (dateRange.from || dateRange.to) ? dateRange : null,
      savedIds: JobBoardsStore.getSavedJobIds(),
      dismissedIds: JobBoardsStore.getDismissedJobIds(),
    };
  }

  function getMapJobsForList() {
    if (!window.JobBoardsStatic) return allMapJobsCache;
    const area = window.JobBoardsFilters?.getAreaFilter();
    const visibleIds = new Set(
      JobBoardsStaticQuery.filterJobs(allJobsCache, getStaticFilterOpts()).map((j) => j.id)
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
    let jobs;
    if (window.JobBoardsStatic && window.JobBoardsStaticQuery) {
      jobs = JobBoardsStaticQuery.filterJobs(allJobsCache, getStaticFilterOpts());
    } else {
      jobs = applyClientStackFilters(allJobsCache);
      const view = currentView();
      if (view === "saved") {
        jobs = jobs.filter((j) => j.is_saved);
      } else if (view === "dismissed") {
        jobs = jobs.filter((j) => j.is_dismissed);
      }
    }

    if (!window.JobBoardsFilters?.getAreaFilter()) {
      return jobs;
    }
    const ids = new Set(getMapJobsForList().map((j) => j.id));
    return jobs.filter((j) => ids.has(j.id));
  }

  function updateMapFootnote() {
    const footnote = document.getElementById("map-footnote");
    if (!footnote) return;
    const mapped = window.JobBoardsStatic ? getMapJobsForList().length : allMapJobsCache.length;
    const missing = mapStats.missing;
    const filteredTotal = window.JobBoardsStatic
      ? JobBoardsStaticQuery.filterJobs(allJobsCache, getStaticFilterOpts()).length
      : allJobsCache.length;
    const filterCount = window.JobBoardsFilters?.getStack().length || 0;
    const filterNote = filterCount
      ? ` · ${filterCount} active filter${filterCount === 1 ? "" : "s"}`
      : "";
    const hasArea = !!window.JobBoardsFilters?.getAreaFilter();
    const listCount = listJobsForDisplay().length;

    if (hasArea) {
      footnote.textContent = listCount
        ? `${listCount} job${listCount === 1 ? "" : "s"} in the selected area`
          + (filteredTotal > listCount
            ? ` (${filteredTotal - listCount} outside area or not on map)`
            : "")
        : filteredTotal
          ? `${filteredTotal} matching job${filteredTotal === 1 ? "" : "s"}, but none are on the map in this area yet.`
          : "No jobs match the current filters.";
      return;
    }

    footnote.textContent = mapped
      ? `Showing ${mapped} of ${filteredTotal} filtered job${filteredTotal === 1 ? "" : "s"} on the map`
        + (missing ? ` (${missing} not geocoded yet)` : "")
        + filterNote
      : filteredTotal
        ? `${filteredTotal} filtered job${filteredTotal === 1 ? "" : "s"} found, but none are geocoded yet.${filterNote}`
        : "No jobs match the current filters.";
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
      mapCtrl.setMarkers(window.JobBoardsStatic ? getMapJobsForList() : allMapJobsCache, {
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

  function buildListParams(source, sort, order) {
    const params = window.JobBoardsFilters
      ? JobBoardsFilters.buildApiParams(source, sort, order)
      : new URLSearchParams({ source, sort, order });
    const view = currentView();
    if (view !== "all") params.set("view", view);
    params.delete("bbox");
    return params;
  }

  let resultsInFlight = false;
  let pendingReloadOpts = null;
  let pendingFilterReload = false;
  let reloadTimer = null;

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
      note.textContent = `Static site · listings updated ${formatLastUpdated(meta.generated_at)}`;
    }
    allJobsCache = JobBoardsStore.attachUserFlags(jobsData.jobs || []);
    allMapJobsCache = mapData.jobs || [];
    mapStats = {
      mapped: mapData.mapped || allMapJobsCache.length,
      missing: mapData.missing || 0,
      filteredTotal: allJobsCache.length,
    };
    jobsLoadedOnce = true;
    hasCache = allJobsCache.length > 0;
  }

  async function reloadResultsStatic(opts = {}) {
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
      JobBoardsStore.attachUserFlags(allJobsCache);
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

  async function reloadResults(opts = {}) {
    if (window.JobBoardsStatic) {
      return reloadResultsStatic(opts);
    }
    const list = document.getElementById("jobs-list");
    const footnote = document.getElementById("map-footnote");
    if (!list || window.JobBoardsPage !== "index") return;

    if (resultsInFlight) {
      pendingReloadOpts = { ...(pendingReloadOpts || {}), ...opts };
      return;
    }

    const quiet = opts.quiet === true;
    const source = document.getElementById("source-filter")?.value || "all";
    const sort = document.getElementById("sort-filter")?.value || "posted_at";
    const order = document.getElementById("order-filter")?.value || "desc";
    const hasArea = !!window.JobBoardsFilters?.getAreaFilter();

    if (!quiet && !list.querySelector(".job-card")) {
      list.innerHTML = '<p class="empty-state">Loading jobs…</p>';
      updateResultCount(null, true);
    } else if (!quiet) {
      updateResultCount(listJobsForDisplay().length);
    }
    if (!quiet && footnote) {
      footnote.textContent = list.querySelector(".job-card")
        ? "Updating map…"
        : "Loading map…";
    }
    if (opts.resetFit && mapCtrl && !hasArea) mapCtrl.resetFit();

    const listParams = buildListParams(source, sort, order);
    const mapParams = window.JobBoardsFilters
      ? JobBoardsFilters.buildApiParams(source, sort, order)
      : new URLSearchParams({ source, sort, order });
    const view = currentView();
    if (view !== "all") mapParams.set("view", view);

    resultsInFlight = true;
    loadInFlight = true;
    try {
      const jobsRes = await fetch("/api/jobs?" + listParams, { cache: "no-store" });
      if (!jobsRes.ok) throw new Error("jobs fetch failed");
      const jobsData = await jobsRes.json();
      updateStats(jobsData.stats);
      jobsLoadedOnce = true;
      allJobsCache = jobsData.jobs || [];
      applyDisplay({ focusId: opts.focusId });

      if (mapCtrl) {
        mapInFlight = true;
        if (footnote) footnote.textContent = "Updating map…";
        try {
          const mapRes = await fetch("/api/map-jobs?" + mapParams, { cache: "no-store" });
          if (!mapRes.ok) throw new Error("map fetch failed");
          const mapData = await mapRes.json();
          allMapJobsCache = mapData.jobs || [];
          mapStats = {
            mapped: mapData.mapped || 0,
            missing: mapData.missing || 0,
            filteredTotal: allJobsCache.length,
          };
          applyDisplay({ focusId: opts.focusId });
        } catch {
          if (footnote) footnote.textContent = "Map could not be updated.";
        } finally {
          mapInFlight = false;
        }
      }
    } catch {
      list.innerHTML = '<p class="empty-state">Failed to load jobs.</p>';
      if (footnote) footnote.textContent = "Failed to load map data.";
      updateResultCount(0);
    } finally {
      resultsInFlight = false;
      loadInFlight = false;
      if (pendingReloadOpts) {
        const next = pendingReloadOpts;
        pendingReloadOpts = null;
        scheduleReloadResults(next);
      }
    }
  }

  function onFiltersChanged(filters) {
    renderFilterStack(filters);
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
      const actionBtn = e.target.closest(".job-card-action[data-action]");
      if (actionBtn) {
        e.preventDefault();
        e.stopPropagation();
        const jobId = actionBtn.dataset.jobId;
        const action = actionBtn.dataset.action;
        if (action === "save") {
          const save = !actionBtn.classList.contains("is-saved");
          mutateSavedJob(jobId, save).catch(() => window.alert("Could not update saved job."));
        } else if (action === "dismiss") {
          mutateDismissedJob(jobId, true).catch(() => window.alert("Could not dismiss listing."));
        } else if (action === "restore") {
          mutateDismissedJob(jobId, false).catch(() => window.alert("Could not restore listing."));
        }
        return;
      }

      const btn = e.target.closest(".job-card-locate");
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      const jobId = btn.dataset.jobId;
      if (!focusJobOnMap(jobId)) {
        const footnote = document.getElementById("map-footnote");
        if (footnote) footnote.textContent = "This listing is not on the map yet (still geocoding).";
      }
    });

    list.addEventListener("mouseover", (e) => {
      const wrap = e.target.closest(".job-card-wrap");
      if (!wrap || !mapCtrl) return;
      const jobId = wrap.dataset.jobId;
      if (jobId && mapCtrl.hasJob(jobId)) mapCtrl.highlightJob(jobId);
    });
  }

  async function loadJobs(opts = {}) {
    return reloadResults(opts);
  }

  async function loadMap(opts = {}) {
    return reloadResults(opts);
  }

  function scheduleMapLoad(opts = {}) {
    clearTimeout(mapRefreshTimer);
    mapRefreshTimer = setTimeout(() => reloadResults(opts), opts.immediate ? 0 : 250);
  }

  function initIndexMap() {
    const el = document.getElementById("job-map");
    if (!el || !window.JobBoardsMap || !window.L) return;
    mapCtrl = JobBoardsMap.create(el, { areaSelect: true });
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
    wireJobsListMapEvents();
    restoreMapAreaFromFilters();
    if (!window.JobBoardsStatic) {
      setInterval(() => scheduleReloadResults({ quiet: true }), 45000);
    }
  }

  function initDetailMap() {
    const el = document.getElementById("job-detail-map");
    const geo = window.JobBoardsJobGeo;
    if (!el || !geo || !window.JobBoardsMap || !window.L) return;
    const ctrl = JobBoardsMap.create(el);
    ctrl.showSingle(geo, 13);
  }

  function applyScrapeUI(data) {
    if (window.JobBoardsStatic) {
      if (data?.stats) updateStats(data.stats);
      if (data?.last_fetched_at && lastUpdated) {
        lastUpdated.textContent = formatLastUpdated(data.last_fetched_at);
      }
      return;
    }
    const active = !!data.running || ["starting", "ecoevojobs", "evoldir", "sciencecareers"].includes(data.phase);
    scrapeRunning = active;
    if (active) {
      progressWanted = true;
      updateProgressUI(data);
      showBlockingLoad(false);
      showProgressBanner(true);
      setStatsBarRefreshing(true);
      if (data.batch_stats) updateStats(data.batch_stats);
    } else {
      progressWanted = false;
      showBlockingLoad(false);
      setStatsBarRefreshing(false);
      if (data.stats) updateStats(data.stats);
      if (data.error && !progressHidden) {
        showProgressBanner(true);
        if (progressMessage) progressMessage.textContent = data.message;
        if (progressBarFill) progressBarFill.style.width = "0%";
      } else {
        showProgressBanner(false);
      }
      if (data.has_cache) hasCache = true;
      maybeRefreshJobs(data);
      if (pendingFilterReload && !active) {
        pendingFilterReload = false;
        scheduleReloadResults({ resetFit: !JobBoardsFilters?.getAreaFilter() });
      }
      if (data.stats?.last_fetched_at && lastUpdated) {
        lastUpdated.textContent = formatLastUpdated(data.stats.last_fetched_at);
      }
    }
  }

  async function pollStatus() {
    let delay = POLL_MS_IDLE;
    try {
      const res = await fetch("/api/status", { cache: "no-store" });
      const data = await res.json();
      applyScrapeUI(data);
      delay = data.running || ["starting", "ecoevojobs", "evoldir", "sciencecareers"].includes(data.phase)
        ? POLL_MS_RUNNING
        : POLL_MS_IDLE;
    } catch {
      delay = POLL_MS_IDLE;
    }
    pollTimer = setTimeout(pollStatus, delay);
  }

  function startStatusPolling() {
    if (window.JobBoardsStatic) return;
    if (pollTimer) return;
    pollStatus();
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

  if (progressHideBtn) {
    progressHideBtn.addEventListener("click", () => setProgressHidden(true));
  }

  if (themeToggle) {
    applyTheme(currentTheme());
    themeToggle.addEventListener("click", toggleTheme);
  }

  ["source-filter", "sort-filter", "order-filter"].forEach((id) => {
    document.getElementById(id)?.addEventListener("change", () => {
      scheduleReloadResults({ resetFit: true });
    });
  });

  document.getElementById("save-search-btn")?.addEventListener("click", saveCurrentSearch);
  document.getElementById("delete-search-btn")?.addEventListener("click", deleteSelectedSearch);
  document.getElementById("saved-search-select")?.addEventListener("change", (e) => {
    const delBtn = document.getElementById("delete-search-btn");
    if (delBtn) delBtn.hidden = !e.target.value;
    if (e.target.value) applySavedSearch(e.target.value);
  });

  const searchInput = document.getElementById("search-input");
  if (searchInput) {
    searchInput.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || (!window.JobBoardsStatic && scrapeRunning) || !window.JobBoardsFilters) return;
      e.preventDefault();
      const val = searchInput.value.trim();
      if (!val) return;
      JobBoardsFilters.add({ type: "search", value: val });
      searchInput.value = "";
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (window.JobBoardsStatic) {
      if (progressBanner) progressBanner.hidden = true;
      if (overlay) overlay.hidden = true;
      if (window.JobBoardsFilters) {
        const origToUrl = JobBoardsFilters.toUrl.bind(JobBoardsFilters);
        JobBoardsFilters.toUrl = function () {
          const raw = origToUrl();
          const qs = raw.startsWith("/?") ? raw.slice(2) : raw.replace(/^\//, "");
          return qs ? JobBoardsPageUrl(`index.html?${qs}`) : JobBoardsPageUrl("index.html");
        };
      }
    }
    if (window.JobBoardsPage === "index") {
      startStatusPolling();
      refreshUserData();
      initIndexMap();
      if (window.JobBoardsDateRange) {
        dateRangeCtrl = JobBoardsDateRange.create(document.getElementById("date-range-panel"));
      }
      if (window.JobBoardsFilters) {
        const initial =
          window.JobBoardsInitialFilters?.length
            ? window.JobBoardsInitialFilters
            : JobBoardsFilters.parseUrl();
        JobBoardsFilters.onChange(onFiltersChanged);
        JobBoardsFilters.init(initial);
      } else if (!hasCache) {
        loadJobs();
      } else {
        loadJobs({ quiet: true });
      }
      document.getElementById("view-filter")?.addEventListener("change", onViewFilterChange);
      document.getElementById("export-csv-btn")?.addEventListener("click", exportVisibleJobsCsv);
    }
    if (window.JobBoardsPage === "detail" && !window.JobBoardsStatic) initDetailMap();
    if (window.JobBoardsPage !== "index") {
      if (window.JobBoardsStatic) {
        fetch(JobBoardsDataUrl("meta.json"), { cache: "no-store" })
          .then((r) => r.json())
          .then((meta) => applyScrapeUI({ stats: meta.stats, last_fetched_at: meta.last_fetched_at }))
          .catch(() => {});
      } else {
        fetch("/api/status", { cache: "no-store" })
          .then((r) => r.json())
          .then(applyScrapeUI)
          .catch(() => {});
      }
    }
  });
})();
