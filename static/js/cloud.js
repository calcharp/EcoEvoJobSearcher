(function () {
  const panel = document.getElementById("cloud-panel");
  const cloudMeta = document.getElementById("cloud-meta");

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
      el.style.fontSize = `${sizeFor(count).toFixed(2)}rem`;
      el.style.opacity = String(0.55 + ((count - min) / (max - min || 1)) * 0.45);
      el.style.color = `hsl(${hues[i % hues.length]} 48% ${58 + (count / max) * 12}%)`;
    });
  }

  function renderCloud(terms) {
    if (!panel) return;
    if (!terms.length) {
      panel.innerHTML = '<p class="empty-state">No subject terms found yet.</p>';
      return;
    }

    panel.innerHTML = terms
      .map(
        (item) => `
      <a
        class="cloud-term"
        href="${JobBoardsPageUrl("index.html?kw=" + encodeURIComponent(item.term))}"
        data-count="${item.count}"
        title="${item.count} listing${item.count === 1 ? "" : "s"}"
      >${esc(item.term)}</a>`
      )
      .join("");
    sizeCloudTerms();
  }

  async function loadStaticCloud() {
    try {
      const res = await fetch(JobBoardsDataUrl("subject-cloud.json"), { cache: "no-store" });
      const data = await res.json();
      const terms = data.terms || [];
      renderCloud(terms);
      if (cloudMeta) {
        cloudMeta.textContent = `${terms.length} terms · ${data.total_jobs || 0} listings with subjects`;
      }
    } catch {
      if (panel) panel.innerHTML = '<p class="empty-state">Could not load subject terms.</p>';
    }
  }

  document.addEventListener("DOMContentLoaded", loadStaticCloud);
})();
