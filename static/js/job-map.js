(function () {
  function esc(s) {
    if (!s) return "";
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function precisionColor(precision) {
    if (precision === "campus") return "#3dd68c";
    if (precision === "city") return "#6cb6ff";
    if (precision === "region") return "#f0b429";
    return "#8b9aab";
  }

  function popupHtml(job) {
    const title = job.subject_area || job.institution || "Job";
    const place = [job.institution, job.location].filter(Boolean).join(" · ");
    return `
      <div class="map-popup">
        <strong>${esc(title)}</strong>
        <div>${esc(place)}</div>
        <a href="/jobs/${job.id}">View listing</a>
      </div>`;
  }

  function clusterTooltipHtml(markers) {
    const jobs = markers.map((m) => m._jobData).filter(Boolean);
    const count = jobs.length || markers.length;
    if (!jobs.length) {
      return `<div class="map-popup map-popup-cluster"><strong>${count} jobs</strong></div>`;
    }
    const items = jobs
      .slice(0, 5)
      .map((job) => {
        const title = job.subject_area || job.title || job.institution || "Job";
        return `<div class="map-popup-item">${esc(title)}</div>`;
      })
      .join("");
    const more = jobs.length > 5 ? `<div class="map-popup-more">+ ${jobs.length - 5} more</div>` : "";
    return `<div class="map-popup map-popup-cluster"><strong>${jobs.length} jobs</strong>${items}${more}</div>`;
  }

  const HOVER_CLOSE_DELAY_MS = 350;

  function createHoverCard(map) {
    const container = map.getContainer();
    const card = document.createElement("div");
    card.className = "map-hover-card";
    card.setAttribute("role", "tooltip");
    card.hidden = true;
    container.appendChild(card);

    let closeTimer = null;
    let anchorLatLng = null;

    function cancelClose() {
      if (closeTimer) {
        clearTimeout(closeTimer);
        closeTimer = null;
      }
    }

    function hide() {
      cancelClose();
      card.hidden = true;
      anchorLatLng = null;
    }

    function scheduleClose() {
      cancelClose();
      closeTimer = setTimeout(hide, HOVER_CLOSE_DELAY_MS);
    }

    function position() {
      if (!anchorLatLng || card.hidden) return;
      const point = map.latLngToContainerPoint(anchorLatLng);
      card.style.left = `${point.x}px`;
      card.style.top = `${point.y}px`;
    }

    function show(latlng, html) {
      cancelClose();
      anchorLatLng = latlng;
      card.innerHTML = html;
      card.hidden = false;
      position();
    }

    card.addEventListener("mouseenter", cancelClose);
    card.addEventListener("mouseleave", scheduleClose);
    L.DomEvent.disableClickPropagation(card);
    L.DomEvent.disableScrollPropagation(card);

    map.on("move zoom resize", position);

    function bindLayer(layer, html) {
      layer.on("mouseover", () => {
        show(layer.getLatLng(), html);
      });
      layer.on("mouseout", scheduleClose);
    }

    return { show, hide, scheduleClose, bindLayer };
  }

  function createController(container, options) {
    const opts = options || {};
    const map = L.map(container, { scrollWheelZoom: true }).setView([30, 0], 2);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 18,
    }).addTo(map);

    const hoverCard = createHoverCard(map);

    const cluster = L.markerClusterGroup({
      showCoverageOnHover: false,
      maxClusterRadius: 42,
      disableClusteringAtZoom: 15,
      spiderfyOnMaxZoom: true,
      spiderfyDistanceMultiplier: 2.5,
      zoomToBoundsOnClick: true,
    });
    map.addLayer(cluster);

    cluster.on("clusterclick", () => {
      hoverCard.hide();
    });
    cluster.on("spiderfied", (e) => {
      for (const marker of e.markers) {
        if (marker.bringToFront) marker.bringToFront();
      }
    });

    cluster.on("clustermouseover", (e) => {
      const markers = e.layer.getAllChildMarkers();
      hoverCard.show(e.layer.getLatLng(), clusterTooltipHtml(markers));
    });
    cluster.on("clustermouseout", () => {
      hoverCard.scheduleClose();
    });

    const markersById = new Map();
    let focusedId = null;
    let fitOnNextLoad = true;

    function makeMarker(job, highlighted) {
      const color = precisionColor(job.geo_precision);
      const marker = L.circleMarker([job.lat, job.lon], {
        radius: highlighted ? 10 : job.geo_precision === "campus" ? 7 : 6,
        color: highlighted ? "#ffffff" : color,
        fillColor: color,
        fillOpacity: highlighted ? 1 : 0.85,
        weight: highlighted ? 2 : 1,
        bubblingMouseEvents: false,
      });
      hoverCard.bindLayer(marker, popupHtml(job));
      marker._jobId = job.id;
      return marker;
    }

    function setMarkers(jobs, opts) {
      const options = opts || {};
      cluster.clearLayers();
      markersById.clear();

      if (!jobs.length) return false;

      const bounds = [];
      for (const job of jobs) {
        const highlighted = job.id === focusedId;
        const marker = makeMarker(job, highlighted);
        markersById.set(job.id, marker);
        cluster.addLayer(marker);
        bounds.push([job.lat, job.lon]);
      }

      if (options.focusId && markersById.has(options.focusId)) {
        focusJob(options.focusId, options.zoom || 12, false);
        return true;
      }

      if (fitOnNextLoad && !options.skipFit) {
        if (bounds.length === 1) {
          map.setView(bounds[0], options.zoom || 10);
        } else {
          map.fitBounds(bounds, { padding: [36, 36], maxZoom: options.maxZoom || 10 });
        }
        fitOnNextLoad = false;
      }
      return true;
    }

    function focusJob(jobId, zoom, openPopup) {
      focusedId = jobId;
      const marker = markersById.get(jobId);
      if (!marker) return false;

      markersById.forEach((m, id) => {
        const job = m._jobData;
        if (!job) return;
        const highlighted = id === jobId;
        const color = precisionColor(job.geo_precision);
        m.setStyle({
          radius: highlighted ? 10 : job.geo_precision === "campus" ? 7 : 6,
          color: highlighted ? "#ffffff" : color,
          fillColor: color,
          fillOpacity: highlighted ? 1 : 0.85,
          weight: highlighted ? 2 : 1,
        });
      });

      const latlng = marker.getLatLng();
      map.setView(latlng, zoom || 12, { animate: true });
      if (openPopup !== false) {
        const job = marker._jobData;
        if (job) hoverCard.show(latlng, popupHtml(job));
      }
      return true;
    }

    function highlightJob(jobId) {
      focusedId = jobId;
      markersById.forEach((m, id) => {
        const job = m._jobData;
        if (!job) return;
        const highlighted = id === jobId;
        const color = precisionColor(job.geo_precision);
        m.setStyle({
          radius: highlighted ? 9 : job.geo_precision === "campus" ? 7 : 6,
          color: highlighted ? "#ffffff" : color,
          fillColor: color,
          fillOpacity: highlighted ? 1 : 0.85,
          weight: highlighted ? 2 : 1,
        });
      });
    }

    function showSingle(job, zoom) {
      cluster.clearLayers();
      markersById.clear();
      const marker = makeMarker(job, true);
      marker._jobData = job;
      markersById.set(job.id, marker);
      cluster.addLayer(marker);
      map.setView([job.lat, job.lon], zoom || 13);
      hoverCard.show([job.lat, job.lon], popupHtml(job));
      setTimeout(() => map.invalidateSize(), 50);
    }

    function attachJobData(jobs) {
      for (const job of jobs) {
        const marker = markersById.get(job.id);
        if (marker) marker._jobData = job;
      }
    }

    function fitAll(maxZoom) {
      const layers = cluster.getLayers();
      if (!layers.length) return;
      const group = L.featureGroup(layers);
      map.fitBounds(group.getBounds(), { padding: [36, 36], maxZoom: maxZoom || 10 });
    }

    function resetFit() {
      fitOnNextLoad = true;
    }

    let areaLayer = null;
    let dragRect = null;
    let selectMode = false;
    let selectStart = null;
    let onAreaSelected = null;
    let selectBtn = null;
    let clearBtn = null;

    function setSelectMode(on) {
      selectMode = on;
      map.getContainer().classList.toggle("map-selecting", on);
      if (selectBtn) selectBtn.classList.toggle("is-active", on);
      if (on) {
        map.dragging.disable();
        map.boxZoom.disable();
        map.doubleClickZoom.disable();
      } else {
        map.dragging.enable();
        map.boxZoom.enable();
        map.doubleClickZoom.enable();
        selectStart = null;
        if (dragRect) {
          map.removeLayer(dragRect);
          dragRect = null;
        }
      }
    }

    function setAreaBounds(bounds) {
      if (areaLayer) map.removeLayer(areaLayer);
      if (!bounds) {
        areaLayer = null;
        if (clearBtn) clearBtn.hidden = true;
        return;
      }
      const latLngBounds =
        bounds instanceof L.LatLngBounds
          ? bounds
          : L.latLngBounds(
              [bounds.south, bounds.west],
              [bounds.north, bounds.east]
            );
      areaLayer = L.rectangle(latLngBounds, {
        color: "#3dd68c",
        weight: 2,
        dashArray: "6 4",
        fillColor: "#3dd68c",
        fillOpacity: 0.12,
      });
      areaLayer.addTo(map);
      if (clearBtn) clearBtn.hidden = false;
    }

    function clearAreaBounds() {
      setAreaBounds(null);
    }

    function finishAreaSelect(bounds) {
      setSelectMode(false);
      if (bounds.getNorth() - bounds.getSouth() < 0.001 && bounds.getEast() - bounds.getWest() < 0.001) {
        if (dragRect) {
          map.removeLayer(dragRect);
          dragRect = null;
        }
        return;
      }
      if (dragRect) {
        map.removeLayer(dragRect);
        dragRect = null;
      }
      setAreaBounds(bounds);
      if (onAreaSelected) onAreaSelected(bounds);
    }

    if (opts.areaSelect) {
      const toolbar = L.control({ position: "topright" });
      toolbar.onAdd = function () {
        const div = L.DomUtil.create("div", "map-area-toolbar");
        div.innerHTML = `
          <button type="button" class="map-tool-btn" data-action="select" title="Draw a rectangle to filter jobs">Select area</button>
          <button type="button" class="map-tool-btn" data-action="clear" title="Clear map area filter" hidden>Clear</button>`;
        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.disableScrollPropagation(div);
        selectBtn = div.querySelector('[data-action="select"]');
        clearBtn = div.querySelector('[data-action="clear"]');
        selectBtn.addEventListener("click", () => setSelectMode(!selectMode));
        clearBtn.addEventListener("click", () => {
          clearAreaBounds();
          if (onAreaSelected) onAreaSelected(null);
        });
        return div;
      };
      toolbar.addTo(map);

      map.on("mousedown", (e) => {
        if (!selectMode) return;
        L.DomEvent.stop(e.originalEvent);
        selectStart = e.latlng;
        if (dragRect) map.removeLayer(dragRect);
        dragRect = L.rectangle([selectStart, selectStart], {
          color: "#3dd68c",
          weight: 2,
          fillColor: "#3dd68c",
          fillOpacity: 0.2,
        });
        dragRect.addTo(map);
      });

      map.on("mousemove", (e) => {
        if (!selectMode || !selectStart || !dragRect) return;
        dragRect.setBounds(L.latLngBounds(selectStart, e.latlng));
      });

      map.on("mouseup", (e) => {
        if (!selectMode || !selectStart || !dragRect) return;
        L.DomEvent.stop(e.originalEvent);
        finishAreaSelect(dragRect.getBounds());
        selectStart = null;
      });
    }

    setTimeout(() => map.invalidateSize(), 100);

    return {
      map,
      setMarkers(jobs, opts) {
        setMarkers(jobs, opts);
        attachJobData(jobs);
      },
      focusJob,
      highlightJob,
      showSingle,
      fitAll,
      resetFit,
      setAreaBounds,
      clearAreaBounds,
      onAreaSelected(cb) {
        onAreaSelected = cb;
      },
      getAreaBounds() {
        return areaLayer ? areaLayer.getBounds() : null;
      },
      hasJob(jobId) {
        return markersById.has(jobId);
      },
    };
  }

  window.JobBoardsMap = {
    create(container, options) {
      if (!container || !window.L) return null;
      return createController(container, options);
    },
    precisionColor,
    popupHtml,
    esc,
  };
})();
