(function () {
  function parseDay(iso) {
    if (!iso) return null;
    const d = new Date(iso + "T12:00:00");
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function toIsoDay(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function formatDisplay(iso) {
    const d = parseDay(iso);
    if (!d) return iso || "";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }

  function daysBetween(minIso, maxIso) {
    const min = parseDay(minIso);
    const max = parseDay(maxIso);
    if (!min || !max) return 1;
    return Math.max(1, Math.round((max - min) / 86400000));
  }

  function dayIndex(minIso, iso) {
    const min = parseDay(minIso);
    const d = parseDay(iso);
    if (!min || !d) return 0;
    return Math.round((d - min) / 86400000);
  }

  function indexToIso(minIso, maxIso, index) {
    const min = parseDay(minIso);
    const max = parseDay(maxIso);
    if (!min || !max) return minIso;
    const total = daysBetween(minIso, maxIso);
    const clamped = Math.max(0, Math.min(index, total));
    const d = new Date(min.getTime() + clamped * 86400000);
    if (d > max) return maxIso;
    return toIsoDay(d);
  }

  function formatTickLabel(date, spanDays) {
    if (spanDays > 420) {
      return date.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
    }
    if (spanDays > 100) {
      return date.toLocaleDateString(undefined, { month: "short" });
    }
    return date.toLocaleDateString(undefined, { month: "numeric", day: "numeric" });
  }

  function buildTicks(minIso, maxIso) {
    const span = daysBetween(minIso, maxIso);
    const min = parseDay(minIso);
    const max = parseDay(maxIso);
    if (!min || !max || span <= 0) return [];

    const ticks = [];
    const seen = new Set();

    function addTick(iso, major) {
      if (!iso || seen.has(iso)) return;
      const idx = dayIndex(minIso, iso);
      const pct = Math.max(0, Math.min(100, (idx / span) * 100));
      const d = parseDay(iso);
      if (!d) return;
      seen.add(iso);
      ticks.push({
        iso,
        pct,
        major,
        label: formatTickLabel(d, span),
      });
    }

    addTick(minIso, true);

    if (span <= 56) {
      let d = new Date(min);
      d.setDate(d.getDate() + 7);
      while (d < max) {
        addTick(toIsoDay(d), false);
        d.setDate(d.getDate() + 7);
      }
    } else if (span <= 200) {
      let d = new Date(min.getFullYear(), min.getMonth() + 1, 1);
      while (d < max) {
        if (d > min) addTick(toIsoDay(d), d.getMonth() % 2 === 0);
        d.setMonth(d.getMonth() + 1);
      }
    } else {
      let d = new Date(min.getFullYear(), Math.floor(min.getMonth() / 3) * 3 + 3, 1);
      if (d <= min) d.setMonth(d.getMonth() + 3);
      while (d < max) {
        addTick(toIsoDay(d), true);
        d.setMonth(d.getMonth() + 3);
      }
    }

    addTick(maxIso, true);
    return ticks.sort((a, b) => a.pct - b.pct);
  }

  function bucketCount(spanDays) {
    if (spanDays <= 56) return 14;
    if (spanDays <= 200) return 24;
    return 32;
  }

  function binDailyCounts(daily, minIso, maxIso) {
    const span = daysBetween(minIso, maxIso);
    if (!span || !daily?.length) return [];

    const buckets = bucketCount(span);
    const counts = new Array(buckets).fill(0);
    for (const row of daily) {
      const idx = dayIndex(minIso, row.day);
      if (idx < 0 || idx > span) continue;
      const bucket = Math.min(buckets - 1, Math.floor((idx / span) * buckets));
      counts[bucket] += row.count || 0;
    }
    const peak = Math.max(...counts, 1);
    return counts.map((count, i) => ({
      count,
      startIdx: Math.round((i / buckets) * span),
      endIdx: Math.round(((i + 1) / buckets) * span),
      heightPct: Math.max(4, Math.round((count / peak) * 100)),
    }));
  }

  function create(root) {
    if (!root) return null;

    const fieldSelect = root.querySelector("#date-field-select");
    const labelEl = root.querySelector("#date-range-label");
    const track = root.querySelector(".date-range-track");
    const notchesEl = root.querySelector("#date-range-notches");
    const histogramEl = root.querySelector("#date-range-histogram");
    const fill = root.querySelector("#date-range-fill");
    const thumbMin = root.querySelector("#date-thumb-min");
    const thumbMax = root.querySelector("#date-thumb-max");

    let bounds = {};
    let field = "posted_at";
    let minIdx = 0;
    let maxIdx = 0;
    let totalDays = 1;
    let suppressFilter = false;
    let onRangeChange = null;

    function currentBounds() {
      return bounds[field] || {};
    }

    function isFullRange(fromIso, toIso) {
      const b = currentBounds();
      if (!b.min || !b.max) return true;
      return (!fromIso || fromIso <= b.min) && (!toIso || toIso >= b.max);
    }

    function updateLabel() {
      const b = currentBounds();
      if (!b.min || !b.max) {
        labelEl.textContent = "All time";
        return;
      }
      const fromIso = indexToIso(b.min, b.max, minIdx);
      const toIso = indexToIso(b.min, b.max, maxIdx);
      if (isFullRange(fromIso, toIso)) {
        labelEl.textContent = "All time";
      } else {
        labelEl.textContent = `${formatDisplay(fromIso)} – ${formatDisplay(toIso)}`;
      }
    }

    function renderHistogram() {
      if (!histogramEl) return;
      const b = currentBounds();
      if (!b.min || !b.max || !b.daily?.length) {
        histogramEl.innerHTML = "";
        return;
      }

      const bins = binDailyCounts(b.daily, b.min, b.max);
      if (!bins.length) {
        histogramEl.innerHTML = "";
        return;
      }

      const fullRange = minIdx === 0 && maxIdx === totalDays;
      histogramEl.innerHTML = bins
        .map((bin) => {
          const inRange =
            fullRange || (bin.endIdx >= minIdx && bin.startIdx <= maxIdx);
          const cls = inRange ? "is-in-range" : "is-out-range";
          const title = bin.count
            ? `${bin.count} listing${bin.count === 1 ? "" : "s"}`
            : "";
          return `
        <div class="date-histogram-col" title="${title}">
          <span class="date-histogram-bar ${cls}" style="height:${bin.heightPct}%"></span>
        </div>`;
        })
        .join("");
    }

    function renderNotches() {
      const b = currentBounds();
      if (!notchesEl || !b.min || !b.max) {
        if (notchesEl) notchesEl.innerHTML = "";
        return;
      }
      const ticks = buildTicks(b.min, b.max);
      notchesEl.innerHTML = ticks
        .map(
          (t) => `
        <span class="date-notch${t.major ? " date-notch-major" : ""}" style="left:${t.pct}%">
          ${t.major ? `<span class="date-notch-label">${t.label}</span>` : ""}
          <span class="date-notch-mark"></span>
        </span>`
        )
        .join("");
    }

    function renderThumbs() {
      const pctMin = (minIdx / totalDays) * 100;
      const pctMax = (maxIdx / totalDays) * 100;
      thumbMin.style.left = `${pctMin}%`;
      thumbMax.style.left = `${pctMax}%`;
      fill.style.left = `${pctMin}%`;
      fill.style.width = `${Math.max(pctMax - pctMin, 0)}%`;
      updateLabel();
      renderHistogram();
    }

    function applyFilter() {
      if (suppressFilter) return;
      const b = currentBounds();
      if (!b.min || !b.max || !window.JobBoardsFilters) return;
      const fromIso = indexToIso(b.min, b.max, minIdx);
      const toIso = indexToIso(b.min, b.max, maxIdx);

      if (isFullRange(fromIso, toIso)) {
        const existing = JobBoardsFilters.getDateFilter();
        if (existing) JobBoardsFilters.remove(existing.id);
        return;
      }

      JobBoardsFilters.add({
        type: "date",
        field,
        from: fromIso,
        to: toIso,
        label: JobBoardsFilters.formatDateLabel(field, fromIso, toIso),
      });
    }

    function setIndices(newMin, newMax, apply) {
      minIdx = Math.max(0, Math.min(newMin, totalDays));
      maxIdx = Math.max(minIdx, Math.min(newMax, totalDays));
      renderThumbs();
      if (apply) applyFilter();
    }

    function setFromFilter(dateFilter) {
      const b = currentBounds();
      if (!b.min || !b.max) return;
      suppressFilter = true;
      if (dateFilter) {
        field = dateFilter.field === "apply_by" ? "apply_by" : "posted_at";
        if (fieldSelect) fieldSelect.value = field;
        const boundsForField = bounds[field] || {};
        totalDays = daysBetween(boundsForField.min, boundsForField.max);
        const fromIdx = dateFilter.from
          ? dayIndex(boundsForField.min, dateFilter.from)
          : 0;
        const toIdx = dateFilter.to
          ? dayIndex(boundsForField.min, dateFilter.to)
          : totalDays;
        minIdx = fromIdx;
        maxIdx = toIdx;
      } else {
        totalDays = daysBetween(b.min, b.max);
        minIdx = 0;
        maxIdx = totalDays;
      }
      renderNotches();
      renderThumbs();
      suppressFilter = false;
    }

    function resetToFull() {
      setFromFilter(null);
    }

    function wireThumb(thumb, which) {
      let dragging = false;

      function onPointerMove(clientX) {
        const rect = track.getBoundingClientRect();
        const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
        const idx = Math.round(pct * totalDays);
        if (which === "min") setIndices(idx, maxIdx, false);
        else setIndices(minIdx, idx, false);
      }

      thumb.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        dragging = true;
        thumb.setPointerCapture(e.pointerId);
        onPointerMove(e.clientX);
      });

      thumb.addEventListener("pointermove", (e) => {
        if (!dragging) return;
        onPointerMove(e.clientX);
      });

      thumb.addEventListener("pointerup", (e) => {
        if (!dragging) return;
        dragging = false;
        thumb.releasePointerCapture(e.pointerId);
        applyFilter();
      });
    }

    fieldSelect?.addEventListener("change", () => {
      field = fieldSelect.value === "apply_by" ? "apply_by" : "posted_at";
      const b = currentBounds();
      totalDays = daysBetween(b.min, b.max);
      minIdx = 0;
      maxIdx = totalDays;
      renderNotches();
      renderThumbs();
      applyFilter();
    });

    track?.addEventListener("click", (e) => {
      if (e.target === thumbMin || e.target === thumbMax) return;
      const rect = track.getBoundingClientRect();
      const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const idx = Math.round(pct * totalDays);
      const distMin = Math.abs(idx - minIdx);
      const distMax = Math.abs(idx - maxIdx);
      if (distMin <= distMax) setIndices(idx, maxIdx, true);
      else setIndices(minIdx, idx, true);
    });

    wireThumb(thumbMin, "min");
    wireThumb(thumbMax, "max");

    async function init() {
      try {
        const res = await fetch("/api/date-bounds");
        bounds = await res.json();
      } catch {
        bounds = {};
      }
      const b = currentBounds();
      totalDays = daysBetween(b.min, b.max);
      minIdx = 0;
      maxIdx = totalDays;
      renderNotches();
      renderThumbs();
      const existing = window.JobBoardsFilters?.getDateFilter();
      if (existing) setFromFilter(existing);
    }

    init();

    return {
      setFromFilter,
      resetToFull,
      onRangeChange(fn) {
        onRangeChange = fn;
      },
    };
  }

  window.JobBoardsDateRange = { create };
})();
