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
    let out = jobs;
    out = out.filter((j) => matchesSource(j, opts.source));
    out = out.filter((j) => matchesTerms(j, opts.terms));
    out = out.filter((j) => matchesDate(j, opts.dateRange));
    return sortJobs(out, opts.sort, opts.order);
  }

  window.JobBoardsStaticQuery = {
    filterJobs,
    jobMatchesTerm,
  };
})();
