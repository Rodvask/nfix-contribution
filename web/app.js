/* nfix-contribution v2 dashboard — no build step, no external requests */
const TABS = [
  ["overview", "Resumen"],
  ["tags", "Tags"],
  ["grind", "Grind / derisk"],
  ["versions", "Versiones"],
  ["pairs", "Pares"],
  ["exits", "Salidas"],
  ["trades", "Trades"],
  ["worst", "Peores"],
];

const state = {
  tab: location.hash.replace("#", "") || "overview",
  detail: null,
  page: 1,
};
const $ = (id) => document.getElementById(id);
const view = () => $("view");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v) ? "·" : Number(v).toFixed(d));
const pct = (v, d = 2) => (v === null || v === undefined ? "·" : (v >= 0 ? "+" : "") + Number(v).toFixed(d) + "%");
const signed = (v, d = 2) => `<span class="${v >= 0 ? "pos" : "neg"}">${pct(v, d)}</span>`;
const bar = (v, max, cls = "") => {
  const w = max > 0 ? Math.min(100, (Math.abs(v) / max) * 100) : 0;
  return `<div class="bar ${cls}"><i style="width:${w.toFixed(1)}%"></i></div>`;
};

function params(extra = {}) {
  const p = {
    days: $("f-days").value,
    version: $("f-version").value,
    system_version: $("f-system").value,
    side: $("f-side").value,
    exchange: $("f-exchange").value,
    ...extra,
  };
  const token = $("f-token").value.trim();
  if (token) p.token = token;
  return p;
}

async function api(path, extra) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params(extra))) if (v !== "" && v !== null && v !== undefined) q.set(k, v);
  const res = await fetch(`${path}?${q.toString()}`);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || res.statusText);
  return body;
}

function table(cols, rows, opts = {}) {
  const head = cols.map((c) => `<th data-k="${c.k}" class="${c.cls || ""}">${esc(c.label)}</th>`).join("");
  const body = rows
    .map((r, i) => {
      const cells = cols
        .map((c) => {
          const raw = r[c.k];
          const text = c.fmt ? c.fmt(raw, r) : esc(raw ?? "");
          return `<td class="${c.cls || ""}">${text}</td>`;
        })
        .join("");
      return `<tr class="${opts.onRow ? "clickable" : ""}" data-i="${i}">${cells}</tr>`;
    })
    .join("");
  if (!rows.length) return `<p class="muted">Sin datos con estos filtros.</p>`;
  return `<div class="scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function wireTable(container, cols, rows, opts = {}) {
  const tableEl = container.querySelector("table");
  if (!tableEl) return;
  tableEl.querySelectorAll("th").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.k;
      const col = cols.find((c) => c.k === key);
      const dir = th.dataset.dir === "asc" ? "desc" : "asc";
      tableEl.querySelectorAll("th").forEach((h) => delete h.dataset.dir);
      th.dataset.dir = dir;
      const numeric = col && col.type !== "text";
      const sorted = [...rows].sort((a, b) => {
        const va = a[key];
        const vb = b[key];
        if (numeric) return dir === "asc" ? (va ?? -Infinity) - (vb ?? -Infinity) : (vb ?? -Infinity) - (va ?? -Infinity);
        return dir === "asc" ? String(va ?? "").localeCompare(String(vb ?? "")) : String(vb ?? "").localeCompare(String(va ?? ""));
      });
      const html = table(cols, sorted, opts);
      const scroll = container.querySelector(".scroll");
      if (scroll) scroll.outerHTML = html;
      else container.innerHTML = html;
      wireTable(container, cols, sorted, opts);
    });
  });
  if (opts.onRow) {
    tableEl.querySelectorAll("tbody tr").forEach((tr) => {
      tr.addEventListener("click", () => opts.onRow(rows[Number(tr.dataset.i)]));
    });
  }
}

function kpis(items) {
  return `<div class="kpis">${items
    .map((i) => `<div class="kpi"><div class="k">${esc(i.k)}</div><div class="v ${i.cls || ""}">${i.v}</div><div class="s">${i.s || ""}</div></div>`)
    .join("")}</div>`;
}

function sparkline(values, { width = 260, height = 42, cls = "" } = {}) {
  if (!values.length) return "";
  const max = Math.max(...values.map(Math.abs), 0.0001);
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values
    .map((v, i) => `${(i * step).toFixed(1)},${(height / 2 - (v / max) * (height / 2 - 3)).toFixed(1)}`)
    .join(" ");
  return `<svg class="spark ${cls}" width="${width}" height="${height}" role="img">
    <line x1="0" y1="${height / 2}" x2="${width}" y2="${height / 2}" stroke="#223046" stroke-width="1"/>
    <polyline points="${points}" fill="none" stroke="#4da3ff" stroke-width="1.6"/></svg>`;
}

const AGG_COLS = (prefix = "") => [
  { k: "n", label: "trades", type: "number" },
  { k: "wr", label: "WR %", type: "number", fmt: (v) => (v === null ? "·" : num(v, 1)) },
  { k: "avg_pct", label: "avg %", type: "number", fmt: (v) => signed(v) },
  { k: "med_pct", label: "mediana %", type: "number", fmt: (v) => signed(v) },
  { k: "p10", label: "p10 %", type: "number", fmt: (v) => (v === null || v === undefined ? "·" : signed(v)) },
  { k: "sum_pct", label: "suma %", type: "number", fmt: (v) => signed(v, 1) },
  { k: "avg_hours", label: "horas med.", type: "number", fmt: (v) => num(v, 1) },
  { k: "avg_mae", label: "MAE med.", type: "number", fmt: (v) => num(v, 2) },
  { k: "avg_mfe", label: "MFE med.", type: "number", fmt: (v) => num(v, 2) },
  { k: "avg_entries", label: "entradas", type: "number", fmt: (v) => num(v, 2) },
  { k: "grinds", label: "grinds", type: "number" },
  { k: "derisks", label: "derisks", type: "number" },
  { k: "installs", label: "instal.", type: "number" },
];

const views = {};

views.overview = async (target) => {
  const [data, meta] = await Promise.all([api("/api/overview"), api("/api/meta")]);
  const t = data.totals;
  const series = data.series;
  target.innerHTML = `
    ${kpis([
      { k: "trades cerrados", v: t.n ?? 0, s: `${data.open.n} abiertos` },
      { k: "win rate", v: num(t.wr, 1) + "%" },
      { k: "profit medio", v: pct(t.avg_pct), cls: t.avg_pct >= 0 ? "pos" : "neg", s: `mediana ${pct(t.med_pct)}` },
      { k: "suma %", v: pct(t.sum_pct, 1), cls: t.sum_pct >= 0 ? "pos" : "neg" },
      { k: "profit absoluto", v: num(t.profit_abs, 0) + " USDT" },
      { k: "horas medias", v: num(t.avg_hours, 1), s: `mediana ${num(t.med_hours, 1)}` },
      { k: "MAE / MFE", v: num(t.avg_mae, 2) + " / " + num(t.avg_mfe, 2) },
      { k: "instalaciones", v: t.installs ?? 0, s: `${meta.installs} conocidas` },
      { k: "abiertos", v: data.open.n, s: `no realizado ${pct(data.open.avg_unrealized)} · ${num(data.open.avg_age_hours, 0)}h` },
    ])}
    <h2>Actividad diaria</h2>
    <div class="legend">último día <b>${esc(series.at(-1)?.day || "·")}</b> · ${series.length} días con cierres · tendencia = suma % por día</div>
    ${sparkline(series.map((s) => s.sum_pct), { width: 900, height: 70 })}
    <h2>Versiones reportando</h2>
    <div class="legend">${meta.versions.map((v) => `${esc(v.strategy_version)} / ${esc(v.system_version)}: <b>${v.n}</b>`).join(" · ") || "sin datos"}</div>
    <div class="legend">último reporte recibido: <b>${esc((meta.last_report_utc || "·").replace("T", " ").slice(0, 19))}</b> · ingestas recientes: ${meta.latest_ingest.map((i) => `${esc(i.source)} (${i.imported} nuevos)`).join(", ") || "·"}</div>
  `;
};

views.tags = async (target, opts = {}) => {
  const sort = opts.sort || "n";
  const data = await api("/api/tags", { sort, limit: 200 });
  const best = Math.max(...data.rows.map((r) => Math.abs(r.sum_pct || 0)), 1);
  const cols = [
    { k: "tag", label: "tag", type: "text" },
    ...AGG_COLS(),
    { k: "bar", label: "", fmt: (_, r) => bar(r.sum_pct, best, r.sum_pct >= 0 ? "pos" : "neg") },
  ];
  target.innerHTML = `
    <h2>Ranking por tag</h2>
    <div class="legend">clic en una fila para ver el detalle · ordena por columna · ${data.k_anonymity_floor ? `filas con menos de ${data.k_anonymity_floor} instalaciones ocultas` : "todas las filas visibles"}</div>
    <div id="tags-table">${table(cols, data.rows, { onRow: (row) => showTag(row.tag) })}</div>
    <div id="tag-detail"></div>
  `;
  wireTable($("tags-table"), cols, data.rows, { onRow: (row) => showTag(row.tag) });
};

async function showTag(tag) {
  const box = $("tag-detail");
  if (!box) return;
  box.innerHTML = `<h2>Tag ${esc(tag)}</h2><p class="muted">cargando…</p>`;
  const d = await api(`/api/tag/${encodeURIComponent(tag)}`);
  const pairCols = [
    { k: "pair", label: "par", type: "text" },
    ...AGG_COLS(),
  ];
  const exitCols = [
    { k: "exit", label: "motivo de salida", type: "text" },
    { k: "n", label: "trades", type: "number" },
    { k: "wr", label: "WR %", type: "number", fmt: (v) => num(v, 1) },
    { k: "avg_pct", label: "avg %", type: "number", fmt: (v) => signed(v) },
  ];
  const orderCols = [
    { k: "kind", label: "tipo de orden", type: "text" },
    { k: "n", label: "órdenes", type: "number" },
    { k: "filled", label: "cantidad", type: "number", fmt: (v) => num(v, 3) },
  ];
  box.innerHTML = `
    <div class="grid2">
      <div><h3>Por par</h3><div class="scroll">${table(pairCols, d.by_pair)}</div></div>
      <div>
        <h3>Por motivo de salida</h3><div class="scroll">${table(exitCols, d.by_exit)}</div>
        <h3>Órdenes por tipo</h3><div class="scroll">${table(orderCols, d.orders)}</div>
      </div>
    </div>
    <h3>Últimas semanas</h3>
    <div class="legend">tendencia = avg % semanal</div>
    ${sparkline([...d.weekly].reverse().map((w) => w.avg_pct), { width: 900, height: 60 })}
  `;
}

views.grind = async (target) => {
  const d = await api("/api/grind");
  const bucketCols = [
    { k: "bucket", label: "gestión", type: "text" },
    { k: "n", label: "trades", type: "number" },
    { k: "wr", label: "WR %", type: "number", fmt: (v) => num(v, 1) },
    { k: "avg_pct", label: "avg %", type: "number", fmt: (v) => signed(v) },
    { k: "p10", label: "p10 %", type: "number", fmt: (v) => signed(v) },
    { k: "avg_hours", label: "horas med.", type: "number", fmt: (v) => num(v, 1) },
    { k: "avg_mae", label: "MAE med.", type: "number", fmt: (v) => num(v, 2) },
    { k: "avg_mfe", label: "MFE med.", type: "number", fmt: (v) => num(v, 2) },
    { k: "avg_entries", label: "entradas", type: "number", fmt: (v) => num(v, 2) },
    { k: "avg_stake_growth", label: "crecimiento stake", type: "number", fmt: (v) => (v ? "×" + num(v, 2) : "·") },
  ];
  const kindCols = [
    { k: "kind", label: "tipo", type: "text" },
    { k: "n", label: "órdenes", type: "number" },
    { k: "trades", label: "trades", type: "number" },
    { k: "filled", label: "cantidad", type: "number", fmt: (v) => num(v, 3) },
  ];
  const tagCols = [
    { k: "tag", label: "tag", type: "text" },
    { k: "n", label: "trades", type: "number" },
    { k: "grinds", label: "grinds", type: "number" },
    { k: "derisks", label: "derisks", type: "number" },
    { k: "avg_entries", label: "entradas", type: "number", fmt: (v) => num(v, 2) },
    { k: "avg_stake_growth", label: "crecimiento stake", type: "number", fmt: (v) => (v ? "×" + num(v, 2) : "·") },
    { k: "avg_pct", label: "avg %", type: "number", fmt: (v) => signed(v) },
    { k: "wr", label: "WR %", type: "number", fmt: (v) => num(v, 1) },
  ];
  target.innerHTML = `
    <h2>¿Sirve promediar y de-risquear?</h2>
    <div class="legend">trades agrupados por si tuvieron órdenes de grind (promediar) y/o derisk (recortar)</div>
    <div class="scroll">${table(bucketCols, d.by_group)}</div>
    <h2>Órdenes por tipo</h2>
    <div class="scroll">${table(kindCols, d.kinds)}</div>
    <h2>Tags que más promedian</h2>
    <div class="scroll">${table(tagCols, d.by_tag)}</div>
    <h3>Tendencia de trades con grind</h3>
    ${sparkline([...d.weekly_grind].reverse().map((w) => w.avg_pct), { width: 900, height: 60 })}
  `;
};

views.versions = async (target) => {
  const d = await api("/api/versions");
  const cols = [
    { k: "strategy_version", label: "estrategia", type: "text" },
    { k: "system_version", label: "sistema", type: "text" },
    ...AGG_COLS(),
  ];
  const instCols = [
    { k: "masked", label: "instalación", type: "text" },
    { k: "exchange", label: "exchange", type: "text" },
    { k: "trading_mode", label: "modo", type: "text" },
    { k: "strategy_version", label: "versión", type: "text" },
    { k: "reports", label: "reportes", type: "number" },
    { k: "trades", label: "trades", type: "number" },
    { k: "wr", label: "WR %", type: "number", fmt: (v) => (v === null ? "·" : num(v, 1)) },
    { k: "avg_pct", label: "avg %", type: "number", fmt: (v) => (v === null ? "·" : signed(v)) },
    { k: "last_seen_utc", label: "último reporte", type: "text", fmt: (v) => esc(String(v).replace("T", " ").slice(0, 19)) },
  ];
  target.innerHTML = `
    <h2>Comparación por versión</h2>
    <div class="scroll">${table(cols, d.rows)}</div>
    <h2>Instalaciones</h2>
    <div class="legend">ids anonimizados (uuid aleatorio por instalación, no derivado de claves ni de IP)</div>
    <div class="scroll">${table(instCols, d.installs)}</div>
  `;
};

views.pairs = async (target) => {
  const d = await api("/api/pairs");
  const cols = [{ k: "pair", label: "par", type: "text" }, ...AGG_COLS()];
  const sideCols = [{ k: "side", label: "lado", type: "text" }, ...AGG_COLS()];
  target.innerHTML = `
    <h2>Por lado</h2>
    <div class="scroll">${table(sideCols, d.sides)}</div>
    <h2>Por par</h2>
    <div class="scroll">${table(cols, d.rows)}</div>
  `;
};

views.exits = async (target) => {
  const d = await api("/api/exits");
  const max = Math.max(...d.rows.map((r) => r.n), 1);
  const cols = [
    { k: "exit", label: "motivo", type: "text" },
    { k: "n", label: "trades", type: "number" },
    { k: "bar", label: "", fmt: (_, r) => bar(r.n, max) },
    { k: "wr", label: "WR %", type: "number", fmt: (v) => num(v, 1) },
    { k: "avg_pct", label: "avg %", type: "number", fmt: (v) => signed(v) },
    { k: "sum_pct", label: "suma %", type: "number", fmt: (v) => signed(v, 1) },
    { k: "avg_hours", label: "horas med.", type: "number", fmt: (v) => num(v, 1) },
    { k: "avg_mae", label: "MAE med.", type: "number", fmt: (v) => num(v, 2) },
  ];
  target.innerHTML = `<h2>Motivos de salida</h2><div class="scroll">${table(cols, d.rows)}</div>`;
};

views.trades = async (target) => {
  const extra = { page: state.page, per_page: 50 };
  let d;
  try {
    d = await api("/api/trades", extra);
  } catch (err) {
    target.innerHTML = `<h2>Trades</h2><div class="notice">Para ver el detalle trade a trade hace falta el token del dashboard (arriba a la derecha). ${esc(err.message)}</div>`;
    return;
  }
  const cols = [
    { k: "closed_utc", label: "cierre (UTC)", type: "text", fmt: (v) => esc(String(v).replace("T", " ").slice(0, 16)) },
    { k: "pair", label: "par", type: "text" },
    { k: "side", label: "lado", type: "text" },
    { k: "tag", label: "tag", type: "text" },
    { k: "hours", label: "horas", type: "number", fmt: (v) => num(v, 1) },
    { k: "profit_pct", label: "profit %", type: "number", fmt: (v) => signed(v) },
    { k: "profit_abs", label: "abs", type: "number", fmt: (v) => num(v, 2) },
    { k: "mae_pct", label: "MAE", type: "number", fmt: (v) => num(v, 2) },
    { k: "mfe_pct", label: "MFE", type: "number", fmt: (v) => num(v, 2) },
    { k: "entries", label: "entradas", type: "number" },
    { k: "grinds", label: "grinds", type: "number" },
    { k: "derisks", label: "derisks", type: "number" },
    { k: "exit", label: "salida", type: "text" },
    { k: "install", label: "instal.", type: "text" },
    { k: "system_version", label: "sistema", type: "text" },
  ];
  target.innerHTML = `
    <h2>Trades cerrados <span class="pill">${d.total} con estos filtros</span></h2>
    <div class="legend">clic en una fila para ver todas sus órdenes (grind/derisk/rebuy incluidas)</div>
    <div id="trades-table">${table(cols, d.rows, { onRow: (row) => showTrade(row) })}</div>
    <div class="pager">
      <button id="prev">◀ anteriores</button>
      <span class="muted">página ${d.page} · ${d.per_page} por página</span>
      <button id="next">siguientes ▶</button>
    </div>
    <div id="trade-detail"></div>
  `;
  wireTable($("trades-table"), cols, d.rows, { onRow: (row) => showTrade(row) });
  $("prev").onclick = () => { state.page = Math.max(1, state.page - 1); views.trades(target); };
  $("next").onclick = () => { state.page += 1; views.trades(target); };
};

async function showTrade(row) {
  const box = $("trade-detail");
  box.innerHTML = `<h2>${esc(row.pair)} · trade ${esc(row.trade_id)}</h2><p class="muted">cargando…</p>`;
  const d = await api(`/api/trade/${encodeURIComponent(row.install_id)}/${row.trade_id}`);
  const cols = [
    { k: "placed_utc", label: "puesta (UTC)", type: "text", fmt: (v) => esc(String(v || "·").replace("T", " ").slice(0, 16)) },
    { k: "filled_utc", label: "ejecutada (UTC)", type: "text", fmt: (v) => esc(String(v || "·").replace("T", " ").slice(0, 16)) },
    { k: "kind", label: "tipo", type: "text" },
    { k: "tag", label: "tag", type: "text" },
    { k: "status", label: "estado", type: "text" },
    { k: "amount", label: "cantidad", type: "number", fmt: (v) => num(v, 6) },
    { k: "filled", label: "ejecutado", type: "number", fmt: (v) => num(v, 6) },
    { k: "price", label: "precio", type: "number", fmt: (v) => num(v, 6) },
    { k: "cost", label: "coste", type: "number", fmt: (v) => num(v, 2) },
  ];
  box.innerHTML = `
    <div class="legend">
      abierto <b>${esc(String(d.opened_utc).replace("T", " ").slice(0, 16))}</b> ·
      cerrado <b>${esc(String(d.closed_utc || "·").replace("T", " ").slice(0, 16))}</b> ·
      <b>${num(d.hours, 1)}h</b> · profit <b>${pct(d.profit_pct)}</b> ·
      MAE <b>${num(d.mae_pct, 2)}</b> · MFE <b>${num(d.mfe_pct, 2)}</b> ·
      salida <b>${esc(d.exit || "·")}</b> · <span class="muted">${esc(d.exit_detail || "")}</span>
    </div>
    <div class="scroll">${table(cols, d.orders)}</div>
  `;
}

views.worst = async (target) => {
  let d;
  try {
    d = await api("/api/worst", { n: 40 });
  } catch (err) {
    target.innerHTML = `<h2>Peores trades</h2><div class="notice">Requiere el token del dashboard. ${esc(err.message)}</div>`;
    return;
  }
  const cols = [
    { k: "profit_pct", label: "profit %", type: "number", fmt: (v) => signed(v) },
    { k: "closed_utc", label: "cierre", type: "text", fmt: (v) => esc(String(v).replace("T", " ").slice(0, 16)) },
    { k: "pair", label: "par", type: "text" },
    { k: "side", label: "lado", type: "text" },
    { k: "tag", label: "tag", type: "text" },
    { k: "hours", label: "horas", type: "number", fmt: (v) => num(v, 1) },
    { k: "mae_pct", label: "MAE", type: "number", fmt: (v) => num(v, 2) },
    { k: "mfe_pct", label: "MFE", type: "number", fmt: (v) => num(v, 2) },
    { k: "entries", label: "entradas", type: "number" },
    { k: "grinds", label: "grinds", type: "number" },
    { k: "derisks", label: "derisks", type: "number" },
    { k: "stake", label: "stake", type: "number", fmt: (v) => num(v, 0) },
    { k: "max_stake", label: "máx", type: "number", fmt: (v) => num(v, 0) },
    { k: "exit", label: "salida", type: "text", cls: "muted" },
  ];
  target.innerHTML = `<h2>Peores trades <span class="pill">top 40</span></h2>
    <div class="legend">lo que más duele, con duración, MAE y motivo de salida: aquí es donde se optimiza</div>
    <div id="worst-table">${table(cols, d.rows, { onRow: (row) => showTrade(row) })}</div>
    <div id="trade-detail"></div>`;
  wireTable($("worst-table"), cols, d.rows, { onRow: (row) => showTrade(row) });
};

async function loadMeta() {
  const meta = await api("/api/meta");
  $("meta-line").textContent = `${meta.installs} instalaciones · ${meta.reports} reportes · ${meta.trades} trades (${meta.open} abiertos) · último ${(meta.last_report_utc || "·").replace("T", " ").slice(0, 19)} UTC`;
  const fill = (id, values, current) => {
    const box = $(id);
    for (const v of values) {
      if (!v) continue;
      const option = document.createElement("option");
      option.value = v;
      option.textContent = v;
      box.appendChild(option);
      if (v === current) box.value = v;
    }
  };
  fill("f-version", [...new Set(meta.versions.map((v) => v.strategy_version))]);
  fill("f-system", [...new Set(meta.versions.map((v) => v.system_version))]);
  const exchanges = [...new Set(meta.latest_ingest.map(() => null))];
  void exchanges;
}

async function render() {
  const target = view();
  $("tabs").querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.tab === state.tab));
  target.innerHTML = '<p class="muted">Cargando…</p>';
  try {
    await views[state.tab](target);
  } catch (err) {
    target.innerHTML = `<div class="notice err">Error: ${esc(err.message)}</div>`;
  }
}

function buildTabs() {
  $("tabs").innerHTML = TABS.map(([id, label]) => `<button data-tab="${id}">${esc(label)}</button>`).join("");
  $("tabs").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      state.tab = b.dataset.tab;
      state.page = 1;
      location.hash = state.tab;
      render();
    })
  );
}

function init() {
  buildTabs();
  for (const id of ["f-days", "f-version", "f-system", "f-side", "f-exchange"]) $(id).addEventListener("change", render);
  $("f-token").value = localStorage.getItem("nfix-token") || "";
  $("f-token").addEventListener("change", () => {
    localStorage.setItem("nfix-token", $("f-token").value.trim());
    render();
  });
  $("refresh").addEventListener("click", render);
  window.addEventListener("hashchange", () => {
    state.tab = location.hash.replace("#", "") || "overview";
    render();
  });
  loadMeta().then(render).catch((err) => {
    view().innerHTML = `<div class="notice err">No se pudo cargar: ${esc(err.message)}</div>`;
  });
}

init();
