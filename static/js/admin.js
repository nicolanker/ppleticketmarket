/* Admin console. Relies on the browser's HTTP Basic auth: the /admin page is
 * itself behind Basic auth, so the browser resends credentials on these
 * same-origin API calls automatically. */

(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const euro = (n) => (n == null ? "—" : "€" + Number(n).toFixed(2));

  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    if (r.status === 401) { alert("Unauthorized. Reload and re-enter admin credentials."); throw new Error("401"); }
    return r;
  }

  function renderStats(d) {
    const s = d.stats;
    const cards = [
      ["Last price", euro(s.last_price)],
      ["Best bid", euro(s.best_bid)],
      ["Best ask", euro(s.best_ask)],
      ["Spread", s.spread == null ? "—" : euro(s.spread)],
      ["Total trades", s.total_trades],
      ["Volume (tickets)", s.total_volume],
      ["Total orders", d.total_orders],
      ["Open", d.open_orders],
      ["Filled", d.filled_orders],
      ["Cancelled", d.cancelled_orders],
    ];
    $("stats").innerHTML = cards
      .map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`)
      .join("");
  }

  function renderOrders(orders) {
    const el = $("orders");
    if (!orders.length) { el.innerHTML = `<div class="empty">No orders</div>`; return; }
    el.innerHTML = orders.map((o) => {
      const active = o.status === "open" || o.status === "partial";
      return `
        <div class="admin-row">
          <span>#${o.id}</span>
          <span class="tag ${o.side}">${o.side}</span>
          <span class="email" title="${o.email}">${o.email}</span>
          <span>${o.filled}/${o.quantity}</span>
          <span>${o.remaining}</span>
          <span>${euro(o.price)}</span>
          <span class="status ${o.status}">${o.status}</span>
          <span><button class="cancel-btn" data-id="${o.id}" ${active ? "" : "disabled"}>Cancel</button></span>
        </div>`;
    }).join("");

    el.querySelectorAll(".cancel-btn:not([disabled])").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm(`Cancel order #${btn.dataset.id}?`)) return;
        btn.disabled = true;
        try {
          const r = await api(`/api/admin/orders/${btn.dataset.id}`, { method: "DELETE" });
          if (r.ok) refresh();
          else { alert("Could not cancel order."); btn.disabled = false; }
        } catch (_) { btn.disabled = false; }
      });
    });
  }

  async function refresh() {
    try {
      const [statsR, ordersR] = await Promise.all([
        api("/api/admin/stats"),
        api("/api/admin/orders"),
      ]);
      renderStats(await statsR.json());
      renderOrders(await ordersR.json());
    } catch (_) { /* handled in api() */ }
  }

  function initResetButton() {
    const btn = document.getElementById("reset-btn");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      if (!confirm("Delete ALL orders and trades and empty the book? This cannot be undone.")) return;
      const typed = prompt('Type RESET to confirm a full market wipe:');
      if (typed !== "RESET") { alert("Cancelled — nothing was deleted."); return; }
      btn.disabled = true;
      const original = btn.textContent;
      btn.textContent = "Resetting…";
      try {
        const r = await api("/api/admin/reset", { method: "POST" });
        if (r.ok) {
          const d = await r.json();
          alert(`Market reset. Removed ${d.deleted_orders} orders and ${d.deleted_trades} trades.`);
          refresh();
        } else {
          alert("Reset failed.");
        }
      } catch (_) { /* handled in api() */ }
      finally { btn.disabled = false; btn.textContent = original; }
    });
  }

  window.addEventListener("DOMContentLoaded", () => {
    refresh();
    initResetButton();
    setInterval(refresh, 4000);
  });
})();
