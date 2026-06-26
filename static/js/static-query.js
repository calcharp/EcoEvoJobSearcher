(function () {
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

  function jobSources(job) {
    return job.sources || [job.source].filter(Boolean);
  }

  function matchesSource(job, source) {
    if (!source || source === "all") return true;
    return jobSources(job).includes(source);
  }

  function matchesTerms(job, terms) {
    if (!terms || !terms.length) return true;
    return terms.every((term) => jobMatchesTerm(job, term));
  }

  function matchesDate(job, dateRange) {
    if (!dateRange) return true;
    const field = dateRange.field === "apply_by" ? "apply_by" : "posted_at";
    const raw = job[field];
    if (!raw) return false;
    const day = field === "posted_at" ? raw.slice(0, 10) : raw;
    if (dateRange.from && day < dateRange.from) return false;
    if (dateRange.to && day > dateRange.to) return false;
    return true;
  }

  function compareValues(a, b) {
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    if (typeof a === "number" && typeof b === "number") return a - b;
    return String(a).localeCompare(String(b), undefined, { sensitivity: "base" });
  }

  function sortJobs(jobs, sort, order) {
    const col = sort || "posted_at";
    const desc = (order || "desc").toLowerCase() === "desc";
    return [...jobs].sort((a, b) => {
      const cmp = compareValues(a[col], b[col]);
      return desc ? -cmp : cmp;
    });
  }

  function filterJobs(jobs, opts) {
    const view = opts.view || "all";
    const saved = new Set(opts.savedIds || []);
    const dismissed = new Set(opts.dismissedIds || []);
    let out = jobs;

    if (view === "saved") {
      out = out.filter((j) => saved.has(j.id) && !dismissed.has(j.id));
    } else if (view === "dismissed") {
      out = out.filter((j) => dismissed.has(j.id));
    } else {
      out = out.filter((j) => !dismissed.has(j.id));
    }

    out = out.filter((j) => matchesSource(j, opts.source));
    out = out.filter((j) => matchesTerms(j, opts.terms));
    out = out.filter((j) => matchesDate(j, opts.dateRange));
    return sortJobs(out, opts.sort, opts.order);
  }

  function filterMapJobs(mapJobs, jobIds) {
    const ids = jobIds instanceof Set ? jobIds : new Set(jobIds);
    return mapJobs.filter((j) => ids.has(j.id));
  }

  function filterCloudTerms(terms, prefs) {
    const ignore = new Set((prefs.ignore || []).map((p) => p.toLowerCase()));
    const watch = new Set((prefs.watch || []).map((p) => p.toLowerCase()));
    const out = [];
    const seen = new Set();

    for (const item of terms || []) {
      const key = String(item.term || "").toLowerCase();
      if (!key || ignore.has(key) || seen.has(key)) continue;
      seen.add(key);
      out.push({
        term: item.term,
        count: item.count || 0,
        watch: watch.has(key) || !!item.watch,
      });
    }

    for (const phrase of prefs.watch || []) {
      const key = phrase.toLowerCase();
      if (ignore.has(key) || seen.has(key)) continue;
      seen.add(key);
      const existing = (terms || []).find((t) => String(t.term).toLowerCase() === key);
      out.push({
        term: phrase,
        count: existing ? existing.count || 0 : 0,
        watch: true,
      });
    }

    out.sort((a, b) => b.count - a.count || String(a.term).localeCompare(String(b.term)));
    return out;
  }

  window.JobBoardsStaticQuery = {
    filterJobs,
    filterMapJobs,
    filterCloudTerms,
    jobMatchesTerm,
  };
})();
