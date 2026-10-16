const $ = (id) => document.getElementById(id);
let rows = [], sortK = "fires", sortD = -1, chart = null;

const cls = (wr) => wr >= 0.95 ? "good" : wr >= 0.9 ? "warn" : "bad";
const fmtDur = (m) => m >= 1440 ? (m / 1440).toFixed(1) + "d" : m >= 60 ? (m / 60).toFixed(0) + "h" : m.toFixed(0) + "m";

async function load() {
  const q = new URLSearchParams({
    strategy_version: $("strategy").value.trim(),
    exchange: $("exchange").value,
    weeks: $("weeks").value,
  });
  const r = await fetch("/v1/leaderboard?" + q);
  const all = (await r.json()).rows || [];
  rows = $("realonly").checked ? all.filter((x) => !x.dry_run) : all;
  render();
  loadPulse();
}

async function loadPulse() {
  try {
    const q = new URLSearchParams({ strategy_version: $("strategy").value.trim(), hours: "24" });
    const r = await fetch("/v1/pulse?" + q);
    const data = ((await r.json()).rows || []).slice(0, 20);
    document.querySelector("#tblp tbody").innerHTML = data.map((x) =>
      `<tr><td>${x.tag}</td><td>${x.pair}</td><td>${x.side}</td><td>${x.opens}</td>` +
      `<td>${x.closes}</td><td>${x.avg_close_pct === null ? "—" : (x.avg_close_pct >= 0 ? "+" : "") + x.avg_close_pct.toFixed(2) + "%"}</td></tr>`).join("");
    $("emptyp").hidden = data.length > 0;
  } catch { $("emptyp").hidden = false; }
}

setInterval(loadPulse, 5 * 60 * 1000);

function render() {
  const fires = rows.reduce((a, r) => a + r.fires, 0);
  const wins = rows.reduce((a, r) => a + r.wins, 0);
  const wr = fires ? wins / fires : 0;
  const worst = [...rows].filter((r) => r.fires >= 5).sort((a, b) => a.win_rate - b.win_rate)[0];
  const best = [...rows].filter((a) => a.fires >= 5).sort((a, b) => b.win_rate - a.win_rate)[0];
  $("kpis").innerHTML = [
    [fires.toLocaleString(), "fires", ""],
    [(wr * 100).toFixed(1) + "%", "avg win rate", wr >= .95 ? "good" : wr >= .9 ? "warn" : "bad"],
    [rows.length, "tag × exchange groups", ""],
    [worst ? `tag ${worst.tag} · ${(worst.win_rate * 100).toFixed(1)}%` : "—", "worst tag", worst && worst.win_rate < .9 ? "bad" : "warn"],
    [best ? `tag ${best.tag} · ${(best.win_rate * 100).toFixed(1)}%` : "—", "best tag", "good"],
  ].map(([v, l, c]) => `<div class="kpi ${c}"><b>${v}</b><span>${l}</span></div>`).join("");

  const wl = [...rows].filter((r) => r.fires >= 5).sort((a, b) => a.win_rate - b.win_rate).slice(0, 6);
  $("worst").innerHTML = wl.map((r) =>
    `<li><span>tag ${r.tag} · ${r.exchange}</span><span class="wr ${cls(r.win_rate)}">${(r.win_rate * 100).toFixed(1)}% · ${r.fires}</span></li>`).join("")
    || "<li><span>No groups yet</span></li>";

  const tb = document.querySelector("#tbl tbody");
  const data = [...rows].sort((a, b) => (a[sortK] > b[sortK] ? 1 : -1) * sortD);
  tb.innerHTML = data.map((r) => `<tr><td>${r.tag}</td><td>${r.exchange}</td><td>${r.fires}</td>` +
    `<td><span class="pill ${cls(r.win_rate)}">${(r.win_rate * 100).toFixed(1)}%</span></td>` +
    `<td>${r.avg_profit_pct >= 0 ? "+" : ""}${r.avg_profit_pct.toFixed(2)}%</td><td>${fmtDur(r.avg_duration_min)}</td></tr>`).join("");
  $("empty").hidden = data.length > 0;
  draw(data);
}

function draw(data) {
  if (!window.Chart) return;
  if (chart) chart.destroy();
  const pts = data.filter((r) => r.fires >= 3).map((r) => ({
    x: r.fires, y: +(r.win_rate * 100).toFixed(1),
    tag: r.tag, wr: r.win_rate,
  }));
  chart = new Chart($("chTags"), {
    type: "bubble",
    data: { datasets: [{ data: pts, backgroundColor: (c) => c.raw.wr >= .95 ? "#34d399aa" : c.raw.wr >= .9 ? "#fbbf24aa" : "#f87171aa" }] },
    options: {
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => ` tag ${c.raw.tag}: ${c.raw.y}% WR · ${c.raw.x} fires` } },
      },
      scales: {
        x: { title: { display: true, text: "fires (log)", color: "#8b94a9" }, type: "logarithmic", grid: { color: "#232c42" }, ticks: { color: "#8b94a9" } },
        y: { min: 0, max: 100, title: { display: true, text: "win rate %", color: "#8b94a9" }, grid: { color: "#232c42" }, ticks: { color: "#8b94a9" } },
      },
    },
  });
}

document.querySelectorAll("#tbl th").forEach((th) => th.addEventListener("click", () => {
  const k = th.dataset.k;
  sortD = k === sortK ? -sortD : -1; sortK = k; render();
}));
["strategy", "exchange", "weeks", "realonly"].forEach((id) =>
  $("strategy") && $(id).addEventListener(id === "strategy" ? "change" : "change", load));
load();
