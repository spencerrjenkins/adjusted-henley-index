/* Adjusted Henley Index — interaction layer.
   No dependencies: the geometry is baked SVG path data and everything else is
   a few hundred lines of DOM work, so the page stays fast on a phone and keeps
   working when a CDN does not. */
(function () {
  "use strict";

  const DATA = window.AHI_DATA;
  const PATHS = window.WORLD_PATHS;
  const MARKERS = window.AHI_MARKERS;
  const VIEWBOX = window.WORLD_VIEWBOX;

  const css = (name) => getComputedStyle(document.documentElement)
    .getPropertyValue(name).trim();
  const SEQ = () => [1, 2, 3, 4, 5, 6, 7].map((i) => css("--seq-" + i));
  const fmt = (v, d = 0) => (v === null || v === undefined || Number.isNaN(v))
    ? "—" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

  /* ------------------------------------------------------------------ *
   * Metrics: each is a way of asking the same question differently.
   * ------------------------------------------------------------------ */
  const METRICS = {
    henley: {
      label: "Henley rule (count)", short: "Destinations",
      get: (c) => c.henleyScore, unit: " destinations", decimals: 0,
      blurb: "Destinations reachable with no prior visa, scored the way Henley & Partners score them: one point each, no weighting.",
    },
    balanced: {
      label: "Adjusted — Balanced", short: "Adjusted %",
      get: (c) => c.lenses.balanced, unit: "%", decimals: 1,
      blurb: "Share of the world's weighted opportunity reachable, across all six pillars at once.",
    },
    business: {
      label: "Adjusted — Business", short: "Business %",
      get: (c) => c.lenses.business, unit: "%", decimals: 1,
      blurb: "Weighted toward market size, wealth and institutional reliability.",
    },
    leisure: {
      label: "Adjusted — Leisure", short: "Leisure %",
      get: (c) => c.lenses.leisure, unit: "%", decimals: 1,
      blurb: "Weighted toward tourist draw, safety and how far your money goes.",
    },
    settlement: {
      label: "Adjusted — Settlement", short: "Settlement %",
      get: (c) => c.lenses.settlement, unit: "%", decimals: 1,
      blurb: "Weighted toward human development and security: where you could plausibly live.",
    },
    gdpShare: {
      label: "Share of world GDP", short: "World GDP %",
      get: (c) => c.gdpShare, unit: "% of world GDP", decimals: 1,
      blurb: "Percentage of global output (PPP) you can walk into without asking permission. No weighting scheme involved.",
    },
    popShare: {
      label: "Share of world population", short: "World people %",
      get: (c) => c.popShare, unit: "% of humanity", decimals: 1,
      blurb: "Percentage of the world's people you can go and meet without a prior visa.",
    },
    openness: {
      label: "Openness (who you admit)", short: "Admits",
      get: (c) => c.admits, unit: " nationalities", decimals: 0,
      blurb: "How many nationalities this country lets in without a prior visa — the inbound mirror of the index.",
    },
    balance: {
      label: "Mobility balance", short: "Balance",
      get: (c) => c.balance, unit: " destinations", decimals: 0, diverging: true,
      blurb: "Destinations you can reach minus nationalities you admit. Positive means you travel more freely than you welcome.",
    },
    residual: {
      label: "Over/under-performance", short: "Residual",
      get: (c) => c.residual, unit: " points vs. predicted", decimals: 1, diverging: true,
      blurb: "Actual access minus what a regression on the country's own wealth, development, size and institutions predicts.",
    },
  };

  const PILLARS = ["economy", "development", "scale", "draw", "security", "cost"];
  const PILLAR_LABELS = {
    economy: "Economy", development: "Development", scale: "Scale",
    draw: "Draw", security: "Security", cost: "Affordability",
  };

  let currentMetric = "balanced";
  let selected = "USA";
  let sortKey = "balanced";
  let sortDir = 1;
  let filterText = "";

  const codes = Object.keys(DATA.countries);
  const tooltip = document.getElementById("tooltip");

  /* ------------------------------------------------------------------ *
   * Color scales
   * ------------------------------------------------------------------ */
  function scaleFor(metricKey) {
    const metric = METRICS[metricKey];
    const values = codes.map((c) => metric.get(DATA.countries[c]))
      .filter((v) => v !== null && v !== undefined && !Number.isNaN(v));
    const min = Math.min(...values);
    const max = Math.max(...values);
    if (metric.diverging) {
      const span = Math.max(Math.abs(min), Math.abs(max)) || 1;
      return (v) => {
        if (v === null || v === undefined || Number.isNaN(v)) return null;
        const t = v / span;
        if (Math.abs(t) < 0.06) return css("--pole-mid");
        // Two hues and a neutral middle; opacity carries magnitude so the
        // ramp stays one hue per arm instead of drifting through a rainbow.
        const hue = t > 0 ? css("--pole-high") : css("--pole-low");
        return mix(css("--pole-mid"), hue, Math.min(Math.abs(t), 1));
      };
    }
    const ramp = SEQ();
    return (v) => {
      if (v === null || v === undefined || Number.isNaN(v)) return null;
      const t = max === min ? 0.5 : (v - min) / (max - min);
      return ramp[Math.min(ramp.length - 1, Math.max(0, Math.round(t * (ramp.length - 1))))];
    };
  }

  function mix(a, b, t) {
    const pa = parse(a), pb = parse(b);
    if (!pa || !pb) return b;
    const out = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
    return `rgb(${out[0]},${out[1]},${out[2]})`;
  }
  function parse(color) {
    if (color.startsWith("#")) {
      const h = color.slice(1);
      const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
      return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
    }
    const m = color.match(/rgba?\(([^)]+)\)/);
    return m ? m[1].split(",").slice(0, 3).map((v) => parseFloat(v)) : null;
  }

  /* ------------------------------------------------------------------ *
   * Map
   * ------------------------------------------------------------------ */
  const svg = document.getElementById("map");
  svg.setAttribute("viewBox", VIEWBOX);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "World choropleth of passport strength");

  const shapes = {};
  Object.keys(PATHS).forEach((iso) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", "path");
    el.setAttribute("d", PATHS[iso]);
    el.setAttribute("class", "country");
    el.dataset.iso = iso;
    svg.appendChild(el);
    shapes[iso] = el;
  });
  Object.keys(MARKERS).forEach((iso) => {
    const [x, y] = MARKERS[iso];
    const el = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    el.setAttribute("cx", x); el.setAttribute("cy", y); el.setAttribute("r", 3.1);
    el.setAttribute("class", "dot");
    el.dataset.iso = iso;
    svg.appendChild(el);
    if (!shapes[iso]) shapes[iso] = el;
  });

  function paintMap() {
    const metric = METRICS[currentMetric];
    const scale = scaleFor(currentMetric);
    Object.keys(shapes).forEach((iso) => {
      const country = DATA.countries[iso];
      const el = shapes[iso];
      const color = country ? scale(metric.get(country)) : null;
      if (color) {
        el.setAttribute("fill", color);
        el.classList.remove("no-data");
      } else {
        el.removeAttribute("fill");
        el.classList.add("no-data");
      }
      el.classList.toggle("selected", iso === selected);
    });
    paintLegend(metric, scale);
  }

  function paintLegend(metric, scale) {
    const values = codes.map((c) => metric.get(DATA.countries[c]))
      .filter((v) => v !== null && !Number.isNaN(v));
    const min = Math.min(...values), max = Math.max(...values);
    const swatches = document.getElementById("legend-swatches");
    swatches.innerHTML = "";
    const steps = 7;
    for (let i = 0; i < steps; i++) {
      const v = min + (max - min) * (i / (steps - 1));
      const div = document.createElement("div");
      div.className = "sw";
      div.style.background = scale(v) || css("--deemphasis");
      swatches.appendChild(div);
    }
    document.getElementById("legend-min").textContent = fmt(min, metric.decimals);
    document.getElementById("legend-max").textContent = fmt(max, metric.decimals);
    document.getElementById("metric-blurb").textContent = metric.blurb;
  }

  function showTooltip(event, iso) {
    const country = DATA.countries[iso];
    if (!country) return;
    const metric = METRICS[currentMetric];
    tooltip.innerHTML =
      `<strong>${country.name}</strong>` +
      row(metric.short, fmt(metric.get(country), metric.decimals) + metric.unit) +
      row("Henley rank", "#" + country.henleyRank) +
      row("Position → adjusted", country.henleyPos + " → " + country.pos.balanced) +
      row("Reaches / admits", `${country.reaches} / ${country.admits}`) +
      `<div class="row" style="margin-top:.35rem"><span>${country.clusterLabel}</span></div>`;
    tooltip.style.opacity = "1";
    moveTooltip(event);
  }
  const row = (k, v) => `<div class="row"><span>${k}</span><b>${v}</b></div>`;

  function moveTooltip(event) {
    const pad = 14;
    const rect = tooltip.getBoundingClientRect();
    let x = event.clientX + pad;
    let y = event.clientY + pad;
    if (x + rect.width > window.innerWidth - 8) x = event.clientX - rect.width - pad;
    if (y + rect.height > window.innerHeight - 8) y = event.clientY - rect.height - pad;
    tooltip.style.left = x + "px";
    tooltip.style.top = y + "px";
  }

  svg.addEventListener("mousemove", (e) => {
    const iso = e.target.dataset && e.target.dataset.iso;
    if (iso && DATA.countries[iso]) { showTooltip(e, iso); } else { tooltip.style.opacity = "0"; }
  });
  svg.addEventListener("mouseleave", () => { tooltip.style.opacity = "0"; });
  svg.addEventListener("click", (e) => {
    const iso = e.target.dataset && e.target.dataset.iso;
    if (iso && DATA.countries[iso]) select(iso);
  });

  /* ------------------------------------------------------------------ *
   * Metric buttons
   * ------------------------------------------------------------------ */
  const metricBar = document.getElementById("metric-buttons");
  Object.keys(METRICS).forEach((key) => {
    const b = document.createElement("button");
    b.textContent = METRICS[key].label;
    b.setAttribute("aria-pressed", key === currentMetric);
    b.addEventListener("click", () => {
      currentMetric = key;
      metricBar.querySelectorAll("button").forEach((other) =>
        other.setAttribute("aria-pressed", other === b));
      paintMap();
    });
    metricBar.appendChild(b);
  });

  /* ------------------------------------------------------------------ *
   * Ranking table
   * ------------------------------------------------------------------ */
  const COLUMNS = [
    { key: "name", label: "Passport", type: "text" },
    { key: "henleyScore", label: "Destinations", d: 0 },
    { key: "henleyRank", label: "Henley rank", d: 0 },
    { key: "henleyPos", label: "Position /199", d: 0 },
    { key: "balanced", label: "Adjusted %", d: 1, lens: true },
    { key: "posBalanced", label: "Adj. position", d: 0 },
    // Movement is the fractional difference, not the difference of the two
    // integer positions: Henley's ties would otherwise make almost everyone
    // appear to fall. See the note under the table.
    { key: "move", label: "Move", d: 1, delta: true },
    { key: "gdpShare", label: "World GDP %", d: 1 },
    { key: "admits", label: "Admits", d: 0 },
    { key: "balance", label: "Balance", d: 0, delta: true },
  ];

  function tableValue(country, key) {
    switch (key) {
      case "name": return country.name;
      case "balanced": return country.lenses.balanced;
      case "posBalanced": return country.pos.balanced;
      case "move": return country.henleyFrac - country.balancedFrac;
      default: return country[key];
    }
  }

  function buildTable() {
    const head = document.getElementById("table-head");
    head.innerHTML = "";
    COLUMNS.forEach((col) => {
      const th = document.createElement("th");
      th.textContent = col.label + (sortKey === col.key ? (sortDir > 0 ? " ▾" : " ▴") : "");
      th.setAttribute("scope", "col");
      th.addEventListener("click", () => {
        if (sortKey === col.key) { sortDir *= -1; } else { sortKey = col.key; sortDir = 1; }
        buildTable();
      });
      head.appendChild(th);
    });

    const rows = codes
      .map((iso) => DATA.countries[iso])
      .filter((c) => !filterText || c.name.toLowerCase().includes(filterText)
        || c.iso.toLowerCase().includes(filterText));

    const numeric = sortKey !== "name";
    rows.sort((a, b) => {
      const va = tableValue(a, sortKey), vb = tableValue(b, sortKey);
      if (!numeric) return String(va).localeCompare(String(vb)) * sortDir;
      // Rank columns are "smaller is better", so a descending click on them
      // should still put the strongest passport on top.
      const flip = (sortKey.includes("Pos") || sortKey.includes("Rank")
        || sortKey === "posBalanced") ? -1 : 1;
      return (vb - va) * sortDir * flip;
    });

    const body = document.getElementById("table-body");
    body.innerHTML = "";
    rows.slice(0, 220).forEach((country) => {
      const tr = document.createElement("tr");
      tr.dataset.iso = country.iso;
      tr.classList.toggle("active", country.iso === selected);
      COLUMNS.forEach((col) => {
        const td = document.createElement("td");
        const value = tableValue(country, col.key);
        if (col.type === "text") {
          td.className = "name";
          td.textContent = value;
        } else if (col.delta) {
          td.textContent = value > 0 ? "+" + fmt(value, col.d) : fmt(value, col.d);
          if (value > 0) td.className = "delta-up";
          if (value < 0) td.className = "delta-down";
        } else {
          td.textContent = fmt(value, col.d);
        }
        tr.appendChild(td);
      });
      tr.addEventListener("click", () => select(country.iso));
      body.appendChild(tr);
    });
    document.getElementById("table-count").textContent =
      `${rows.length} passports` + (filterText ? " matching" : "");
  }

  document.getElementById("table-search").addEventListener("input", (e) => {
    filterText = e.target.value.trim().toLowerCase();
    buildTable();
  });

  /* ------------------------------------------------------------------ *
   * Detail card
   * ------------------------------------------------------------------ */
  function select(iso) {
    selected = iso;
    paintMap();
    buildTable();
    renderDetail();
    const card = document.getElementById("detail-card");
    if (card) card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderDetail() {
    const c = DATA.countries[selected];
    if (!c) return;
    document.getElementById("detail-name").textContent = c.name;
    document.getElementById("detail-sub").textContent =
      `${c.clusterLabel} · ${c.region || "—"} · ${c.incomeGroup || "income group not reported"}`;

    const move = c.henleyFrac - c.balancedFrac;
    const moveLabel = Math.abs(move) < 0.05 ? "" :
      ` (${move > 0 ? "+" : "\u2212"}${Math.abs(move).toFixed(1)})`;
    document.getElementById("detail-kpis").innerHTML = [
      tile(fmt(c.henleyScore) , "destinations, Henley rule"),
      tile("#" + c.henleyRank, "Henley rank (published convention)"),
      tile("#" + c.pos.balanced + moveLabel, "adjusted position, and fractional move"),
      tile(fmt(c.gdpShare, 1) + "%", "of world GDP reachable"),
      tile(fmt(c.popShare, 1) + "%", "of humanity reachable"),
      tile(fmt(c.reaches) + " / " + fmt(c.admits), "reaches / admits"),
    ].join("");

    const maxAtt = 100;
    document.getElementById("detail-pillars").innerHTML = PILLARS.map((p) => {
      const att = c.pillars[p].att, tilt = c.pillars[p].tilt;
      const w = Math.max(0, Math.min(100, att / maxAtt * 100));
      return `<div class="bar-row">
          <span class="cap">${PILLAR_LABELS[p]}</span>
          <span class="track"><span class="fill" style="width:${w}%;background:var(--seq-4)"></span></span>
          <span class="val">${fmt(att, 0)}%</span>
        </div>
        <div class="bar-row">
          <span class="cap note" style="font-size:.74rem">vs. own average</span>
          <span class="tilt-track"><span class="tilt-mid"></span>${tiltBar(tilt)}</span>
          <span class="val" style="font-size:.78rem">${tilt > 0 ? "+" : ""}${fmt(tilt, 1)}</span>
        </div>`;
    }).join("");

    document.getElementById("detail-ranks").innerHTML = [
      ["Balanced", c.pos.balanced], ["Business", c.pos.business],
      ["Leisure", c.pos.leisure], ["Settlement", c.pos.settlement],
      ["Raw reach", c.pos.reach], ["Share of world GDP", c.pos.gdpShare],
      ["Permitted person-days", c.pos.stayDays],
    ].map(([label, rank]) => `<div class="bar-row">
        <span class="cap">${label}</span>
        <span class="track"><span class="fill" style="width:${(1 - (rank - 1) / 199) * 100}%;background:var(--series-1)"></span></span>
        <span class="val">#${rank}</span>
      </div>`).join("");

    document.getElementById("detail-uncertainty").innerHTML =
      `<p class="note" style="margin:0">Across 3,000 resampled pillar weightings this passport ranks
       between <b>#${c.mcLow}</b> and <b>#${c.mcHigh}</b>, median <b>#${c.mcMedian}</b>.
       Its expected position among 199 is <b>${c.henleyFrac.toFixed(1)}</b> under the
       Henley rule and <b>${c.balancedFrac.toFixed(1)}</b> once destinations are weighted.
       A regression on its own wealth, development, size and institutions predicts
       <b>${fmt(c.predicted, 1)}%</b> attainment; it actually reaches
       <b>${fmt(c.lenses.balanced, 1)}%</b> — ${c.residual >= 0 ? "above" : "below"}
       prediction by ${fmt(Math.abs(c.residual), 1)} points.</p>`;
  }

  const tile = (v, l) => `<div class="tile"><span class="value">${v}</span><span class="label">${l}</span></div>`;

  function tiltBar(tilt) {
    const span = 8;
    const pct = Math.min(Math.abs(tilt) / span, 1) * 50;
    const color = tilt >= 0 ? "var(--pole-high)" : "var(--pole-low)";
    const style = tilt >= 0
      ? `left:50%;width:${pct}%;background:${color}`
      : `right:50%;width:${pct}%;background:${color}`;
    return `<span class="tilt-fill" style="${style}"></span>`;
  }

  /* ------------------------------------------------------------------ *
   * Theme toggle — must beat the OS preference in both directions
   * ------------------------------------------------------------------ */
  const toggle = document.getElementById("theme-toggle");
  const stored = localStorage.getItem("ahi-theme");
  if (stored) document.documentElement.setAttribute("data-theme", stored);
  function labelToggle() {
    const dark = document.documentElement.getAttribute("data-theme") === "dark"
      || (!document.documentElement.getAttribute("data-theme")
        && window.matchMedia("(prefers-color-scheme: dark)").matches);
    toggle.textContent = dark ? "Light mode" : "Dark mode";
    document.querySelectorAll("source[data-light]").forEach((s) => {
      s.srcset = dark ? s.dataset.dark : s.dataset.light;
    });
    document.querySelectorAll("img[data-light]").forEach((img) => {
      img.src = dark ? img.dataset.dark : img.dataset.light;
    });
  }
  toggle.addEventListener("click", () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark"
      || (!document.documentElement.getAttribute("data-theme")
        && window.matchMedia("(prefers-color-scheme: dark)").matches);
    const next = dark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("ahi-theme", next);
    labelToggle();
    paintMap();
    // Chart colours are read from CSS custom properties at draw time, so a
    // theme flip needs a redraw rather than a repaint.
    if (window.AHI_RENDER_CHARTS) window.AHI_RENDER_CHARTS();
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    labelToggle(); paintMap();
    if (window.AHI_RENDER_CHARTS) window.AHI_RENDER_CHARTS();
  });

  /* ------------------------------------------------------------------ */
  labelToggle();
  paintMap();
  buildTable();
  renderDetail();
})();
