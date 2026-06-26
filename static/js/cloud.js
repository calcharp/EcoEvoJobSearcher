(function () {
  const panel = document.getElementById("cloud-panel");
  const watchList = document.getElementById("watch-list");
  const ignoreList = document.getElementById("ignore-list");
  const cloudMeta = document.getElementById("cloud-meta");
  const addForm = document.getElementById("phrase-add-form");
  const phraseInput = document.getElementById("phrase-input");

  function esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function sizeCloudTerms() {
    if (!panel) return;
    const terms = [...panel.querySelectorAll(".cloud-term")];
    if (!terms.length) return;

    const counts = terms.map((el) => Number(el.dataset.count) || 0);
    const positive = counts.filter((c) => c > 0);
    const min = positive.length ? Math.min(...positive) : 1;
    const max = positive.length ? Math.max(...positive) : 1;
    const minRem = 0.78;
    const maxRem = 2.35;
    const hues = [145, 195, 165, 210, 125, 175, 155, 205];

    function sizeFor(count) {
      if (max === min) return 1.15;
      const t =
        (Math.log(count) - Math.log(min)) /
        (Math.log(max) - Math.log(min));
      return minRem + t * (maxRem - minRem);
    }

    terms.forEach((el, i) => {
      const count = Number(el.dataset.count) || 0;
      if (count === 0) {
        el.style.fontSize = "0.82rem";
        el.style.opacity = "0.45";
        el.style.color = "var(--text-muted)";
        return;
      }
      el.style.fontSize = `${sizeFor(count).toFixed(2)}rem`;
      el.style.opacity = String(0.55 + ((count - min) / (max - min || 1)) * 0.45);
      el.style.color = `hsl(${hues[i % hues.length]} 48% ${58 + (count / max) * 12}%)`;
    });
  }

  function renderChipList(container, phrases, kind, emptyText) {
    if (!container) return;
    if (!phrases.length) {
      container.innerHTML = `<p class="phrase-empty">${emptyText}</p>`;
      return;
    }
    const action = kind === "watch" ? "unwatch" : "unignore";
    const label = kind === "watch" ? "Stop tracking" : "Restore";
    container.innerHTML = phrases
      .map(
        (phrase) => `
      <span class="phrase-chip phrase-chip-${kind}">
        <span>${esc(phrase)}</span>
        <button type="button" class="phrase-chip-btn" data-action="${action}" data-phrase="${esc(phrase)}" title="${label}">×</button>
      </span>`
      )
      .join("");
  }

  function renderCloud(terms) {
    if (!panel) return;
    if (!terms.length) {
      panel.innerHTML = '<p class="empty-state">No subject terms found yet. Try refreshing job data or add phrases above.</p>';
      return;
    }

    panel.innerHTML = terms
      .map(
        (item) => `
      <span class="cloud-term-wrap">
        <a
          class="cloud-term${item.watch ? " cloud-term-watch" : ""}"
          href="${window.JobBoardsStatic ? JobBoardsPageUrl("index.html?kw=" + encodeURIComponent(item.term)) : "/?kw=" + encodeURIComponent(item.term)}"
          data-count="${item.count}"
          data-term="${esc(item.term)}"
          title="${item.count} listing${item.count === 1 ? "" : "s"}"
        >${esc(item.term)}</a>
        <button type="button" class="cloud-term-hide" data-action="ignore" data-phrase="${esc(item.term)}" title="Hide from cloud">×</button>
      </span>`
      )
      .join("");
    sizeCloudTerms();
  }

  let cloudTermsCache = [];

  async function mutatePhrase(action, phrase) {
    if (window.JobBoardsStatic && window.JobBoardsStore) {
      const prefs = JobBoardsStore.updatePhrasePrefs(action, phrase);
      return {
        prefs,
        terms: JobBoardsStaticQuery.filterCloudTerms(cloudTermsCache, prefs),
        total_jobs: cloudTermsCache._totalJobs || 0,
      };
    }
    const res = await fetch("/api/subject-phrases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, phrase }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || "Request failed");
    }
    return res.json();
  }

  async function applyUpdate(data) {
    renderChipList(watchList, data.prefs.watch, "watch", "No tracked phrases yet.");
    renderChipList(ignoreList, data.prefs.ignore, "ignore", "No hidden phrases.");
    renderCloud(data.terms);
    if (cloudMeta) {
      cloudMeta.textContent = `${data.terms.length} terms · ${data.total_jobs} listings with subjects`;
    }
  }

  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-action][data-phrase]");
    if (!btn) return;
    e.preventDefault();
    const action = btn.dataset.action;
    const phrase = btn.dataset.phrase;
    btn.disabled = true;
    try {
      const data = await mutatePhrase(action, phrase);
      await applyUpdate(data);
    } catch (err) {
      alert(err.message || "Could not update phrase list.");
    } finally {
      btn.disabled = false;
    }
  });

  if (addForm && phraseInput) {
    addForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const phrase = phraseInput.value.trim();
      if (!phrase) return;
      try {
        const data = await mutatePhrase("watch", phrase);
        phraseInput.value = "";
        await applyUpdate(data);
      } catch (err) {
        alert(err.message || "Could not add phrase.");
      }
    });
  }

  async function loadStaticCloud() {
    if (!window.JobBoardsStatic) return;
    try {
      const res = await fetch(JobBoardsDataUrl("subject-cloud.json"), { cache: "no-store" });
      const data = await res.json();
      cloudTermsCache = data.terms || [];
      cloudTermsCache._totalJobs = data.total_jobs || 0;
      const prefs = JobBoardsStore.getPhrasePrefs();
      renderChipList(watchList, prefs.watch, "watch", "No tracked phrases yet.");
      renderChipList(ignoreList, prefs.ignore, "ignore", "No hidden phrases.");
      renderCloud(JobBoardsStaticQuery.filterCloudTerms(cloudTermsCache, prefs));
      if (cloudMeta) {
        cloudMeta.textContent = `${data.terms.length} terms · ${data.total_jobs} listings with subjects`;
      }
    } catch {
      if (panel) panel.innerHTML = '<p class="empty-state">Could not load subject terms.</p>';
    }
  }

  if (window.JobBoardsStatic) {
    document.addEventListener("DOMContentLoaded", loadStaticCloud);
  } else {
    sizeCloudTerms();
  }
})();
