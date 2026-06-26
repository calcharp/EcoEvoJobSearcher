(function () {
  const KEYS = {
    saved: "jobboards-saved-jobs",
    dismissed: "jobboards-dismissed-jobs",
    searches: "jobboards-saved-searches",
    watch: "jobboards-phrase-watch",
    ignore: "jobboards-phrase-ignore",
  };

  function readJson(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch {
      return fallback;
    }
  }

  function writeJson(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
  }

  function dedupePhrases(list) {
    const seen = new Set();
    const out = [];
    for (const phrase of list || []) {
      const clean = String(phrase || "").trim();
      if (!clean) continue;
      const key = clean.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(clean);
    }
    return out;
  }

  function attachUserFlags(jobs) {
    const saved = new Set(getSavedJobIds());
    const dismissed = new Set(getDismissedJobIds());
    for (const job of jobs) {
      job.is_saved = saved.has(job.id);
      job.is_dismissed = dismissed.has(job.id);
    }
    return jobs;
  }

  function getSavedJobIds() {
    return readJson(KEYS.saved, []);
  }

  function getDismissedJobIds() {
    return readJson(KEYS.dismissed, []);
  }

  function saveJob(jobId) {
    const ids = getSavedJobIds();
    if (!ids.includes(jobId)) {
      ids.push(jobId);
      writeJson(KEYS.saved, ids);
    }
  }

  function unsaveJob(jobId) {
    writeJson(KEYS.saved, getSavedJobIds().filter((id) => id !== jobId));
  }

  function dismissJob(jobId) {
    const ids = getDismissedJobIds();
    if (!ids.includes(jobId)) {
      ids.push(jobId);
      writeJson(KEYS.dismissed, ids);
    }
  }

  function restoreJob(jobId) {
    writeJson(KEYS.dismissed, getDismissedJobIds().filter((id) => id !== jobId));
  }

  function listSavedSearches() {
    return readJson(KEYS.searches, []);
  }

  function saveSearch(entry) {
    const searches = listSavedSearches();
    const idx = searches.findIndex((s) => s.id === entry.id);
    if (idx >= 0) searches[idx] = entry;
    else searches.push(entry);
    writeJson(KEYS.searches, searches);
    return searches;
  }

  function deleteSavedSearch(id) {
    const searches = listSavedSearches().filter((s) => s.id !== id);
    writeJson(KEYS.searches, searches);
    return searches;
  }

  function getPhrasePrefs() {
    return {
      watch: dedupePhrases(readJson(KEYS.watch, [])),
      ignore: dedupePhrases(readJson(KEYS.ignore, [])),
    };
  }

  function updatePhrasePrefs(action, phrase) {
    const clean = String(phrase || "").trim();
    if (!clean) throw new Error("phrase required");
    const prefs = getPhrasePrefs();
    let watch = [...prefs.watch];
    let ignore = [...prefs.ignore];
    const key = clean.toLowerCase();

    if (action === "watch") {
      ignore = ignore.filter((p) => p.toLowerCase() !== key);
      if (!watch.some((p) => p.toLowerCase() === key)) watch.push(clean);
    } else if (action === "ignore") {
      watch = watch.filter((p) => p.toLowerCase() !== key);
      if (!ignore.some((p) => p.toLowerCase() === key)) ignore.push(clean);
    } else if (action === "unwatch") {
      watch = watch.filter((p) => p.toLowerCase() !== key);
    } else if (action === "unignore") {
      ignore = ignore.filter((p) => p.toLowerCase() !== key);
    } else {
      throw new Error("unknown action");
    }

    writeJson(KEYS.watch, dedupePhrases(watch));
    writeJson(KEYS.ignore, dedupePhrases(ignore));
    return getPhrasePrefs();
  }

  function userDataSnapshot() {
    return {
      saved_job_ids: getSavedJobIds(),
      dismissed_job_ids: getDismissedJobIds(),
      saved_searches: listSavedSearches(),
    };
  }

  window.JobBoardsStore = {
    attachUserFlags,
    getSavedJobIds,
    getDismissedJobIds,
    saveJob,
    unsaveJob,
    dismissJob,
    restoreJob,
    listSavedSearches,
    saveSearch,
    deleteSavedSearch,
    getPhrasePrefs,
    updatePhrasePrefs,
    userDataSnapshot,
  };
})();
