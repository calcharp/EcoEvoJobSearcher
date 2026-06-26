(function () {
  if (!window.JobBoardsStatic) return;

  function esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function sourceLabel(s) {
    if (s === "ecoevojobs") return "ecoevo";
    if (s === "evoldir") return "evoldir";
    if (s === "sciencecareers") return "Sci Careers";
    return s;
  }

  function deadlineClass(days) {
    if (days == null) return "";
    if (days < 0) return "deadline-past";
    if (days <= 14) return "deadline-soon";
    return "";
  }

  function deadlineLabel(days) {
    if (days == null) return "";
    if (days < 0) return `${-days}d ago`;
    if (days === 0) return "Today";
    return `${days}d left`;
  }

  function renderDetail(job) {
    const root = document.getElementById("job-detail-root");
    if (!root) return;
    if (!job) {
      root.innerHTML = `<p class="empty-state">Job not found. <a href="${JobBoardsPageUrl("index.html")}">Back to all jobs</a></p>`;
      document.title = "Not found — Eco & Evo Jobs";
      return;
    }

    document.title = `${job.institution || "Job"} — Eco & Evo Jobs`;

    const badges = (job.sources || [job.source])
      .filter(Boolean)
      .map((s) => `<span class="badge badge-${s}">${sourceLabel(s)}</span>`)
      .join("");

    const notesHtml = job.notes_thread?.length
      ? job.notes_thread
          .map(
            (note) => `
        <div class="note-item ${note.parentIndex ? "note-reply" : ""}">
          ${note.label !== "intro" ? `<span class="note-badge">${esc(note.label)}</span>` : ""}
          <p>${esc(note.text)}</p>
        </div>`
          )
          .join("")
      : job.notes_raw
        ? `<div class="prose">${esc(job.notes_raw)}</div>`
        : "";

    const mapPane = job.map_geo
      ? `
      <aside class="job-detail-aside">
        <div class="job-map-pane map-panel">
          <div class="preview-pane-header"><h2>Location</h2></div>
          <div id="job-detail-map" class="job-map job-map-detail" role="region" aria-label="Job location map"></div>
        </div>
      </aside>`
      : "";

    root.innerHTML = `
      <div class="job-detail-layout">
        <div class="job-detail-main">
          <header class="job-detail-header">
            <div class="source-badges">${badges}</div>
            <h1 class="job-detail-title">${esc(job.subject_area || job.title || job.institution)}</h1>
            <p class="job-detail-sub">
              ${esc(job.institution || "")}
              ${job.rank_or_pi ? ` · ${esc(job.rank_or_pi)}` : ""}
              ${job.location ? ` · ${esc(job.location)}` : ""}
              ${job.position_type ? ` · ${esc(job.position_type)}` : ""}
            </p>
          </header>
          <div class="detail-meta-grid">
            <div class="meta-item"><span class="meta-label">Posted</span><span class="meta-value">${esc(job.posted_display)}</span></div>
            <div class="meta-item">
              <span class="meta-label">Apply by</span>
              <span class="meta-value ${deadlineClass(job.days_until)}">
                ${esc(job.apply_display)}
                ${job.days_until != null ? `<span class="deadline-chip">${deadlineLabel(job.days_until)}</span>` : ""}
              </span>
            </div>
            ${job.updated_at ? `<div class="meta-item"><span class="meta-label">Updated</span><span class="meta-value">${esc(job.updated_display)}</span></div>` : ""}
            ${job.subject_area ? `<div class="meta-item"><span class="meta-label">Subject</span><span class="meta-value">${esc(job.subject_area)}</span></div>` : ""}
          </div>
          ${job.url ? `<a href="${esc(job.url)}" class="btn btn-primary btn-lg external-link" target="_blank" rel="noopener">Open official posting ↗</a>` : ""}
          ${notesHtml ? `<section class="detail-section"><h2>Community notes</h2>${notesHtml}</section>` : ""}
          ${job.contact_email ? `<section class="detail-section"><h2>Contact</h2><p><a href="mailto:${esc(job.contact_email)}">${esc(job.contact_email)}</a></p></section>` : ""}
        </div>
        ${mapPane}
      </div>`;

    if (job.map_geo && window.JobBoardsMap) {
      window.JobBoardsJobGeo = job.map_geo;
      const ctrl = JobBoardsMap.create(document.getElementById("job-detail-map"));
      ctrl.showSingle(job.map_geo, 13);
    }
  }

  async function loadJob() {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("id");
    if (!id) {
      renderDetail(null);
      return;
    }
    try {
      const res = await fetch(JobBoardsDataUrl("jobs.json"), { cache: "no-store" });
      const data = await res.json();
      const jobs = JobBoardsStore.attachUserFlags(data.jobs || []);
      renderDetail(jobs.find((j) => j.id === id) || null);
    } catch {
      renderDetail(null);
    }
  }

  document.addEventListener("DOMContentLoaded", loadJob);
})();
