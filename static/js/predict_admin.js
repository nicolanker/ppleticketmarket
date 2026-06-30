/* Prediction-market admin console. The page itself sits behind HTTP Basic
 * auth, so the browser resends credentials on these same-origin API calls
 * automatically — no password handling needed in JS. */

(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const pct = (p) => (p * 100).toFixed(1) + "%";

  let resolved = false;

  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    if (r.status === 401) { alert("Unauthorized. Reload and re-enter admin credentials."); throw new Error("401"); }
    return r;
  }

  function renderStats(d) {
    const cards = [
      ["Status", d.resolved ? "Resolved" : "Open", d.resolved ? "" : ""],
      ["Winner", d.winner || "—", d.winner ? "win" : ""],
      ["Traders", d.num_traders, ""],
      ["Trades", d.total_trades, ""],
      ["Volume (shares)", d.total_volume, ""],
      ["Liquidity b", d.b, ""],
      ["Start balance", d.start_balance, ""],
    ];
    $("stats").innerHTML = cards
      .map(([k, v, cls]) => `<div class="stat"><div class="k">${k}</div><div class="v ${cls}">${v}</div></div>`)
      .join("");
  }

  function renderNominees(noms, winnerName) {
    $("nominees").innerHTML = noms
      .map(
        (o, i) =>
          `<tr><td>${i + 1}</td><td class="name">${o.name === winnerName ? '<span class="winner-tag">★ </span>' : ""}${o.name}</td>` +
          `<td class="num">${pct(o.prob)}</td><td class="num">${o.shares}</td></tr>`
      )
      .join("");
  }

  function renderTraders(traders) {
    $("traders").innerHTML = traders.length
      ? traders
          .map(
            (t, i) =>
              `<tr><td>${i + 1}</td><td class="name">${t.email}</td><td class="num">${t.balance.toFixed(1)}</td><td class="num">${t.net_worth.toFixed(1)}</td></tr>`
          )
          .join("")
      : `<tr><td colspan="4" style="color:var(--muted);text-align:center;padding:14px;">No traders yet.</td></tr>`;
  }

  function fillWinnerSelect(noms) {
    const sel = $("winner-select");
    const prev = sel.value;
    sel.innerHTML = noms.map((o) => `<option value="${o.id}">${o.name} — ${pct(o.prob)}</option>`).join("");
    if (prev) sel.value = prev;
  }

  async function refresh() {
    try {
      const r = await api("/api/predict/admin/overview");
      const d = await r.json();
      resolved = d.resolved;
      renderStats(d);
      renderNominees(d.nominees, d.winner);
      renderTraders(d.traders);
      fillWinnerSelect(d.nominees);
      $("resolve-btn").disabled = resolved;
      $("resolve-note").textContent = resolved
        ? `Market resolved — winner: ${d.winner}. Trading is closed.`
        : "Declaring a winner pays 100 pts per winning share and closes trading. This is final.";
    } catch (_) { /* handled in api() */ }
  }

  function init() {
    $("resolve-btn").addEventListener("click", async () => {
      if (resolved) return;
      const sel = $("winner-select");
      const name = sel.options[sel.selectedIndex]?.text || "this nominee";
      if (!confirm(`Declare "${name}" the winner and settle the market? This is final.`)) return;
      try {
        const r = await api("/api/predict/admin/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ winner_outcome_id: parseInt(sel.value, 10) }),
        });
        if (r.ok) { const d = await r.json(); alert(`Resolved — winner: ${d.winner} (${d.points_paid} pts paid out).`); refresh(); }
        else alert("Resolve failed: " + (await r.text()));
      } catch (_) {}
    });

    $("reset-btn").addEventListener("click", async () => {
      if (!confirm("Delete ALL prediction-market data and re-seed nominees? This cannot be undone.")) return;
      if (prompt("Type RESET to confirm:") !== "RESET") { alert("Cancelled."); return; }
      try {
        const r = await api("/api/predict/admin/reset", { method: "POST" });
        if (r.ok) { const d = await r.json(); alert(`Reset done — ${d.nominees} nominees re-seeded.`); refresh(); }
        else alert("Reset failed.");
      } catch (_) {}
    });

    refresh();
    setInterval(refresh, 4000);
  }

  window.addEventListener("DOMContentLoaded", init);
})();
