/* Play-money LMSR prediction market — standalone page controller.
 * Polls market state, renders live odds, computes trade cost previews
 * client-side (mirroring app/lmsr.py), and submits trades. */

(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const pts = (n) => (n == null ? "—" : Number(n).toFixed(1) + " pts");
  const pct = (p) => (p * 100).toFixed(1) + "%";

  let state = null;        // latest /api/predict/state
  let email = localStorage.getItem("predict_email") || "";
  let adminPass = "";

  /* ---- LMSR cost preview (mirror of app/lmsr.py) ---- */
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

  /* ---- Rendering ---- */
  function holdingsByOutcome(portfolio) {
    const map = {};
    (portfolio?.holdings || []).forEach((h) => (map[h.id] = h.shares));
    return map;
  }
  let myHoldings = {};

  function buildNoms() {
    // q vector in stable outcome order (state.outcomes is ordered by idx)
    const noms = $("noms");
    noms.innerHTML = state.outcomes
      .map(
        (o, pos) => `
      <div class="nom" data-id="${o.id}" data-pos="${pos}">
        <div class="nom-head">
          <span class="rank"></span>
          <span class="nom-name">${o.name}</span>
          <span class="nom-prob"></span>
        </div>
        <div class="bar"><div class="bar-fill"></div></div>
        <div class="nom-foot">
          <span class="you"></span>
          <div class="trade">
            <input type="number" class="qty" value="10" min="1" step="1" />
            <button class="buy">Buy</button>
            <button class="sell">Sell</button>
          </div>
          <span class="quote"></span>
        </div>
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

  const qtyVal = (el) => Math.max(1, Math.floor(Number(el.value) || 0));

  function updateQuote(card, pos, qtyEl) {
    if (!state) return;
    const q = state.outcomes.map((o) => o.q);
    const n = qtyVal(qtyEl);
    const buy = costToTrade(q, pos, n, state.b);
    const sell = -costToTrade(q, pos, -n, state.b);
    card.querySelector(".quote").textContent =
      `Buy ${n} ≈ ${buy.toFixed(1)} pts · Sell ${n} ≈ +${sell.toFixed(1)} pts`;
  }

  function updateNoms() {
    // sort cards by probability (desc) without rebuilding inputs
    const noms = $("noms");
    const order = [...state.outcomes.keys()].sort((a, b) => state.outcomes[b].prob - state.outcomes[a].prob);
    const cards = {};
    noms.querySelectorAll(".nom").forEach((c) => (cards[c.dataset.id] = c));

    order.forEach((idx, rank) => {
      const o = state.outcomes[idx];
      const card = cards[o.id];
      if (!card) return;
      card.querySelector(".rank").textContent = "#" + (rank + 1);
      card.querySelector(".nom-prob").textContent = pct(o.prob);
      card.querySelector(".bar-fill").style.width = Math.max(1.5, o.prob * 100) + "%";
      const sh = myHoldings[o.id] || 0;
      card.querySelector(".you").textContent = sh ? `You: ${sh.toFixed(0)} sh` : "You: —";
      updateQuote(card, parseInt(card.dataset.pos, 10), card.querySelector(".qty"));
      noms.appendChild(card); // reorder in DOM
    });

    // disable trading if resolved
    const resolved = state.resolved;
    noms.querySelectorAll("button, .qty").forEach((el) => (el.disabled = resolved));
  }

  function renderLeaderboard() {
    $("leaderboard").innerHTML = state.leaderboard.length
      ? state.leaderboard
          .map(
            (r, i) =>
              `<div class="lb-row"><span>#${i + 1}</span><span>${r.name}</span><span class="lb-net">${r.net_worth.toFixed(1)}</span></div>`
          )
          .join("")
      : `<p class="empty">No traders yet.</p>`;
  }

  function renderResolved() {
    const b = $("resolved-banner");
    if (state.resolved && state.winner) {
      b.className = "resolved-banner";
      b.textContent = `🏆 Market resolved — winner: ${state.winner}. Trading is closed.`;
    } else {
      b.textContent = "";
    }
  }

  function renderPortfolio(p) {
    $("w-balance").textContent = pts(p.balance);
    $("w-net").textContent = pts(p.net_worth);
    myHoldings = holdingsByOutcome(p);
    const el = $("holdings");
    if (!p.holdings.length) {
      el.innerHTML = `<p class="empty">No positions yet — buy a nominee below.</p>`;
    } else {
      el.innerHTML = p.holdings
        .map(
          (h) =>
            `<div class="holding-row"><span class="h-name">${h.name}</span><span class="h-sh">${h.shares.toFixed(0)} sh @ ${pct(h.price)}</span><span class="h-val">${h.value.toFixed(1)}</span></div>`
        )
        .join("");
    }
    if (state) updateNoms();
  }

  /* ---- Data ---- */
  async function loadState() {
    try {
      const r = await fetch("/api/predict/state");
      const fresh = await r.json();
      const firstLoad = state === null;
      const changedCount = !state || state.outcomes.length !== fresh.outcomes.length;
      state = fresh;
      $("conn-text").textContent = "live";
      if (firstLoad || changedCount) {
        buildNoms();
        fillAdminWinners();
      }
      updateNoms();
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
    $("admin-winner").innerHTML = state.outcomes
      .map((o) => `<option value="${o.id}">${o.name}</option>`)
      .join("");
  }
  function adminHeaders() {
    return { "Content-Type": "application/json", Authorization: "Basic " + btoa("admin:" + adminPass) };
  }
  function initAdmin() {
    $("admin-toggle").addEventListener("click", () => {
      $("admin-box").classList.toggle("show");
    });
    $("admin-resolve").addEventListener("click", async () => {
      adminPass = $("admin-pass").value;
      const id = parseInt($("admin-winner").value, 10);
      if (!confirm("Declare this nominee the winner and settle the market? This is final.")) return;
      const r = await fetch("/api/predict/admin/resolve", {
        method: "POST", headers: adminHeaders(), body: JSON.stringify({ winner_outcome_id: id }),
      });
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
    initEmail();
    initAdmin();
    loadState().then(loadPortfolio);
    setInterval(() => { loadState(); loadPortfolio(); }, 2500);
  });
})();
