(function () {
  function xmlEscape(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&apos;");
  }

  function absoluteUrl(path) {
    try {
      return new URL(path, window.location.href).href;
    } catch {
      return path;
    }
  }

  function rfc822(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toUTCString();
  }

  function jobTitle(job) {
    return job.subject_area || job.title || job.institution || "Job listing";
  }

  function jobLink(job) {
    if (job.url) return job.url;
    return absoluteUrl(JobBoardsJobUrl(job.id));
  }

  function jobSummary(job) {
    const bits = [
      job.institution,
      job.location,
      job.rank_or_pi || job.position_type,
      job.apply_display ? `Apply by ${job.apply_display}` : job.apply_by ? `Apply by ${job.apply_by}` : "",
      job.posted_display ? `Posted ${job.posted_display}` : "",
    ].filter(Boolean);
    return bits.join(" · ");
  }

  function queryOpts(stack, view) {
    const clauses = [];
    let dateRange = null;
    for (const f of stack || []) {
      if (f.type === "clause") {
        const phrase = String(f.phrase || f.value || "").trim();
        const expanded = phrase ? window.JobBoardsSearchSuggest?.expand(phrase) : null;
        clauses.push({
          phrase,
          source:
            f.source === "ecoevojobs" || f.source === "evoldir" || f.source === "sciencecareers"
              ? f.source
              : "all",
          join: f.join === "AND" ? "AND" : "OR",
          variants: expanded && expanded.length ? expanded : phrase ? [phrase] : [],
        });
      }
      if (f.type === "date") {
        dateRange = {
          field: f.field === "apply_by" ? "apply_by" : "posted_at",
          from: f.from || "",
          to: f.to || "",
        };
      }
    }
    return {
      source: "all",
      sort: view.sort || "apply_by",
      order: view.order || "asc",
      clauses,
      dateRange: dateRange && (dateRange.from || dateRange.to) ? dateRange : null,
      openOnly: (stack || []).some((f) => f.type === "open"),
      recentOnly: (stack || []).some((f) => f.type === "recent"),
    };
  }

  function applyArea(jobs, bounds, mapJobs) {
    if (!bounds) return jobs;
    const byId = new Map((mapJobs || []).map((j) => [j.id, j]));
    return jobs.filter((j) => {
      const g = j.map_geo || byId.get(j.id);
      if (g == null || g.lat == null || g.lon == null) return false;
      return (
        bounds.south <= g.lat &&
        g.lat <= bounds.north &&
        bounds.west <= g.lon &&
        g.lon <= bounds.east
      );
    });
  }

  function feedTitle(stack) {
    const phrases = (stack || [])
      .filter((f) => f.type === "clause")
      .map((f) => String(f.phrase || "").trim())
      .filter(Boolean);
    if (phrases.length) return `Eco & Evo Jobs — ${phrases.join(", ")}`;
    return "Eco & Evo Jobs";
  }

  function feedDescription(opts, count) {
    const bits = [];
    if (opts.openOnly) bits.push("open applications");
    if (opts.recentOnly) bits.push("posted today or yesterday");
    if (opts.dateRange) {
      const name = opts.dateRange.field === "apply_by" ? "deadline" : "posted";
      bits.push(`${name} ${opts.dateRange.from || "…"} – ${opts.dateRange.to || "…"}`);
    }
    const n = count === 1 ? "1 job" : `${count} jobs`;
    return bits.length ? `${n} matching ${bits.join(", ")}.` : `${n} from Eco & Evo Jobs.`;
  }

  function buildRss(jobs, stack, opts) {
    const searchUrl = absoluteUrl(
      JobBoardsPageUrl("index.html") + (window.location.search || "")
    );
    const now = new Date().toUTCString();
    const items = jobs
      .map((job) => {
        const pub = rfc822(job.posted_at || job.updated_at);
        return `    <item>
      <title>${xmlEscape(jobTitle(job))}</title>
      <link>${xmlEscape(jobLink(job))}</link>
      <guid isPermaLink="false">${xmlEscape(job.id)}</guid>
      ${pub ? `<pubDate>${xmlEscape(pub)}</pubDate>` : ""}
      <description>${xmlEscape(jobSummary(job))}</description>
    </item>`;
      })
      .join("\n");
    return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>${xmlEscape(feedTitle(stack))}</title>
    <link>${xmlEscape(searchUrl)}</link>
    <description>${xmlEscape(feedDescription(opts, jobs.length))}</description>
    <lastBuildDate>${xmlEscape(now)}</lastBuildDate>
    <docs>https://www.rssboard.org/rss-specification</docs>
${items}
  </channel>
</rss>
`;
  }

  async function run() {
    try {
      if (window.JobBoardsSearchSuggest?.ready) await JobBoardsSearchSuggest.ready;
      const stack = JobBoardsFilters.parseUrlOrDefaults();
      const view = JobBoardsFilters.parseViewPrefs();
      const opts = queryOpts(stack, view);
      const area = stack.find((f) => f.type === "area");

      const [jobsRes, mapRes] = await Promise.all([
        fetch(JobBoardsDataUrl("jobs.json"), { cache: "no-store" }),
        fetch(JobBoardsDataUrl("map-jobs.json"), { cache: "no-store" }),
      ]);
      if (!jobsRes.ok) throw new Error("jobs fetch failed");
      const jobsData = await jobsRes.json();
      const mapData = mapRes.ok ? await mapRes.json() : { jobs: [] };
      let jobs = JobBoardsStaticQuery.filterJobs(jobsData.jobs || [], opts);
      jobs = applyArea(jobs, area?.bounds, mapData.jobs || []);

      const xml = buildRss(jobs, stack, opts);
      const blob = new Blob([xml], { type: "application/rss+xml;charset=UTF-8" });
      location.replace(URL.createObjectURL(blob));
    } catch (err) {
      document.body.textContent = "Could not build the RSS feed.";
      console.error(err);
    }
  }

  run();
})();
