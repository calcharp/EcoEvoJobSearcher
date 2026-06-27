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

  function isEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value || "");
  }

  function displayTitle(job) {
    const subject = (job.subject_area || "").trim();
    const title = (job.title || "").trim();
    const institution = (job.institution || "").trim();

    if (job.source === "sciencecareers" && title && title.length < 140) {
      return title;
    }
    if (subject && subject.length <= 120) return subject;
    if (title && title !== institution && title.length < 140) return title;
    if (subject) return subject;
    return title || institution || "Job listing";
  }

  function subtitleParts(job) {
    const parts = [];
    const institution = (job.institution || "").trim();
    if (institution && !isEmail(institution)) parts.push(institution);
    if (job.rank_or_pi && job.rank_or_pi !== job.title) parts.push(job.rank_or_pi);
    if (job.location) parts.push(job.location);
    if (job.position_type) parts.push(job.position_type);
    return parts;
  }

  function renderDetail(job) {
    const root = document.getElementById("job-detail-root");
    if (!root) return;
    if (!job) {
      root.innerHTML = `<p class="empty-state">Job not found. <a href="${JobBoardsPageUrl("index.html")}">Back to all jobs</a></p>`;
      document.title = "Not found — Eco & Evo Jobs";
      return;
    }

    const title = displayTitle(job);
    document.title = `${job.institution && !isEmail(job.institution) ? job.institution : title} — Eco & Evo Jobs`;

    const badges = (job.sources || [job.source])
      .filter(Boolean)
      .map((s) => `<span class="badge badge-${s}">${sourceLabel(s)}</span>`)
      .join("");

    const sub = subtitleParts(job).map(esc).join(" · ");

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

    const descriptionHtml =
      job.description_raw &&
      job.description_raw !== job.notes_raw &&
      job.description_raw !== job.subject_area
        ? `<section class="detail-section"><h2>Description</h2><div class="prose">${esc(job.description_raw)}</div></section>`
        : "";

    const listingOnlyNote =
      job.fetch_status === "listing_only"
        ? `<p class="detail-hint">Dates and full description are on the official Science Careers posting.</p>`
        : "";

    const actionLinks = [
      job.url
        ? `<a href="${esc(job.url)}" class="btn btn-primary btn-lg external-link" target="_blank" rel="noopener">Open official posting ↗</a>`
        : "",
      job.discussion_url
        ? `<a href="${esc(job.discussion_url)}" class="btn btn-ghost btn-lg external-link" target="_blank" rel="noopener">${esc(job.discussion_label || "View on source site")} ↗</a>`
        : "",
    ]
      .filter(Boolean)
      .join("");

    const discussionHint =
      job.source === "ecoevojobs" && job.discussion_url
        ? `<p class="detail-hint">Community notes are added in the <strong>Notes</strong> column on the ecoevojobs spreadsheet. You need edit access to comment there.</p>`
        : job.source === "evoldir" && job.discussion_url
          ? `<p class="detail-hint">EvolDir listings are email archives. Discussion happens on the mailing list, not on the archive page.</p>`
          : "";

    const mapPane = job.map_geo
      ? `
      <div class="job-map-pane map-panel">
        <div class="preview-pane-header"><h2>Location</h2></div>
        <div id="job-detail-map" class="job-map job-map-detail" role="region" aria-label="Job location map"></div>
      </div>`
      : "";

    const previewPane =
      job.has_preview && job.preview_open_url
        ? `
      <div class="job-preview-pane">
        <div class="preview-pane-header">
          <h2>Posting preview</h2>
          <a href="${esc(job.preview_open_url)}" class="preview-open-link" target="_blank" rel="noopener">Open ↗</a>
        </div>
        <iframe
          class="preview-frame"
          src="${esc(job.preview_open_url)}"
          title="Job posting preview"
          loading="lazy"
          sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
        ></iframe>
      </div>`
        : "";

    const aside =
      mapPane || previewPane
        ? `<aside class="job-detail-aside">${mapPane}${previewPane}</aside>`
        : "";

    const showSubjectMeta =
      job.subject_area &&
      job.subject_area !== title &&
      job.subject_area.length <= 120;

    root.innerHTML = `
      <div class="job-detail-layout">
        <div class="job-detail-main">
          <header class="job-detail-header">
            <div class="source-badges">${badges}</div>
            <h1 class="job-detail-title">${esc(title)}</h1>
            ${sub ? `<p class="job-detail-sub">${sub}</p>` : ""}
          </header>
          <div class="detail-meta-grid">
            <div class="meta-item"><span class="meta-label">Posted</span><span class="meta-value">${esc(job.posted_display || "—")}</span></div>
            <div class="meta-item">
              <span class="meta-label">Apply by</span>
              <span class="meta-value ${deadlineClass(job.days_until)}">
                ${esc(job.apply_display || "—")}
                ${job.days_until != null ? `<span class="deadline-chip">${deadlineLabel(job.days_until)}</span>` : ""}
              </span>
            </div>
            ${job.updated_at ? `<div class="meta-item"><span class="meta-label">Updated</span><span class="meta-value">${esc(job.updated_display)}</span></div>` : ""}
            ${showSubjectMeta ? `<div class="meta-item"><span class="meta-label">Subject</span><span class="meta-value">${esc(job.subject_area)}</span></div>` : ""}
            ${job.source_tab ? `<div class="meta-item"><span class="meta-label">Type</span><span class="meta-value">${esc(job.source_tab)}</span></div>` : ""}
            ${job.number_applied != null ? `<div class="meta-item"><span class="meta-label">Applicants</span><span class="meta-value">${esc(job.number_applied)}</span></div>` : ""}
          </div>
          ${listingOnlyNote}
          ${discussionHint}
          ${actionLinks ? `<div class="detail-actions">${actionLinks}</div>` : ""}
          ${notesHtml ? `<section class="detail-section"><h2>Community notes</h2>${notesHtml}</section>` : ""}
          ${descriptionHtml}
          ${job.contact_email ? `<section class="detail-section"><h2>Contact</h2><p><a href="mailto:${esc(job.contact_email)}">${esc(job.contact_email)}</a></p></section>` : ""}
        </div>
        ${aside}
      </div>`;

    if (job.map_geo && window.JobBoardsMap) {
      try {
        window.JobBoardsJobGeo = job.map_geo;
        const mapEl = document.getElementById("job-detail-map");
        const ctrl = JobBoardsMap.create(mapEl);
        if (ctrl) ctrl.showSingle(job.map_geo, 13);
      } catch (_) {
        /* Map is optional; job details should still render */
      }
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
      let job = null;
      const perJobRes = await fetch(JobBoardsDataUrl(`jobs/${encodeURIComponent(id)}.json`), {
        cache: "no-store",
      });
      if (perJobRes.ok) {
        job = await perJobRes.json();
      } else {
        const res = await fetch(JobBoardsDataUrl("jobs.json"), { cache: "no-store" });
        if (!res.ok) throw new Error("jobs fetch failed");
        const data = await res.json();
        job = (data.jobs || []).find((j) => j.id === id) || null;
      }
      if (!job) {
        renderDetail(null);
        return;
      }
      renderDetail(job);
    } catch {
      renderDetail(null);
    }
  }

  document.addEventListener("DOMContentLoaded", loadJob);
})();
