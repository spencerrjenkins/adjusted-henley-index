/* Adjusted Henley Index — interactive chart layer.

   A small SVG engine rather than a charting library: the page ships no
   dependencies, and every mark here is one of six shapes. The engine supplies
   scales, axes, a shared tooltip and the theme hookup; each chart below is a
   short render function that reads from window.AHI_DATA.

   Charts redraw on theme change and on resize, because colours come from CSS
   custom properties and widths come from the container. */
(function () {
  "use strict";

  const D = window.AHI_DATA;
  const S = D.series;
  const NS = "http://www.w3.org/2000/svg";
  const PILLARS = ["economy", "development", "scale", "draw", "security", "cost"];
  const PILLAR_LABELS = S.pillars.reduce((a, p) => (a[p.key] = p.label, a), {});

  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const fmt = (v, d = 0) => v == null || Number.isNaN(v) ? "—"
    : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const el = (tag, attrs = {}, parent = null) => {
    const node = document.createElementNS(NS, tag);
    for (const k in attrs) if (attrs[k] != null) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  };

  /* ---------------------------------------------------------------- *
   * Shared tooltip
   * ---------------------------------------------------------------- */
  const tip = document.getElementById("tooltip");
  function showTip(evt, html) {
    tip.innerHTML = html;
    tip.style.opacity = "1";
    const pad = 14, r = tip.getBoundingClientRect();
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - pad;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  const hideTip = () => { tip.style.opacity = "0"; };
  const row = (k, v) => `<div class="row"><span>${k}</span><b>${v}</b></div>`;
  function hoverable(node, html) {
    node.style.cursor = "default";
    node.addEventListener("mousemove", (e) => showTip(e, html));
    node.addEventListener("mouseleave", hideTip);
    node.addEventListener("touchstart", (e) => showTip(e.touches[0], html), { passive: true });
  }

  /* ---------------------------------------------------------------- *
   * Chart frame: margins, scales, axes, gridlines
   * ---------------------------------------------------------------- */
  function frame(host, opts) {
    const o = Object.assign({ height: 420, m: { t: 12, r: 18, b: 44, l: 52 },
                              xLabel: "", yLabel: "" }, opts);
    const width = Math.max(host.clientWidth || 640, 280);
    const svg = el("svg", {
      viewBox: `0 0 ${width} ${o.height}`, width: "100%", height: o.height,
      role: "img", "aria-label": o.aria || o.xLabel || "chart",
    });
    svg.style.display = "block";
    svg.style.overflow = "visible";
    host.innerHTML = "";
    host.appendChild(svg);

    const iw = width - o.m.l - o.m.r;
    const ih = o.height - o.m.t - o.m.b;
    const g = el("g", { transform: `translate(${o.m.l},${o.m.t})` }, svg);

    const c = {
      svg, g, width, height: o.height, iw, ih, m: o.m,
      ink: css("--text-primary"), ink2: css("--text-secondary"),
      muted: css("--text-muted"), grid: css("--grid"), axis: css("--axis"),
      surface: css("--surface-1"), plane: css("--plane"),
      s1: css("--series-1"), s2: css("--series-2"), s3: css("--series-3"),
      dim: css("--deemphasis"),
      lo: css("--pole-low"), mid: css("--pole-mid"), hi: css("--pole-high"),
      seq: [1, 2, 3, 4, 5, 6, 7].map((i) => css("--seq-" + i)),
    };

    c.xLin = (dom, range) => scale(dom, range || [0, iw]);
    c.yLin = (dom, range) => scale(dom, range || [ih, 0]);
    c.band = (n, range) => {
      const [a, b] = range || [0, iw];
      const step = (b - a) / n;
      return (i) => a + step * (i + 0.5);
    };

    c.gridX = (x, ticks) => ticks.forEach((t) =>
      el("line", { x1: x(t), x2: x(t), y1: 0, y2: ih, stroke: c.grid, "stroke-width": 1 }, g));
    c.gridY = (y, ticks) => ticks.forEach((t) =>
      el("line", { x1: 0, x2: iw, y1: y(t), y2: y(t), stroke: c.grid, "stroke-width": 1 }, g));

    c.axisX = (x, ticks, f = (v) => fmt(v)) => {
      el("line", { x1: 0, x2: iw, y1: ih, y2: ih, stroke: c.axis, "stroke-width": 1 }, g);
      ticks.forEach((t) => text(g, x(t), ih + 18, f(t), { fill: c.ink2, anchor: "middle" }));
      if (o.xLabel) text(g, iw / 2, ih + 38, o.xLabel, { fill: c.ink2, anchor: "middle", size: 11.5 });
    };
    c.axisY = (y, ticks, f = (v) => fmt(v)) => {
      ticks.forEach((t) => text(g, -10, y(t) + 4, f(t), { fill: c.ink2, anchor: "end" }));
      if (o.yLabel) {
        const n = text(g, 0, 0, o.yLabel, { fill: c.ink2, anchor: "middle", size: 11.5 });
        n.setAttribute("transform", `translate(${-o.m.l + 14},${ih / 2}) rotate(-90)`);
      }
    };
    c.labelsY = (labels, y) => labels.forEach((lab, i) =>
      text(g, -10, y(i) + 4, lab, { fill: c.ink, anchor: "end", size: 11.5 }));
    return c;
  }

  function scale(dom, range) {
    const [d0, d1] = dom, [r0, r1] = range;
    const span = d1 - d0 || 1;
    const f = (v) => r0 + (v - d0) / span * (r1 - r0);
    f.domain = dom; f.range = range;
    return f;
  }

  function text(parent, x, y, str, o = {}) {
    const n = el("text", {
      x, y, fill: o.fill || "currentColor", "font-size": o.size || 11.5,
      "text-anchor": o.anchor || "start", "font-weight": o.weight || 400,
    }, parent);
    n.textContent = str;
    if (o.rotate) n.setAttribute("transform", `rotate(${o.rotate},${x},${y})`);
    return n;
  }

  function ticks(min, max, count = 6) {
    const span = max - min;
    if (span === 0) return [min];
    const raw = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || mag * 10;
    const out = [];
    for (let t = Math.ceil(min / step) * step; t <= max + 1e-9; t += step) out.push(+t.toFixed(10));
    return out;
  }

  const seqColor = (c, t) => c.seq[Math.min(c.seq.length - 1, Math.max(0, Math.round(t * (c.seq.length - 1))))];
  const divColor = (c, v, span) => Math.abs(v) < span * 0.05 ? c.mid : (v > 0 ? c.hi : c.lo);

  /* ================================================================ *
   * Explanatory diagrams
   * ================================================================ */

  /* The core identity, walked through for one real passport. */
  function diagramFormula(host) {
    const iso = host.dataset.country || "DEU";
    const c = D.countries[iso];
    host.innerHTML = `
      <div class="formula">
        <div class="formula-line">
          <span class="tok tok-out">score</span><span class="op">=</span>
          <span class="sum">Σ</span><span class="sub">destinations</span>
          <span class="tok tok-credit">credit</span><span class="op">×</span>
          <span class="tok tok-weight">weight</span>
        </div>
        <div class="formula-legend">
          <div><span class="chip chip-credit"></span><b>credit</b> — how frictionless the
            entry is, from 1.00 (visa-free) down to 0 (visa required). Henley allows only
            1 or 0.</div>
          <div><span class="chip chip-weight"></span><b>weight</b> — what the destination is
            worth, averaging 1.00 across the world. Henley fixes it at exactly 1 for every
            country on Earth.</div>
        </div>
      </div>
      <div class="worked" id="worked-${iso}"></div>`;

    const worked = host.querySelector(".worked");
    const rows = [
      ["Destinations reachable, Henley rule", fmt(c.henleyScore),
       "every credit is 1 or 0, every weight is exactly 1"],
      ["Same doors, graded credit", fmt(c.gradedScore, 1),
       "an eTA now counts 0.70 and an e-Visa 0.35, so the total is no longer a whole number"],
      ["Graded credit and weighted destinations", fmt(c.balancedScore, 1),
       "each destination counts as a multiple of the average one, Balanced lens"],
      ["As a share of everything attainable", fmt(c.lenses.balanced, 1) + "%",
       "the whole world, at full credit, would be 100%"],
    ];
    worked.innerHTML = `<div class="worked-title">${c.name}, step by step</div>` +
      rows.map(([k, v, note]) => `<div class="worked-row"><span>${k}</span>
        <b>${v}</b><small>${note}</small></div>`).join("");
  }

  /* The friction ladder: three rungs side by side, sized by how many pairs. */
  function diagramLadder(host) {
    const cats = S.categories.slice().sort((a, b) => b.credit - a.credit);
    const c = frame(host, { height: 300, m: { t: 26, r: 20, b: 46, l: 132 } });
    const x = c.xLin([0, 1]);
    const y = c.band(cats.length, [0, c.ih]);
    const bh = c.ih / cats.length * 0.52;

    c.gridX(x, [0, 0.25, 0.5, 0.75, 1]);
    cats.forEach((cat, i) => {
      const label = cat.category.replace(/_/g, " ");
      text(c.g, -10, y(i) + 4, label, { fill: c.ink, anchor: "end", size: 11.5 });
      // Graded credit as the filled bar; Henley's binary as an outlined marker,
      // so the gap between the two rules is the thing you see.
      const bar = el("rect", { x: 0, y: y(i) - bh / 2, width: Math.max(x(cat.credit), 1),
                               height: bh, rx: 4, fill: seqColor(c, cat.credit),
                               stroke: c.surface, "stroke-width": 2 }, c.g);
      hoverable(bar, `<strong>${label}</strong>` +
        row("Graded credit", cat.credit.toFixed(2)) +
        row("Henley's binary", cat.binary.toFixed(2)) +
        row("Strict", cat.strict.toFixed(2)) +
        row("Share of all pairs", cat.share.toFixed(1) + "%") +
        row("Median stay", cat.days ? fmt(cat.days) + " days" : "—"));
      const mark = el("path", {
        d: `M${x(cat.binary)},${y(i) - bh / 2 - 5} L${x(cat.binary)},${y(i) + bh / 2 + 5}`,
        stroke: c.s2, "stroke-width": 2.5, "stroke-linecap": "round",
      }, c.g);
      hoverable(mark, `<strong>Henley scores this ${cat.binary}</strong>`);
      text(c.g, x(cat.credit) + 8, y(i) + 4, cat.share.toFixed(1) + "% of pairs",
           { fill: c.ink2, size: 10.5 });
    });
    c.axisX(x, [0, 0.25, 0.5, 0.75, 1], (v) => v.toFixed(2));
    text(c.g, 0, -10, "Orange line = the credit Henley's binary rule gives the same regime",
         { fill: c.ink2, size: 10.5 });
  }

  /* 15 indicators → 6 pillars → one composite. */
  function diagramPipeline(host) {
    host.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "pipeline";
    const maxW = Math.max(...Object.values(S.lenses.find((l) => l.key === "balanced").weights));
    S.pillars.forEach((p) => {
      const lens = S.lenses.find((l) => l.key === "balanced");
      const w = lens.weights[p.key];
      const box = document.createElement("div");
      box.className = "pipe-pillar";
      // Weight is shown as a bar rather than a colour swatch: six categorical
      // hues on one screen cannot clear the palette's all-pairs gates, and the
      // pillar name already carries the identity.
      box.innerHTML =
        `<div class="pipe-head">
          <b>${p.label}</b>
          <span class="pipe-weight"><i style="width:${(w / maxW * 100).toFixed(0)}%"></i></span>
          <span class="pipe-w">${(w * 100).toFixed(0)}%</span></div>
         <div class="pipe-q">${p.blurb}</div>
         <ul class="pipe-list">${p.indicators.map((ind) =>
           `<li title="${ind.note}">${ind.label}
            <span class="pipe-meta">${ind.direction < 0 ? "lower is better" : ""}${
              ind.transform === "log" ? (ind.direction < 0 ? " · log" : "log") : ""}</span></li>`
         ).join("")}</ul>`;
      wrap.appendChild(box);
    });
    host.appendChild(wrap);
  }

  /* Dense vs competition vs fractional, on a worked five-passport example. */
  function diagramRanking(host) {
    const demo = [
      { name: "Passport A", score: 160 }, { name: "Passport B", score: 160 },
      { name: "Passport C", score: 160 }, { name: "Passport D", score: 155 },
      { name: "Passport E", score: 150 },
    ];
    const dense = [1, 1, 1, 2, 3];
    const comp = [1, 1, 1, 4, 5];
    const frac = [2, 2, 2, 4, 5];
    host.innerHTML = `
      <table class="rank-demo">
        <thead><tr><th></th><th>Score</th>
          <th>Dense<small>Henley's published rule</small></th>
          <th>Competition<small>displayed position</small></th>
          <th>Fractional<small>used for all movement</small></th></tr></thead>
        <tbody>${demo.map((d, i) => `<tr>
          <td class="name">${d.name}</td><td>${d.score}</td>
          <td${i < 3 ? ' class="tied"' : ""}>${dense[i]}</td>
          <td${i < 3 ? ' class="tied"' : ""}>${comp[i]}</td>
          <td${i < 3 ? ' class="tied"' : ""}>${frac[i]}</td></tr>`).join("")}
        <tr class="sum-row"><td class="name">Sum of ranks</td><td>—</td>
          <td>${dense.reduce((a, b) => a + b)}</td>
          <td>${comp.reduce((a, b) => a + b)}</td>
          <td><b>${frac.reduce((a, b) => a + b)}</b></td></tr></tbody>
      </table>
      <p class="note" style="margin:.8rem 0 0">
        Three passports tie on 160. Between them they occupy positions 1, 2 and 3 — so
        their expected position is 2. Dense and competition both hand all three a 1,
        flattering the tied index; only fractional sums to n(n+1)/2 = ${frac.reduce((a, b) => a + b)},
        which is what a second index with no ties also sums to. Difference two rankings on
        any other basis and the tied one wins by arithmetic.
      </p>`;
  }

  /* ================================================================ *
   * Interactive versions of the fifteen figures
   * ================================================================ */

  function chartRankMovement(host) {
    const n = +(host.dataset.n || 14);
    const all = Object.values(D.countries).map((c) => ({
      c, move: c.henleyFrac - c.balancedFrac,
    }));
    all.sort((a, b) => b.move - a.move);
    const rows = all.slice(0, n).concat(all.slice(-n)).sort((a, b) => a.move - b.move);

    const c = frame(host, { height: 30 * rows.length + 70,
                            m: { t: 12, r: 60, b: 46, l: 132 },
                            xLabel: "Expected position out of 199 (1 = strongest)" });
    const maxRank = Math.max(...rows.flatMap((r) => [r.c.henleyFrac, r.c.balancedFrac]));
    const x = c.xLin([maxRank + 14, 0]);
    const y = c.band(rows.length, [0, c.ih]);
    const tk = ticks(0, maxRank + 14, 6);
    c.gridX(x, tk);

    rows.forEach((r, i) => {
      const col = divColor(c, r.move, 20);
      el("line", { x1: x(r.c.henleyFrac), x2: x(r.c.balancedFrac), y1: y(i), y2: y(i),
                   stroke: col, "stroke-width": 2.5, "stroke-linecap": "round" }, c.g);
      el("circle", { cx: x(r.c.henleyFrac), cy: y(i), r: 5, fill: c.dim,
                     stroke: c.surface, "stroke-width": 2 }, c.g);
      const dot = el("circle", { cx: x(r.c.balancedFrac), cy: y(i), r: 6.5, fill: col,
                                 stroke: c.surface, "stroke-width": 2 }, c.g);
      text(c.g, -10, y(i) + 4, r.c.name, { fill: c.ink, anchor: "end" });
      text(c.g, x(Math.max(r.c.henleyFrac, r.c.balancedFrac)) - 10, y(i) + 4,
           (r.move > 0 ? "+" : "") + r.move.toFixed(1), { fill: c.ink2, anchor: "end", size: 10.5 });
      const html = `<strong>${r.c.name}</strong>` +
        row("Henley rule", r.c.henleyFrac.toFixed(1)) +
        row("Opportunity-weighted", r.c.balancedFrac.toFixed(1)) +
        row("Movement", (r.move > 0 ? "+" : "") + r.move.toFixed(1)) +
        row("of which weighting", r.c.weightingEffect.toFixed(1)) +
        row("of which friction", r.c.frictionEffect.toFixed(1));
      [dot, c.g.lastChild].forEach(() => {});
      hoverable(dot, html);
      const band = el("rect", { x: 0, y: y(i) - c.ih / rows.length / 2, width: c.iw,
                                height: c.ih / rows.length, fill: "transparent" }, c.g);
      hoverable(band, html);
    });
    c.axisX(x, tk);
  }

  function chartAgreement(host) {
    const { labels, matrix } = S.agreement;
    const n = labels.length;
    const c = frame(host, { height: Math.max(host.clientWidth * 0.86, 420),
                            m: { t: 8, r: 12, b: 128, l: 132 } });
    const cell = Math.min(c.iw / n, c.ih / n);
    const lo = Math.min(...matrix.flat());
    matrix.forEach((rowv, i) => rowv.forEach((v, j) => {
      const t = (v - lo) / (1 - lo || 1);
      const r = el("rect", { x: j * cell, y: i * cell, width: cell - 1.5, height: cell - 1.5,
                             rx: 2, fill: seqColor(c, t) }, c.g);
      hoverable(r, `<strong>${labels[i]} vs ${labels[j]}</strong>` +
        row("Kendall's tau-b", v.toFixed(3)) +
        `<div class="row" style="margin-top:.3rem"><span>${
          v > 0.97 ? "Effectively the same ranking" :
          v > 0.9 ? "Very close" : "The choice changed the answer"}</span></div>`);
      if (cell > 26) {
        text(c.g, j * cell + cell / 2 - 0.75, i * cell + cell / 2 + 3, v.toFixed(2), {
          fill: t > 0.55 ? c.surface : c.ink2, anchor: "middle", size: Math.min(cell / 3.4, 9),
        });
      }
    }));
    labels.forEach((lab, i) => {
      text(c.g, -8, i * cell + cell / 2 + 3.5, lab, { fill: c.ink2, anchor: "end", size: 10 });
      const t = text(c.g, i * cell + cell / 2, n * cell + 10, lab,
                     { fill: c.ink2, anchor: "end", size: 10 });
      t.setAttribute("transform", `rotate(-45,${i * cell + cell / 2},${n * cell + 10})`);
    });
  }

  function chartMonteCarlo(host) {
    const n = +(host.dataset.n || 30);
    const rows = Object.values(D.countries)
      .sort((a, b) => a.mcMedian - b.mcMedian).slice(0, n);
    const c = frame(host, { height: 26 * rows.length + 70,
                            m: { t: 12, r: 24, b: 46, l: 132 },
                            xLabel: "Expected position across 3,000 resampled weightings" });
    const max = Math.max(...rows.map((r) => r.mcHigh));
    const x = c.xLin([max + 2, 0]);
    const y = c.band(rows.length, [0, c.ih]);
    const tk = ticks(0, max + 2, 6);
    c.gridX(x, tk);
    rows.forEach((r, i) => {
      el("line", { x1: x(r.mcLow), x2: x(r.mcHigh), y1: y(i), y2: y(i),
                   stroke: c.seq[2], "stroke-width": 7, "stroke-linecap": "round",
                   opacity: 0.9 }, c.g);
      const dot = el("circle", { cx: x(r.mcMedian), cy: y(i), r: 5.5, fill: c.s1,
                                 stroke: c.surface, "stroke-width": 2 }, c.g);
      text(c.g, -10, y(i) + 4, r.name, { fill: c.ink, anchor: "end" });
      const html = `<strong>${r.name}</strong>` +
        row("Median position", r.mcMedian.toFixed(1)) +
        row("5th percentile", r.mcLow.toFixed(1)) +
        row("95th percentile", r.mcHigh.toFixed(1)) +
        row("Interval width", (r.mcHigh - r.mcLow).toFixed(1) + " places");
      hoverable(dot, html);
      hoverable(el("rect", { x: 0, y: y(i) - c.ih / rows.length / 2, width: c.iw,
                             height: c.ih / rows.length, fill: "transparent" }, c.g), html);
    });
    c.axisX(x, tk);
  }

  function chartLadder(host) {
    const n = +(host.dataset.n || 12);
    const rows = Object.values(D.countries).map((c) => ({
      c, spread: Math.max(c.ladder.binary, c.ladder.graded, c.ladder.strict) -
                 Math.min(c.ladder.binary, c.ladder.graded, c.ladder.strict),
    })).sort((a, b) => b.spread - a.spread).slice(0, n);

    const c = frame(host, { height: 460, m: { t: 24, r: 150, b: 56, l: 56 },
                            yLabel: "Expected position out of 199" });
    const stages = ["binary", "graded", "strict"];
    const stageLabels = ["Henley's binary", "Graded friction", "Strict"];
    const vals = rows.flatMap((r) => stages.map((s) => r.c.ladder[s]));
    const y = c.yLin([Math.min(...vals) - 3, Math.max(...vals) + 3], [0, c.ih]);
    const x = c.band(3);
    const tk = ticks(Math.min(...vals), Math.max(...vals), 5);
    c.gridY(y, tk);

    rows.forEach((r) => {
      const pts = stages.map((s, i) => [x(i), y(r.c.ladder[s])]);
      const drop = r.c.ladder.strict - r.c.ladder.binary;
      const col = divColor(c, -drop, 15);
      const path = el("path", {
        d: pts.map((p, i) => (i ? "L" : "M") + p[0] + "," + p[1]).join(" "),
        fill: "none", stroke: col, "stroke-width": 2.4, opacity: 0.85,
      }, c.g);
      const html = `<strong>${r.c.name}</strong>` +
        row("Henley's binary", r.c.ladder.binary.toFixed(1)) +
        row("Graded friction", r.c.ladder.graded.toFixed(1)) +
        row("Strict (visa-free only)", r.c.ladder.strict.toFixed(1)) +
        row("Spread", r.spread.toFixed(1) + " places");
      hoverable(path, html);
      pts.forEach((p) => hoverable(
        el("circle", { cx: p[0], cy: p[1], r: 4.5, fill: col, stroke: c.surface,
                       "stroke-width": 2 }, c.g), html));
      text(c.g, x(2) + 12, y(r.c.ladder.strict) + 4, r.c.name, { fill: c.ink2, size: 10.5 });
    });
    stageLabels.forEach((lab, i) =>
      text(c.g, x(i), c.ih + 22, lab, { fill: c.ink2, anchor: "middle", size: 11 }));
    c.axisY(y, tk);
  }

  function chartWeightDistribution(host) {
    const data = S.destinationWeights;
    const c = frame(host, { height: 330, m: { t: 26, r: 20, b: 52, l: 52 },
                            xLabel: "Destination weight (multiple of the average destination)",
                            yLabel: "Destinations" });
    const vals = data.map((d) => d.w);
    const lo = Math.min(...vals), hi = Math.max(...vals);
    const bins = 32, step = (hi - lo) / bins;
    const buckets = Array.from({ length: bins }, () => []);
    data.forEach((d) => buckets[Math.min(bins - 1, Math.floor((d.w - lo) / step))].push(d));
    const maxCount = Math.max(...buckets.map((b) => b.length));
    const x = c.xLin([lo, hi]);
    const y = c.yLin([0, maxCount]);
    c.gridY(y, ticks(0, maxCount, 5));

    buckets.forEach((b, i) => {
      if (!b.length) return;
      const bx = x(lo + i * step), bw = Math.max(x(lo + (i + 1) * step) - bx - 1.5, 1);
      const r = el("rect", { x: bx, y: y(b.length), width: bw, height: c.ih - y(b.length),
                             fill: c.seq[3], rx: 2 }, c.g);
      const names = b.slice(0, 8).map((d) => d.name).join(", ");
      hoverable(r, `<strong>${(lo + i * step).toFixed(2)}–${(lo + (i + 1) * step).toFixed(2)}×</strong>` +
        row("Destinations", b.length) +
        `<div class="row" style="margin-top:.3rem"><span>${names}${b.length > 8 ? "…" : ""}</span></div>`);
    });
    el("line", { x1: x(1), x2: x(1), y1: 0, y2: c.ih, stroke: c.muted,
                 "stroke-width": 1.5, "stroke-dasharray": "4 3" }, c.g);
    text(c.g, x(1) + 6, 12, "average destination = 1.0", { fill: c.ink2, size: 10.5 });
    c.axisX(x, ticks(lo, hi, 6), (v) => v.toFixed(1));
    c.axisY(y, ticks(0, maxCount, 5));
  }

  function chartPillarTilt(host) {
    const picks = (host.dataset.countries || "SGP,ARE,JPN,DEU,USA,GBR,MYS,CHN,RUS,BRA,ZAF,IND,NGA,AFG")
      .split(",").filter((i) => D.countries[i]);
    const c = frame(host, { height: 34 * picks.length + 60,
                            m: { t: 26, r: 20, b: 34, l: 168 } });
    const cw = c.iw / PILLARS.length;
    const rh = c.ih / picks.length;
    const span = Math.max(...picks.flatMap((i) =>
      PILLARS.map((p) => Math.abs(D.countries[i].pillars[p].tilt))));

    picks.forEach((iso, i) => {
      const co = D.countries[iso];
      text(c.g, -10, i * rh + rh / 2 + 4,
           `${co.name}  (${fmt(co.pillars.economy.att && Object.values(co.pillars)
             .reduce((a, p) => a + p.att, 0) / 6, 0)}% overall)`,
           { fill: c.ink, anchor: "end", size: 11 });
      PILLARS.forEach((p, j) => {
        const { att, tilt } = co.pillars[p];
        const t = tilt / span;
        const fill = Math.abs(t) < 0.06 ? c.mid
          : mixHex(c.mid, t > 0 ? c.hi : c.lo, Math.min(Math.abs(t), 1));
        const r = el("rect", { x: j * cw, y: i * rh, width: cw - 2, height: rh - 2,
                               rx: 3, fill }, c.g);
        hoverable(r, `<strong>${co.name} · ${PILLAR_LABELS[p]}</strong>` +
          row("Share of the world reached", att.toFixed(1) + "%") +
          row("vs. its own average", (tilt > 0 ? "+" : "") + tilt.toFixed(1) + " pts") +
          `<div class="row" style="margin-top:.3rem"><span>${
            S.pillars.find((x) => x.key === p).blurb}</span></div>`);
        text(c.g, j * cw + cw / 2 - 1, i * rh + rh / 2 + 4, Math.round(att) + "%",
             { fill: Math.abs(t) > 0.55 ? c.surface : c.ink2, anchor: "middle", size: 10.5 });
      });
    });
    PILLARS.forEach((p, j) =>
      text(c.g, j * cw + cw / 2, -8, PILLAR_LABELS[p], { fill: c.ink2, anchor: "middle", size: 11 }));
  }

  function mixHex(a, b, t) {
    const pa = parseColor(a), pb = parseColor(b);
    if (!pa || !pb) return b;
    return `rgb(${pa.map((v, i) => Math.round(v + (pb[i] - v) * t)).join(",")})`;
  }
  function parseColor(col) {
    if (col.startsWith("#")) {
      const h = col.slice(1), f = h.length === 3 ? h.split("").map((x) => x + x).join("") : h;
      return [0, 2, 4].map((i) => parseInt(f.slice(i, i + 2), 16));
    }
    const m = col.match(/rgba?\(([^)]+)\)/);
    return m ? m[1].split(",").slice(0, 3).map(parseFloat) : null;
  }

  /* Generic scatter used by reciprocity, clusters, residuals and stay-days. */
  function scatter(host, opts) {
    const pts = opts.points;
    const c = frame(host, Object.assign({ height: 460, m: { t: 16, r: 24, b: 52, l: 60 } }, opts));
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const xd = opts.xDomain || [Math.min(...xs) * 0.98, Math.max(...xs) * 1.02];
    const yd = opts.yDomain || [Math.min(...ys) * 0.98, Math.max(...ys) * 1.02];
    const x = c.xLin(xd), y = c.yLin(yd);
    const tx = ticks(xd[0], xd[1], 6), ty = ticks(yd[0], yd[1], 6);
    c.gridX(x, tx); c.gridY(y, ty);
    if (opts.diagonal) {
      const lo = Math.max(xd[0], yd[0]), hi = Math.min(xd[1], yd[1]);
      el("line", { x1: x(lo), y1: y(lo), x2: x(hi), y2: y(hi), stroke: c.muted,
                   "stroke-width": 1.5, "stroke-dasharray": "4 3" }, c.g);
    }
    pts.forEach((p) => {
      const dot = el("circle", { cx: x(p.x), cy: y(p.y), r: p.r || 4.6,
                                 fill: p.fill || c.dim, stroke: c.surface,
                                 "stroke-width": 1.6 }, c.g);
      hoverable(dot, p.tip);
      if (p.label) text(c.g, x(p.x) + 8, y(p.y) - 5, p.label, { fill: c.ink2, size: 10 });
    });
    c.axisX(x, tx, opts.xFmt); c.axisY(y, ty, opts.yFmt);
    return c;
  }

  function chartReciprocity(host) {
    const all = Object.values(D.countries);
    const extreme = all.slice().sort((a, b) => b.balance - a.balance);
    const named = new Set(extreme.slice(0, 6).concat(extreme.slice(-6)).map((c) => c.iso));
    const c0 = css("--deemphasis");
    scatter(host, {
      xLabel: "Nationalities admitted without a prior visa",
      yLabel: "Destinations reachable without a prior visa",
      diagonal: true, xDomain: [0, 205], yDomain: [0, 175],
      points: all.map((c) => ({
        x: c.admits, y: c.reaches,
        r: named.has(c.iso) ? 6.5 : 4.2,
        fill: named.has(c.iso) ? (c.balance > 0 ? css("--pole-high") : css("--pole-low")) : c0,
        label: named.has(c.iso) ? c.name : null,
        tip: `<strong>${c.name}</strong>` + row("Reaches", c.reaches) +
             row("Admits", c.admits) +
             row("Mobility balance", (c.balance > 0 ? "+" : "") + c.balance) +
             row("Reciprocated", c.reciprocated == null ? "—" : c.reciprocated + "%"),
      })),
    });
  }

  function chartClusters(host) {
    const palette = [css("--series-1"), css("--series-2"), css("--series-3"), css("--text-muted")];
    const order = S.clusters.map((c) => c.label);
    const spotlight = new Set(["USA", "CHN", "IND", "NGA", "DEU", "ARE", "SGP", "BRA", "RUS", "ZAF"]);
    scatter(host, {
      xLabel: "Nationalities admitted without a prior visa",
      yLabel: "Destinations reachable without a prior visa",
      xDomain: [0, 205], yDomain: [0, 175],
      points: Object.values(D.countries).map((c) => {
        const i = Math.max(order.indexOf(c.clusterLabel), 0);
        const prof = S.clusters[i];
        return {
          x: c.admits, y: c.reaches, r: spotlight.has(c.iso) ? 6.5 : 4.6,
          fill: palette[i], label: spotlight.has(c.iso) ? c.name : null,
          tip: `<strong>${c.name}</strong>` +
               `<div class="row"><span>${c.clusterLabel}</span></div>` +
               row("Reaches / admits", `${c.reaches} / ${c.admits}`) +
               row("Attainment", c.lenses.balanced.toFixed(1) + "%") +
               `<div class="row" style="margin-top:.3rem"><span>${prof.description}</span></div>`,
        };
      }),
    });
    legend(host, order.map((l, i) => ({
      label: `${l} (n=${S.clusters[i].members})`, color: palette[i],
    })));
  }

  function chartResiduals(host) {
    const all = Object.values(D.countries);
    const sorted = all.slice().sort((a, b) => b.residual - a.residual);
    const named = new Set(sorted.slice(0, 7).concat(sorted.slice(-7)).map((c) => c.iso));
    scatter(host, {
      xLabel: "Predicted access from own wealth, development, size and institutions",
      yLabel: "Actual access (% of the attainable maximum)",
      diagonal: true, xFmt: (v) => v + "%", yFmt: (v) => v + "%",
      points: all.map((c) => ({
        x: c.predicted, y: c.lenses.balanced,
        r: named.has(c.iso) ? 6.5 : 4.2,
        fill: named.has(c.iso) ? (c.residual > 0 ? css("--pole-high") : css("--pole-low"))
                               : css("--deemphasis"),
        label: named.has(c.iso) ? c.name : null,
        tip: `<strong>${c.name}</strong>` +
             row("Actual", c.lenses.balanced.toFixed(1) + "%") +
             row("Predicted", c.predicted.toFixed(1) + "%") +
             row("Residual", (c.residual > 0 ? "+" : "") + c.residual.toFixed(1) + " pts"),
      })),
    });
  }

  function chartStayDays(host) {
    const all = Object.values(D.countries);
    const withRatio = all.map((c) => ({ c, ratio: c.stayDays / Math.max(c.henleyScore, 1) }));
    const sorted = withRatio.slice().sort((a, b) => b.ratio - a.ratio);
    const named = new Set(sorted.slice(0, 4).concat(sorted.slice(-4)).map((d) => d.c.iso));
    const median = sorted[Math.floor(sorted.length / 2)].ratio;
    scatter(host, {
      xLabel: "Destinations reachable without a prior visa (the published index)",
      yLabel: "Permitted person-years of frictionless presence",
      points: withRatio.map(({ c, ratio }) => ({
        x: c.henleyScore, y: c.stayDays / 365,
        r: named.has(c.iso) ? 6.5 : 4.2,
        fill: named.has(c.iso) ? (ratio > median ? css("--series-1") : css("--series-2"))
                               : css("--deemphasis"),
        label: named.has(c.iso) ? c.name : null,
        tip: `<strong>${c.name}</strong>` +
             row("Destinations", c.henleyScore) +
             row("Permitted days", fmt(c.stayDays)) +
             row("Days per destination", ratio.toFixed(0)),
      })),
    });
  }

  function chartLorenz(host) {
    const entries = Object.entries(S.lorenz);
    const c = frame(host, { height: 420, m: { t: 16, r: 20, b: 52, l: 60 },
                            xLabel: "Cumulative share of passports, weakest first",
                            yLabel: "Cumulative share of total access" });
    const x = c.xLin([0, 1]), y = c.yLin([0, 1]);
    const tk = [0, 0.2, 0.4, 0.6, 0.8, 1];
    c.gridX(x, tk); c.gridY(y, tk);
    el("line", { x1: x(0), y1: y(0), x2: x(1), y2: y(1), stroke: c.muted,
                 "stroke-width": 1.5, "stroke-dasharray": "4 3" }, c.g);
    const cols = [c.s1, c.s2, c.s3];
    entries.forEach(([label, series], i) => {
      const d = series.points.map((p, j) => (j ? "L" : "M") + x(p[0]) + "," + y(p[1])).join(" ");
      const path = el("path", { d, fill: "none", stroke: cols[i], "stroke-width": 2.4 }, c.g);
      hoverable(path, `<strong>${label}</strong>` + row("Gini", series.gini.toFixed(2)) +
        `<div class="row" style="margin-top:.3rem"><span>The further the curve sags below the
         diagonal, the more concentrated that measure of access is.</span></div>`);
    });
    c.axisX(x, tk, (v) => Math.round(v * 100) + "%");
    c.axisY(y, tk, (v) => Math.round(v * 100) + "%");
    legend(host, entries.map(([label, s], i) =>
      ({ label: `${label} (Gini ${s.gini.toFixed(2)})`, color: cols[i] })));
  }

  function chartDivide(host) {
    const rows = S.divide.slice().sort((a, b) => a.access - b.access);
    const c = frame(host, { height: 44 * rows.length + 76,
                            m: { t: 12, r: 20, b: 50, l: 152 },
                            xLabel: "Mean share of the world's weighted opportunity reachable" });
    const x = c.xLin([0, 100]);
    const y = c.band(rows.length, [0, c.ih]);
    const bh = c.ih / rows.length * 0.52;
    c.gridX(x, [0, 20, 40, 60, 80, 100]);
    rows.forEach((r, i) => {
      const bar = el("rect", { x: 0, y: y(i) - bh / 2, width: x(r.access), height: bh,
                               rx: 4, fill: seqColor(c, r.access / 100) }, c.g);
      hoverable(bar, `<strong>${r.group}</strong>` +
        row("Mean access", r.access.toFixed(1) + "%") +
        row("Countries", r.countries) +
        row("Share of world population", r.people + "%"));
      text(c.g, -10, y(i) + 4, r.group, { fill: c.ink, anchor: "end" });
      text(c.g, x(r.access) + 8, y(i) + 4,
           `${r.access.toFixed(0)}%  ·  ${r.countries} countries  ·  ${r.people}% of people`,
           { fill: c.ink2, size: 10.5 });
    });
    c.axisX(x, [0, 20, 40, 60, 80, 100], (v) => v + "%");
  }

  function chartPca(host) {
    const rows = S.pca.slice().sort((a, b) => Math.abs(a.loading) - Math.abs(b.loading));
    const c = frame(host, { height: 30 * rows.length + 70,
                            m: { t: 12, r: 24, b: 50, l: 178 },
                            xLabel: "Loading on the first principal component" });
    const max = Math.max(...rows.map((r) => Math.abs(r.loading))) * 1.1;
    const x = c.xLin([-max, max]);
    const y = c.band(rows.length, [0, c.ih]);
    const bh = c.ih / rows.length * 0.55;
    c.gridX(x, ticks(-max, max, 5));
    rows.forEach((r, i) => {
      const x0 = Math.min(x(0), x(r.loading)), w = Math.abs(x(r.loading) - x(0));
      const bar = el("rect", { x: x0, y: y(i) - bh / 2, width: Math.max(w, 1), height: bh,
                               rx: 3, fill: divColor(c, r.loading, max) }, c.g);
      hoverable(bar, `<strong>${r.indicator}</strong>` +
        `<div class="row"><span>${PILLAR_LABELS[r.pillar]} pillar</span></div>` +
        row("PC1 loading", r.loading.toFixed(3)) +
        row("Entropy weight", r.entropy.toFixed(4)));
      text(c.g, -10, y(i) + 4, r.indicator.replace(/_/g, " "), { fill: c.ink, anchor: "end", size: 10.5 });
    });
    el("line", { x1: x(0), x2: x(0), y1: 0, y2: c.ih, stroke: c.axis, "stroke-width": 1.2 }, c.g);
    c.axisX(x, ticks(-max, max, 5), (v) => v.toFixed(1));
  }

  function chartDispersion(host) {
    const rows = S.dispersion;
    const c = frame(host, { height: 320, m: { t: 34, r: 28, b: 58, l: 60 },
                            yLabel: "Kendall's tau vs. the plain count" });
    const x = c.band(rows.length);
    const ys = rows.map((r) => r.tau);
    const y = c.yLin([Math.min(...ys) - 0.02, 1.005]);
    const tk = ticks(Math.min(...ys) - 0.02, 1, 5);
    c.gridY(y, tk);
    const d = rows.map((r, i) => (i ? "L" : "M") + x(i) + "," + y(r.tau)).join(" ");
    el("path", { d, fill: "none", stroke: c.s1, "stroke-width": 2.4 }, c.g);
    rows.forEach((r, i) => {
      const dot = el("circle", { cx: x(i), cy: y(r.tau), r: 6, fill: c.s1,
                                 stroke: c.surface, "stroke-width": 2 }, c.g);
      hoverable(dot, `<strong>${r.variant}</strong>` +
        row("Best-to-worst weight ratio", r.ratio + "×") +
        row("Gini of destination weight", r.gini.toFixed(3)) +
        row("Kendall tau vs. plain count", r.tau.toFixed(3)));
      text(c.g, x(i), y(r.tau) - 14, r.tau.toFixed(3), { fill: c.ink2, anchor: "middle", size: 10.5 });
      text(c.g, x(i), c.ih + 22, r.variant.split(" (")[0], { fill: c.ink2, anchor: "middle", size: 10.5 });
      text(c.g, x(i), c.ih + 36, r.ratio + "× spread", { fill: c.muted, anchor: "middle", size: 10 });
    });
    c.axisY(y, tk, (v) => v.toFixed(2));
  }

  function chartBlocs(host) {
    const rows = S.blocs.slice().sort((a, b) => a.external - b.external);
    const c = frame(host, { height: 42 * rows.length + 72,
                            m: { t: 12, r: 20, b: 50, l: 132 },
                            xLabel: "Mean destinations a member reaches outside its own bloc" });
    const max = Math.max(...rows.map((r) => r.external)) * 1.9;
    const x = c.xLin([0, max]);
    const y = c.band(rows.length, [0, c.ih]);
    const bh = c.ih / rows.length * 0.52;
    c.gridX(x, ticks(0, max, 6));
    rows.forEach((r, i) => {
      const bar = el("rect", { x: 0, y: y(i) - bh / 2, width: x(r.external), height: bh,
                               rx: 4, fill: seqColor(c, r.external / Math.max(...rows.map((q) => q.external))) }, c.g);
      hoverable(bar, `<strong>${r.bloc}</strong>` +
        row("Members in data", r.members) +
        row("Frictionless within bloc", r.internal.toFixed(1) + "%") +
        row("Mean reach outside", r.external.toFixed(1)));
      text(c.g, -10, y(i) + 4, r.bloc, { fill: c.ink, anchor: "end" });
      text(c.g, x(r.external) + 8, y(i) + 4,
           `${r.external.toFixed(0)} outside · ${r.internal.toFixed(0)}% frictionless within`,
           { fill: c.ink2, size: 10.5 });
    });
    c.axisX(x, ticks(0, max, 6));
  }

  function legend(host, items) {
    const box = document.createElement("div");
    box.className = "chart-legend";
    box.innerHTML = items.map((i) =>
      `<span><i style="background:${i.color}"></i>${i.label}</span>`).join("");
    host.appendChild(box);
  }

  /* ================================================================ *
   * Live weight explorer — the index, recomputed in the browser
   * ================================================================ */
  function explorer(host) {
    const base = S.engine.headline;
    let w = Object.assign({}, base);
    const codes = Object.keys(D.countries);
    const T = S.engine.totals, N = S.engine.n;

    host.innerHTML = `
      <div class="explorer">
        <div class="sliders" id="ex-sliders"></div>
        <div class="ex-out">
          <div class="ex-head">
            <div><span class="panel-title">Top 15 under your weights</span>
              <div class="panel-sub" id="ex-summary"></div></div>
            <button class="reset" id="ex-reset" type="button">Reset to Balanced</button>
          </div>
          <ol class="ex-list" id="ex-list"></ol>
        </div>
      </div>`;

    const sliders = host.querySelector("#ex-sliders");
    PILLARS.forEach((p) => {
      const wrap = document.createElement("label");
      wrap.className = "slider";
      wrap.innerHTML = `<span class="slider-label">${PILLAR_LABELS[p]}
        <b id="ex-v-${p}">${Math.round(base[p] * 100)}%</b></span>
        <input type="range" min="0" max="60" step="1" value="${Math.round(base[p] * 100)}"
               id="ex-${p}" aria-label="${PILLAR_LABELS[p]} weight">
        <span class="slider-blurb">${S.pillars.find((x) => x.key === p).blurb}</span>`;
      sliders.appendChild(wrap);
      wrap.querySelector("input").addEventListener("input", (e) => {
        w[p] = +e.target.value / 100;
        render();
      });
    });
    host.querySelector("#ex-reset").addEventListener("click", () => {
      w = Object.assign({}, base);
      PILLARS.forEach((p) => {
        host.querySelector("#ex-" + p).value = Math.round(base[p] * 100);
      });
      render();
    });

    function render() {
      const total = PILLARS.reduce((a, p) => a + w[p], 0) || 1;
      const wn = {}; PILLARS.forEach((p) => (wn[p] = w[p] / total));
      PILLARS.forEach((p) => {
        host.querySelector("#ex-v-" + p).textContent = Math.round(wn[p] * 100) + "%";
      });

      const denomT = PILLARS.reduce((a, p, i) => a + wn[p] * T[p], 0);
      const scored = codes.map((iso) => {
        const co = D.countries[iso];
        let num = 0, ceil = 0;
        PILLARS.forEach((p, i) => {
          num += wn[p] * co.c[i];
          ceil += wn[p] * (T[p] - co.own[i]);
        });
        return { iso, name: co.name, score: N * num / denomT, pct: 100 * num / ceil,
                 base: co.pos.balanced };
      }).sort((a, b) => b.score - a.score);

      const list = host.querySelector("#ex-list");
      list.innerHTML = scored.slice(0, 15).map((s, i) => {
        const shift = s.base - (i + 1);
        const badge = shift === 0 ? "" :
          `<span class="${shift > 0 ? "delta-up" : "delta-down"}">${shift > 0 ? "▲" : "▼"}${Math.abs(shift)}</span>`;
        return `<li><span class="ex-rank">${i + 1}</span>
          <span class="ex-name">${s.name}</span>
          <span class="ex-score">${s.pct.toFixed(1)}%</span>${badge}</li>`;
      }).join("");

      // How far this weighting moved the whole table, not just the top of it.
      const byIso = {}; scored.forEach((s, i) => (byIso[s.iso] = i + 1));
      let moved = 0, maxMove = 0, maxName = "";
      codes.forEach((iso) => {
        const d = Math.abs(D.countries[iso].pos.balanced - byIso[iso]);
        if (d > 0) moved++;
        if (d > maxMove) { maxMove = d; maxName = D.countries[iso].name; }
      });
      host.querySelector("#ex-summary").textContent =
        `${moved} of ${codes.length} passports change position versus the published Balanced ` +
        `lens; the largest single move is ${maxMove} places (${maxName}). ▲▼ is against Balanced.`;
    }
    render();
  }

  /* ================================================================ *
   * Registry + lifecycle
   * ================================================================ */
  const CHARTS = {
    "diagram-formula": diagramFormula,
    "diagram-ladder": diagramLadder,
    "diagram-pipeline": diagramPipeline,
    "diagram-ranking": diagramRanking,
    "rank-movement": chartRankMovement,
    "agreement": chartAgreement,
    "monte-carlo": chartMonteCarlo,
    "ladder": chartLadder,
    "weight-distribution": chartWeightDistribution,
    "pillar-tilt": chartPillarTilt,
    "reciprocity": chartReciprocity,
    "lorenz": chartLorenz,
    "residuals": chartResiduals,
    "divide": chartDivide,
    "pca": chartPca,
    "clusters": chartClusters,
    "dispersion": chartDispersion,
    "blocs": chartBlocs,
    "stay-days": chartStayDays,
    "explorer": explorer,
  };

  function renderAll() {
    document.querySelectorAll("[data-chart]").forEach((host) => {
      const fn = CHARTS[host.dataset.chart];
      if (!fn) return;
      try {
        fn(host);
      } catch (err) {
        host.innerHTML = `<p class="note">This chart could not be drawn.</p>`;
        console.error(host.dataset.chart, err);
      }
    });
  }

  // The explorer holds slider state, so it is rebuilt only when the theme
  // changes (colours come from CSS variables) rather than on every resize.
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      document.querySelectorAll("[data-chart]").forEach((host) => {
        if (host.dataset.chart === "explorer") return;
        const fn = CHARTS[host.dataset.chart];
        if (fn) try { fn(host); } catch (e) { console.error(e); }
      });
    }, 180);
  });

  window.AHI_RENDER_CHARTS = renderAll;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderAll);
  } else {
    renderAll();
  }
})();
