/* Play-money LMSR prediction market — page controller.
 * Polls state + history, renders an elegant top-5 probability-over-time chart
 * (dynamically tracking whoever is currently leading), live odds rows, and
 * trade actions. LMSR cost previews are computed client-side. */

(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const pts = (n) => (n == null ? "—" : Number(n).toFixed(1) + " pts");
  const pct = (p) => (p * 100).toFixed(1) + "%";
  const COLORS = ["#4f8cff", "#16c784", "#f5a623", "#b06bff", "#36d1dc"];
  const TOP_N = 5;

  let state = null;       // /api/predict/state
  let history = null;     // /api/predict/history
  let email = localStorage.getItem("predict_email") || "";
  let adminPass = "";
  let chart = null;
  let myHoldings = {};

  /* ---- LMSR cost preview (mirrors app/lmsr.py) ---- */
  function lmsrCost(q, b) {
    const s = q.map((x) => x / b);
    const m = Math.max(...s);
    return b * (m + Math.log(s.reduce((a, c) => a + Math.exp(c - m), 0)));
  }
  function costToTrade(q, i, delta, b) {
    const q2 = q.slice();
    q2[i] += delta;
    return lmsrCost(q2, b) - lmsrCost(q, b);
  }

  /* ---- Chart ---- */
  function topFive() {
    // positions (index in outcome order) of the current highest-probability nominees
    return [...state.outcomes.keys()]
      .sort((a, b) => state.outcomes[b].prob - state.outcomes[a].prob)
      .slice(0, TOP_N);
  }

  function initChart() {
    const ctx = $("prob-chart").getContext("2d");
    chart = new Chart(ctx, {
      type: "line",
      data: { labels: [], datasets: [] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}%` } },
        },
        scales: {
          x: { ticks: { color: "#8a98ad", maxTicksLimit: 7, maxRotation: 0 }, grid: { color: "rgba(31,42,61,.4)" } },
          y: { ticks: { color: "#8a98ad", callback: (v) => v + "%" }, grid: { color: "rgba(31,42,61,.4)" }, beginAtZero: true },
        },
      },
    });
  }

  function fmtTime(iso) {
    if (!iso) return "start";
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function updateChart() {
    if (!chart || !state || !history) return;
    const top = topFive();
    chart.data.labels = history.points.map((p) => fmtTime(p.t));
    chart.data.datasets = top.map((pos, k) => ({
      label: state.outcomes[pos].name,
      data: history.points.map((p) => +(p.probs[pos] * 100).toFixed(2)),
      borderColor: COLORS[k],
      backgroundColor: COLORS[k],
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      tension: 0.25,
    }));
    chart.update();

    // Custom legend with live percentages.
    $("legend").innerHTML = top
      .map(
        (pos, k) =>
          `<span class="legend-item"><span class="legend-dot" style="background:${COLORS[k]}"></span>` +
          `<span class="legend-name">${state.outcomes[pos].name}</span>` +
          `<span class="legend-pct">${pct(state.outcomes[pos].prob)}</span></span>`
      )
      .join("");
  }

  /* ---- Nominee rows ---- */
  const qtyVal = (el) => Math.max(1, Math.floor(Number(el.value) || 0));

  function buildNoms() {
    const noms = $("noms");
    noms.innerHTML = state.outcomes
      .map(
        (o, pos) => `
      <div class="nom" data-id="${o.id}" data-pos="${pos}">
        <div class="left">
          <span class="dot"></span>
          <div style="min-width:0;">
            <div class="name">${o.name}</div>
            <div class="you"></div>
          </div>
        </div>
        <div class="mid"><div class="bar"><div class="bar-fill"></div></div></div>
        <div class="prob"></div>
        <div class="actions">
          <input type="number" class="qty" value="10" min="1" step="1" />
          <div class="btns"><button class="buy">Buy</button><button class="sell">Sell</button></div>
        </div>
        <div class="quote"></div>
      </div>`
      )
      .join("");

    noms.querySelectorAll(".nom").forEach((card) => {
      const id = parseInt(card.dataset.id, 10);
      const pos = parseInt(card.dataset.pos, 10);
      const qtyEl = card.querySelector(".qty");
      qtyEl.addEventListener("input", () => updateQuote(card, pos, qtyEl));
      card.querySelector(".buy").addEventListener("click", () => doTrade(id, +qtyVal(qtyEl)));
      card.querySelector(".sell").addEventListener("click", () => doTrade(id, -qtyVal(qtyEl)));
    });
  }

  function updateQuote(card, pos, qtyEl) {
    if (!state) return;
    const q = state.outcomes.map((o) => o.q);
    const n = qtyVal(qtyEl);
    const buy = costToTrade(q, pos, n, state.b);
    const sell = -costToTrade(q, pos, -n, state.b);
    card.querySelector(".quote").textContent = `Buy ≈ ${buy.toFixed(1)} pts · Sell ≈ +${sell.toFixed(1)} pts`;
  }

  function updateNoms() {
    const noms = $("noms");
    const order = topFive(); // for color assignment
    const colorByPos = {};
    order.forEach((pos, k) => (colorByPos[pos] = COLORS[k]));

    const sorted = [...state.outcomes.keys()].sort((a, b) => state.outcomes[b].prob - state.outcomes[a].prob);
    const cards = {};
    noms.querySelectorAll(".nom").forEach((c) => (cards[c.dataset.id] = c));

    sorted.forEach((pos) => {
      const o = state.outcomes[pos];
      const card = cards[o.id];
      if (!card) return;
      card.querySelector(".prob").textContent = pct(o.prob);
      card.querySelector(".bar-fill").style.width = Math.max(1.5, o.prob * 100) + "%";
      const dot = card.querySelector(".dot");
      const color = colorByPos[pos];
      dot.style.background = color || "transparent";
      card.querySelector(".bar-fill").style.background = color || "var(--accent)";
      const sh = myHoldings[o.id] || 0;
      card.querySelector(".you").textContent = sh ? `you hold ${sh.toFixed(0)} shares` : "";
      updateQuote(card, pos, card.querySelector(".qty"));
      noms.appendChild(card); // reorder by probability
    });

    const resolved = state.resolved;
    noms.querySelectorAll("button, .qty").forEach((el) => (el.disabled = resolved));
  }

  function renderLeaderboard() {
    $("leaderboard").innerHTML = state.leaderboard.length
      ? state.leaderboard
          .map((r, i) => `<div class="lb-row"><span>#${i + 1}</span><span>${r.name}</span><span class="lb-net">${r.net_worth.toFixed(1)}</span></div>`)
          .join("")
      : `<p class="empty">No traders yet.</p>`;
  }

  function renderResolved() {
    const b = $("resolved-banner");
    b.textContent = state.resolved && state.winner ? `🏆 Resolved — winner: ${state.winner}. Trading is closed.` : "";
  }

  function renderPortfolio(p) {
    $("w-balance").textContent = pts(p.balance);
    $("w-net").textContent = pts(p.net_worth);
    myHoldings = {};
    (p.holdings || []).forEach((h) => (myHoldings[h.id] = h.shares));
    const el = $("holdings");
    el.innerHTML = p.holdings.length
      ? p.holdings
          .map((h) => `<div class="holding-row"><span class="h-name">${h.name}</span><span class="h-sh">${h.shares.toFixed(0)} @ ${pct(h.price)}</span><span class="h-val">${h.value.toFixed(1)}</span></div>`)
          .join("")
      : `<p class="empty">No positions yet — buy a nominee.</p>`;
    if (state) updateNoms();
  }

  /* ---- Data ---- */
  async function loadState() {
    try {
      const [sr, hr] = await Promise.all([fetch("/api/predict/state"), fetch("/api/predict/history")]);
      const fresh = await sr.json();
      history = await hr.json();
      const rebuild = state === null || state.outcomes.length !== fresh.outcomes.length;
      state = fresh;
      $("conn-text").textContent = "live";
      if (rebuild) { buildNoms(); fillAdminWinners(); }
      updateNoms();
      updateChart();
      renderLeaderboard();
      renderResolved();
    } catch (_) {
      $("conn-text").textContent = "reconnecting…";
    }
  }

  async function loadPortfolio() {
    if (!email) return;
    try {
      const r = await fetch("/api/predict/portfolio?email=" + encodeURIComponent(email));
      if (r.ok) renderPortfolio(await r.json());
    } catch (_) {}
  }

  async function doTrade(outcomeId, shares) {
    const msg = $("msg");
    msg.className = "msg";
    if (!email) { msg.classList.add("error"); msg.textContent = "Enter your email first."; return; }
    try {
      const r = await fetch("/api/predict/trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, outcome_id: outcomeId, shares }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Trade failed");
      renderPortfolio(data);
      await loadState();
      msg.classList.add("success");
      msg.textContent = shares > 0 ? `Bought ${shares} shares.` : `Sold ${-shares} shares.`;
    } catch (err) {
      msg.classList.add("error");
      msg.textContent = err.message;
    }
  }

  /* ---- Admin ---- */
  function fillAdminWinners() {
    if (!state) return;
    $("admin-winner").innerHTML = state.outcomes.map((o) => `<option value="${o.id}">${o.name}</option>`).join("");
  }
  const adminHeaders = () => ({ "Content-Type": "application/json", Authorization: "Basic " + btoa("admin:" + adminPass) });
  function initAdmin() {
    $("admin-toggle").addEventListener("click", () => $("admin-box").classList.toggle("show"));
    $("admin-resolve").addEventListener("click", async () => {
      adminPass = $("admin-pass").value;
      const id = parseInt($("admin-winner").value, 10);
      if (!confirm("Declare this nominee the winner and settle the market? This is final.")) return;
      const r = await fetch("/api/predict/admin/resolve", { method: "POST", headers: adminHeaders(), body: JSON.stringify({ winner_outcome_id: id }) });
      alert(r.ok ? "Market resolved." : "Failed (check password): " + (await r.text()));
      loadState(); loadPortfolio();
    });
    $("admin-reset").addEventListener("click", async () => {
      adminPass = $("admin-pass").value;
      if (!confirm("Wipe ALL prediction-market data and re-seed nominees?")) return;
      const r = await fetch("/api/predict/admin/reset", { method: "POST", headers: adminHeaders() });
      alert(r.ok ? "Reset done." : "Failed (check password): " + (await r.text()));
      state = null; loadState(); loadPortfolio();
    });
  }

  /* ---- Boot ---- */
  function initEmail() {
    if (email) $("email").value = email;
    $("enter-btn").addEventListener("click", () => {
      const v = $("email").value.trim().toLowerCase();
      if (!v || !v.includes("@")) { $("msg").className = "msg error"; $("msg").textContent = "Enter a valid email."; return; }
      email = v;
      localStorage.setItem("predict_email", email);
      $("msg").className = "msg success"; $("msg").textContent = "You're in — start trading.";
      loadPortfolio();
    });
  }

  window.addEventListener("DOMContentLoaded", () => {
    initChart();
    initEmail();
    initAdmin();
    loadState().then(loadPortfolio);
    setInterval(() => { loadState(); loadPortfolio(); }, 2500);
  });
})();
