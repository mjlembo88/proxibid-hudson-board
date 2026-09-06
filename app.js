(function () {
  const ORIGIN_FALLBACK = { lat: 28.3672144, lon: -82.643641, address: "14515 Giddyup Pl, Hudson, FL" };
  const LS_WATCH = "proxibid-hudson-watch-v1";
  const LS_MAX = "proxibid-hudson-maxes-v1";
  const PAGE_SIZE = 75;

  const state = {
    all: [],
    origin: ORIGIN_FALLBACK,
    scrapedAt: null,
    sortKey: "datetime_local",
    sortAsc: true,
    markers: {},
    selectedId: null,
    mapReady: false,
    lotsByAid: {},
    auctionMeta: [],
    flatLots: [],
    watch: loadJson(LS_WATCH, {}),
    maxes: loadJson(LS_MAX, {}),
    lotSort: "lot",
    lotSortAsc: true,
    page: 0,
  };

  const els = {
    subtitle: document.getElementById("subtitle"),
    scraped: document.getElementById("scraped"),
    seller: document.getElementById("f-seller"),
    type: document.getElementById("f-type"),
    dist: document.getElementById("f-dist"),
    from: document.getElementById("f-from"),
    to: document.getElementById("f-to"),
    reset: document.getElementById("f-reset"),
    count: document.getElementById("count"),
    tbody: document.getElementById("tbody"),
    auction: document.getElementById("f-auction"),
    q: document.getElementById("f-q"),
    status: document.getElementById("f-status"),
    min: document.getElementById("f-min"),
    max: document.getElementById("f-max"),
    watched: document.getElementById("f-watched"),
    hasmax: document.getElementById("f-hasmax"),
    resetLots: document.getElementById("f-reset-lots"),
    exportBtn: document.getElementById("btn-export"),
    lotCount: document.getElementById("lot-count"),
    lotsTbody: document.getElementById("lots-tbody"),
    prevPage: document.getElementById("prev-page"),
    nextPage: document.getElementById("next-page"),
    pageLabel: document.getElementById("page-label"),
  };

  let map, layer;

  function loadJson(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return fallback;
      const v = JSON.parse(raw);
      return v && typeof v === "object" ? v : fallback;
    } catch (_) {
      return fallback;
    }
  }
  function saveWatch() {
    localStorage.setItem(LS_WATCH, JSON.stringify(state.watch));
  }
  function saveMaxes() {
    localStorage.setItem(LS_MAX, JSON.stringify(state.maxes));
  }
  function lotKey(aid, lot) {
    return String(aid) + ":" + String(lot);
  }
  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function fmtMoney(n, currency) {
    if (n == null || n === "" || Number.isNaN(Number(n))) return "—";
    const c = currency || "USD";
    try {
      return new Intl.NumberFormat("en-US", { style: "currency", currency: c, maximumFractionDigits: 2 }).format(Number(n));
    } catch (_) {
      return "$" + Number(n).toFixed(2);
    }
  }

  /* -------- tabs -------- */
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => {
        b.classList.toggle("active", b === btn);
        b.setAttribute("aria-selected", b === btn ? "true" : "false");
      });
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      document.getElementById("panel-" + btn.dataset.tab).classList.add("active");
      if (btn.dataset.tab === "map") {
        ensureMap();
        setTimeout(() => map && map.invalidateSize(), 50);
        refreshMapPanel();
      }
    });
  });

  /* -------- map / auctions -------- */
  function ensureMap() {
    if (state.mapReady) return;
    map = L.map("map", { zoomControl: true, scrollWheelZoom: true });
    L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      { attribution: "Esri", maxZoom: 16 }
    ).addTo(map);
    layer = L.layerGroup().addTo(map);
    state.mapReady = true;
  }
  function homeIcon() {
    return L.divIcon({
      className: "",
      html: '<div style="width:14px;height:14px;border-radius:50%;background:#6eb6ff;border:2px solid #fff;box-shadow:0 0 0 3px rgba(110,182,255,.35)"></div>',
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });
  }
  function auctionIcon(active) {
    const c = active ? "#7dd3a8" : "#f0b45a";
    return L.divIcon({
      className: "",
      html: `<div style="width:12px;height:12px;border-radius:50%;background:${c};border:2px solid #fff;box-shadow:0 0 0 2px rgba(0,0,0,.35)"></div>`,
      iconSize: [12, 12],
      iconAnchor: [6, 6],
    });
  }
  function dayKey(iso) {
    if (!iso) return "";
    return String(iso).slice(0, 10);
  }
  function applyAuctionFilters(items) {
    const seller = els.seller.value;
    const type = els.type.value;
    const maxMi = Number(els.dist.value) || 50;
    const from = els.from.value;
    const to = els.to.value;
    return items.filter((a) => {
      if (seller && a.seller !== seller) return false;
      if (type && String(a.type || "").toLowerCase() !== type.toLowerCase()) return false;
      if (a.distance_mi != null && Number(a.distance_mi) > maxMi) return false;
      const d = dayKey(a.datetime_local);
      if (from && d && d < from) return false;
      if (to && d && d > to) return false;
      return true;
    });
  }
  function sortAuctions(items) {
    const k = state.sortKey;
    const asc = state.sortAsc ? 1 : -1;
    return items.slice().sort((a, b) => {
      let va = a[k], vb = b[k];
      if (k === "distance_mi") {
        va = va == null ? Infinity : Number(va);
        vb = vb == null ? Infinity : Number(vb);
        return (va - vb) * asc;
      }
      va = va == null ? "" : String(va).toLowerCase();
      vb = vb == null ? "" : String(vb).toLowerCase();
      if (va < vb) return -1 * asc;
      if (va > vb) return 1 * asc;
      return 0;
    });
  }
  function openAuction(a) {
    if (a && a.url) window.open(a.url, "_blank", "noopener,noreferrer");
  }
  function selectRow(id, open) {
    state.selectedId = id;
    [...els.tbody.querySelectorAll("tr")].forEach((tr) => {
      tr.classList.toggle("active", tr.dataset.id === id);
    });
    Object.entries(state.markers).forEach(([mid, m]) => {
      m.setIcon(auctionIcon(mid === id));
    });
    const a = state.all.find((x) => x.id === id);
    if (a && a.lat != null && a.lon != null && map) {
      map.panTo([a.lat, a.lon], { animate: true });
    }
    if (open) openAuction(a);
  }
  function renderAuctionTable(items) {
    els.count.textContent =
      items.length + " auction" + (items.length === 1 ? "" : "s") + " · click row to open Proxibid";
    els.tbody.innerHTML = "";
    if (!items.length) {
      const tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="6" class="muted">No auctions match filters.</td>';
      els.tbody.appendChild(tr);
      return;
    }
    const frag = document.createDocumentFragment();
    items.forEach((a) => {
      const tr = document.createElement("tr");
      tr.dataset.id = a.id;
      tr.tabIndex = 0;
      if (a.id === state.selectedId) tr.classList.add("active");
      const typeClass = String(a.type || "").toLowerCase() === "timed" ? "timed" : "live";
      tr.innerHTML =
        `<td class="title">${escapeHtml(a.title || "")}</td>` +
        `<td>${escapeHtml(a.seller || "")}</td>` +
        `<td>${escapeHtml(a.datetime_display || a.datetime_local || "")}</td>` +
        `<td class="muted">${escapeHtml(a.location || "")}</td>` +
        `<td class="dist">${a.distance_mi != null ? Number(a.distance_mi).toFixed(1) : "—"}</td>` +
        `<td><span class="pill ${typeClass}">${escapeHtml(a.type || "")}</span></td>`;
      tr.addEventListener("click", () => selectRow(a.id, true));
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectRow(a.id, true);
        }
      });
      frag.appendChild(tr);
    });
    els.tbody.appendChild(frag);
  }
  function renderMap(items) {
    if (!state.mapReady) return;
    layer.clearLayers();
    state.markers = {};
    const o = state.origin;
    const bounds = [];
    if (o.lat != null && o.lon != null) {
      L.marker([o.lat, o.lon], { icon: homeIcon(), title: "Home" })
        .bindPopup(`<div class="pin-label"><strong>Home</strong><br>${escapeHtml(o.address || "Hudson")}</div>`)
        .addTo(layer);
      bounds.push([o.lat, o.lon]);
    }
    items.forEach((a) => {
      if (a.lat == null || a.lon == null) return;
      const m = L.marker([a.lat, a.lon], {
        icon: auctionIcon(a.id === state.selectedId),
        title: a.title,
      })
        .bindPopup(
          `<div class="pin-label"><strong>${escapeHtml(a.title || "")}</strong><br>` +
            `${escapeHtml(a.datetime_display || "")}<br>` +
            `${a.distance_mi != null ? a.distance_mi + " mi · " : ""}` +
            `<a href="${escapeHtml(a.url || "#")}" target="_blank" rel="noopener">Open catalog</a></div>`
        )
        .addTo(layer);
      m.on("click", () => selectRow(a.id, false));
      state.markers[a.id] = m;
      bounds.push([a.lat, a.lon]);
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [36, 36], maxZoom: 11 });
    else map.setView([o.lat, o.lon], 9);
  }
  function refreshMapPanel() {
    const filtered = sortAuctions(applyAuctionFilters(state.all));
    renderAuctionTable(filtered);
    renderMap(filtered);
    document.querySelectorAll("#panel-map th[data-sort]").forEach((th) => {
      th.classList.toggle("sorted", th.dataset.sort === state.sortKey);
      th.classList.toggle("asc", th.dataset.sort === state.sortKey && state.sortAsc);
    });
  }
  function fillSellers(items) {
    const sellers = [...new Set(items.map((a) => a.seller).filter(Boolean))].sort();
    els.seller.innerHTML = '<option value="">All</option>';
    sellers.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      els.seller.appendChild(opt);
    });
  }

  ["change", "input"].forEach((ev) => {
    [els.seller, els.type, els.dist, els.from, els.to].forEach((el) => {
      el.addEventListener(ev, refreshMapPanel);
    });
  });
  els.reset.addEventListener("click", () => {
    els.seller.value = "";
    els.type.value = "";
    els.dist.value = "50";
    els.from.value = "";
    els.to.value = "";
    refreshMapPanel();
  });
  document.querySelectorAll("#panel-map th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      if (state.sortKey === k) state.sortAsc = !state.sortAsc;
      else {
        state.sortKey = k;
        state.sortAsc = k === "datetime_local" || k === "distance_mi";
      }
      refreshMapPanel();
    });
  });

  function bootAuctions(data) {
    state.origin = Object.assign({}, ORIGIN_FALLBACK, data.origin || {});
    state.all = Array.isArray(data.auctions) ? data.auctions : [];
    state.scrapedAt = data.scraped_at || null;
    const radius = (data.filters && data.filters.radius_mi) || 50;
    els.dist.value = String(radius);
    els.subtitle.textContent =
      `Within ${radius} mi of ${state.origin.address || "Hudson, FL"} · watch board only (no bids placed)`;
    fillSellers(state.all);
  }

  /* -------- lots / watch -------- */
  function fillAuctionSelect() {
    els.auction.innerHTML = '<option value="">All auctions (' + state.flatLots.length + " lots)</option>";
    state.auctionMeta.forEach((a) => {
      const opt = document.createElement("option");
      opt.value = a.aid;
      opt.textContent = a.title + " (" + a.lots.length + ")";
      els.auction.appendChild(opt);
    });
  }

  function filteredLots() {
    const aid = els.auction.value;
    const q = (els.q.value || "").trim().toLowerCase();
    const status = (els.status.value || "").toLowerCase();
    const min = els.min.value === "" ? null : Number(els.min.value);
    const max = els.max.value === "" ? null : Number(els.max.value);
    const watchedOnly = els.watched.checked;
    const hasMax = els.hasmax.checked;

    let items = state.flatLots;
    if (aid) items = items.filter((x) => x.aid === aid);
    if (q) {
      items = items.filter(
        (x) =>
          String(x.lot).toLowerCase().includes(q) ||
          String(x.title || "").toLowerCase().includes(q) ||
          String(x.description || "").toLowerCase().includes(q)
      );
    }
    if (status) items = items.filter((x) => String(x.status || "").toLowerCase() === status);
    if (min != null && !Number.isNaN(min)) {
      items = items.filter((x) => x.current_bid != null && Number(x.current_bid) >= min);
    }
    if (max != null && !Number.isNaN(max)) {
      items = items.filter((x) => x.current_bid != null && Number(x.current_bid) <= max);
    }
    if (watchedOnly) items = items.filter((x) => state.watch[lotKey(x.aid, x.lot)]);
    if (hasMax) {
      items = items.filter((x) => {
        const v = state.maxes[lotKey(x.aid, x.lot)];
        return v != null && v !== "" && !Number.isNaN(Number(v));
      });
    }

    const k = state.lotSort;
    const asc = state.lotSortAsc ? 1 : -1;
    items = items.slice().sort((a, b) => {
      let va = a[k], vb = b[k];
      if (k === "current_bid") {
        va = va == null ? Infinity : Number(va);
        vb = vb == null ? Infinity : Number(vb);
        return (va - vb) * asc;
      }
      if (k === "lot") {
        const na = Number(va), nb = Number(vb);
        if (!Number.isNaN(na) && !Number.isNaN(nb)) return (na - nb) * asc;
      }
      va = va == null ? "" : String(va).toLowerCase();
      vb = vb == null ? "" : String(vb).toLowerCase();
      if (va < vb) return -1 * asc;
      if (va > vb) return 1 * asc;
      return 0;
    });
    return items;
  }

  function renderLots() {
    const items = filteredLots();
    const pages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
    if (state.page >= pages) state.page = pages - 1;
    if (state.page < 0) state.page = 0;
    const start = state.page * PAGE_SIZE;
    const slice = items.slice(start, start + PAGE_SIZE);

    const watchedN = Object.keys(state.watch).filter((k) => state.watch[k]).length;
    const maxN = Object.keys(state.maxes).filter((k) => state.maxes[k] != null && state.maxes[k] !== "").length;
    els.lotCount.textContent =
      items.length.toLocaleString() +
      " lot" +
      (items.length === 1 ? "" : "s") +
      " · " +
      watchedN +
      " watched · " +
      maxN +
      " hard maxes";
    els.pageLabel.textContent = "Page " + (state.page + 1) + " / " + pages;
    els.prevPage.disabled = state.page <= 0;
    els.nextPage.disabled = state.page >= pages - 1;

    document.querySelectorAll(".lots-table th[data-lsort]").forEach((th) => {
      th.classList.toggle("sorted", th.dataset.lsort === state.lotSort);
    });

    els.lotsTbody.innerHTML = "";
    if (!slice.length) {
      const tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="7" class="muted">No lots match filters.</td>';
      els.lotsTbody.appendChild(tr);
      return;
    }

    const frag = document.createDocumentFragment();
    slice.forEach((lot) => {
      const key = lotKey(lot.aid, lot.lot);
      const watched = !!state.watch[key];
      const maxVal = state.maxes[key];
      const tr = document.createElement("tr");
      if (watched) tr.classList.add("watched");

      const st = String(lot.status || "").toLowerCase();
      const thumb = lot.image
        ? `<img class="lot-thumb" src="${escapeHtml(lot.image)}" alt="" loading="lazy" decoding="async" onerror="this.style.display='none'" />`
        : "";

      tr.innerHTML =
        `<td><button type="button" class="watch-btn${watched ? " on" : ""}" data-act="watch" title="Watch">★</button></td>` +
        `<td class="money">${escapeHtml(lot.lot)}</td>` +
        `<td><div class="lot-title">${thumb}<div class="t"><span>${escapeHtml(lot.title || "")}</span><span class="aid">aid ${escapeHtml(lot.aid)} · ${escapeHtml(lot.auctionTitle || "")}</span></div></div></td>` +
        `<td class="money">${fmtMoney(lot.current_bid, lot.currency)}</td>` +
        `<td><span class="pill ${escapeHtml(st)}">${escapeHtml(lot.status || "—")}</span></td>` +
        `<td><input class="max-input${maxVal != null && maxVal !== "" ? " has-value" : ""}" type="number" min="0" step="1" inputmode="decimal" placeholder="ceiling" data-act="max" value="${maxVal != null && maxVal !== "" ? escapeHtml(maxVal) : ""}" title="Hard max bid (USD) — Auction Desk never bids above this" aria-label="Hard max bid USD" /></td>` +
        `<td><a class="linkish" href="${escapeHtml(lot.url || "#")}" target="_blank" rel="noopener noreferrer">Open</a></td>`;

      const watchBtn = tr.querySelector('[data-act="watch"]');
      watchBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (state.watch[key]) delete state.watch[key];
        else state.watch[key] = true;
        saveWatch();
        renderLots();
      });

      const maxInput = tr.querySelector('[data-act="max"]');
      maxInput.addEventListener("click", (e) => e.stopPropagation());
      maxInput.addEventListener("change", () => {
        const raw = maxInput.value.trim();
        if (raw === "") {
          delete state.maxes[key];
        } else {
          const n = Number(raw);
          if (Number.isNaN(n) || n < 0) {
            maxInput.value = state.maxes[key] != null ? state.maxes[key] : "";
            return;
          }
          state.maxes[key] = n;
          // auto-watch when setting a max
          state.watch[key] = true;
          saveWatch();
        }
        saveMaxes();
        renderLots();
      });

      tr.addEventListener("dblclick", () => {
        if (lot.url) window.open(lot.url, "_blank", "noopener,noreferrer");
      });

      frag.appendChild(tr);
    });
    els.lotsTbody.appendChild(frag);
  }

  function exportWatchlist() {
    const items = [];
    const keys = new Set([...Object.keys(state.watch), ...Object.keys(state.maxes)]);
    keys.forEach((key) => {
      const watched = !!state.watch[key];
      const maxBid = state.maxes[key];
      const hasMax = maxBid != null && maxBid !== "" && !Number.isNaN(Number(maxBid));
      if (!watched && !hasMax) return;
      const [aid, lot] = key.split(":");
      const found = state.flatLots.find((x) => x.aid === aid && String(x.lot) === String(lot));
      items.push({
        key,
        aid,
        lot,
        title: found ? found.title : null,
        url: found ? found.url : null,
        current_bid: found ? found.current_bid : null,
        status: found ? found.status : null,
        watched,
        hard_max_bid_usd: hasMax ? Number(maxBid) : null,
        note: "hard_max_bid_usd is Mark's ceiling — Auction Desk must never bid above it. Dashboard does not place bids.",
      });
    });
    items.sort((a, b) => String(a.aid).localeCompare(String(b.aid)) || Number(a.lot) - Number(b.lot));
    const payload = {
      exported_at: new Date().toISOString(),
      origin: "proxibid-hudson-dashboard",
      rules: {
        hard_max_is_ceiling: true,
        auction_desk_never_bids_above_max: true,
        dashboard_does_not_place_bids: true,
      },
      counts: {
        rows: items.length,
        watched: items.filter((x) => x.watched).length,
        with_max: items.filter((x) => x.hard_max_bid_usd != null).length,
      },
      items,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "watchlist.json";
    a.click();
    URL.revokeObjectURL(a.href);

    // Also try to mirror a copy hint in console for Auction Desk path
    console.info("Watchlist exported. Save as /workspace/proxibid/dashboard/watchlist.json if desired.", payload.counts);
  }

  function wireLotFilters() {
    const bump = () => {
      state.page = 0;
      renderLots();
    };
    ["change", "input"].forEach((ev) => {
      [els.auction, els.q, els.status, els.min, els.max, els.watched, els.hasmax].forEach((el) => {
        el.addEventListener(ev, bump);
      });
    });
    els.resetLots.addEventListener("click", () => {
      els.auction.value = "";
      els.q.value = "";
      els.status.value = "";
      els.min.value = "";
      els.max.value = "";
      els.watched.checked = false;
      els.hasmax.checked = false;
      bump();
    });
    els.exportBtn.addEventListener("click", exportWatchlist);
    els.prevPage.addEventListener("click", () => {
      state.page -= 1;
      renderLots();
    });
    els.nextPage.addEventListener("click", () => {
      state.page += 1;
      renderLots();
    });
    document.querySelectorAll(".lots-table th[data-lsort]").forEach((th) => {
      th.addEventListener("click", () => {
        const k = th.dataset.lsort;
        if (state.lotSort === k) state.lotSortAsc = !state.lotSortAsc;
        else {
          state.lotSort = k;
          state.lotSortAsc = true;
        }
        renderLots();
      });
    });
  }

  function bootLots(data) {
    state.auctionMeta = Array.isArray(data.auctions) ? data.auctions : [];
    state.flatLots = [];
    state.auctionMeta.forEach((a) => {
      (a.lots || []).forEach((lot) => {
        state.flatLots.push(
          Object.assign({}, lot, {
            aid: String(a.aid),
            auctionTitle: a.title,
            auctionUrl: a.url,
          })
        );
      });
    });
    const lotScraped = data.scraped_at || null;
    els.scraped.textContent =
      (state.scrapedAt ? "Auctions " + state.scrapedAt + " · " : "") +
      (lotScraped ? "Lots " + lotScraped : "") +
      " · " +
      state.flatLots.length +
      " lots";
    fillAuctionSelect();
    renderLots();
  }

  wireLotFilters();

  // Load auctions then lots
  const auctionsP = fetch("auctions.json", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .catch(() => window.__AUCTIONS__);

  auctionsP.then((data) => {
    if (data) bootAuctions(data);
    else els.count.textContent = "Could not load auctions.json";
  });

  fetch("lots.json", { cache: "no-store" })
    .then((r) => {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(bootLots)
    .catch((err) => {
      els.lotCount.textContent =
        "Could not load lots.json — " + err.message + ". Serve via: python3 -m http.server 8766";
    });
})();
