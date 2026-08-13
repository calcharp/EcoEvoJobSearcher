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

  function matchesClause(job, clause) {
    const phrase = String(clause.phrase || "").trim();
    if (phrase) {
      const variants = Array.isArray(clause.variants) && clause.variants.length
        ? clause.variants
        : [phrase];
      if (!variants.some((v) => jobMatchesTerm(job, v))) return false;
    }
    if (!matchesSource(job, clause.source)) return false;
    return true;
  }

  function clauseHasConstraint(clause) {
    return Boolean(
      String(clause.phrase || "").trim() ||
        (clause.source && clause.source !== "all")
    );
  }

  function matchesClauses(job, clauses) {
    const rows = (clauses || []).filter(clauseHasConstraint);
    if (!rows.length) return true;
    let acc = matchesClause(job, rows[0]);
    for (let i = 0; i < rows.length - 1; i++) {
      const next = matchesClause(job, rows[i + 1]);
      acc = rows[i].join === "AND" ? acc && next : acc || next;
    }
    return acc;
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

  function matchesOpen(job, openOnly) {
    if (!openOnly) return true;
    if (job.days_until == null) return true;
    return job.days_until >= 0;
  }

  function localDayString(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function postedLocalDay(job) {
    const raw = job.posted_at;
    if (!raw) return null;
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw;
    const d = new Date(raw);
    if (Number.isNaN(d.getTime())) return null;
    return localDayString(d);
  }

  function matchesRecent(job, recentOnly) {
    if (!recentOnly) return true;
    const day = postedLocalDay(job);
    if (!day) return false;
    const today = new Date();
    const cutoff = new Date(today);
    cutoff.setDate(cutoff.getDate() - 6);
    const todayStr = localDayString(today);
    const cutoffStr = localDayString(cutoff);
    return day >= cutoffStr && day <= todayStr;
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
    let out = jobs;
    out = out.filter((j) => matchesSource(j, opts.source));
    out = out.filter((j) => matchesClauses(j, opts.clauses));
    out = out.filter((j) => matchesDate(j, opts.dateRange));
    out = out.filter((j) => matchesOpen(j, opts.openOnly));
    out = out.filter((j) => matchesRecent(j, opts.recentOnly));
    return sortJobs(out, opts.sort, opts.order);
  }

  window.JobBoardsStaticQuery = {
    filterJobs,
    jobMatchesTerm,
  };
})();
