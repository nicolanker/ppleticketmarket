/* PPLE Graduation Ticket Market — frontend controller.
 * Connects to the WebSocket feed, renders the book / trades / orders, and
 * maintains a step chart of executed prices. Falls back to REST polling if
 * the socket drops. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const euro = (n) => (n == null ? "—" : "€" + Number(n).toFixed(2));
  const fmtTime = (iso) => {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  };

  let chart;
  let lastTradeId = null; // for flash animation on new trades

  /* ---------------- Chart ---------------- */
  function initChart() {
    const ctx = $("price-chart").getContext("2d");
    const grad = ctx.createLinearGradient(0, 0, 0, 240);
    grad.addColorStop(0, "rgba(79,140,255,0.35)");
    grad.addColorStop(1, "rgba(79,140,255,0.0)");
    chart = new Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [{
          label: "Trade price (€)",
          data: [],
          stepped: true,                 // step chart, per spec
          borderColor: "#4f8cff",
          backgroundColor: grad,
          borderWidth: 2,
          fill: true,
          pointRadius: 2,
          pointBackgroundColor: "#4f8cff",
          tension: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 250 },
        plugins: { legend: { display: false }, tooltip: { intersect: false, mode: "index" } },
        scales: {
          x: { ticks: { color: "#8a98ad", maxTicksLimit: 8 }, grid: { color: "rgba(31,42,61,.5)" } },
          y: { ticks: { color: "#8a98ad", callback: (v) => "€" + v }, grid: { color: "rgba(31,42,61,.5)" } },
        },
      },
    });
  }

  function updateChart(trades) {
    // trades arrive newest-first; chart wants chronological order.
    const chrono = [...trades].reverse();
    chart.data.labels = chrono.map((t) => fmtTime(t.created_at));
    chart.data.datasets[0].data = chrono.map((t) => t.price);
    chart.update();
  }

  /* ---------------- Renderers ---------------- */
  function renderBook(book) {
    const maxQty = Math.max(
      1,
      ...book.bids.map((l) => l.quantity),
      ...book.asks.map((l) => l.quantity)
    );

    const row = (l) => `
      <div class="lvl">
        <div class="depth" style="width:${(l.quantity / maxQty) * 100}%"></div>
        <span class="price">${euro(l.price)}</span>
        <span class="qty">${l.quantity}</span>
        <span class="total">${euro(l.price * l.quantity)}</span>
      </div>`;

    // Asks: highest price at the top, best (lowest) ask resting just above the
    // spread. The API returns them lowest-first, so reverse for display.
    const asksHtml = book.asks.length
      ? [...book.asks].reverse().map(row).join("")
      : `<div class="book-empty">No asks</div>`;
    // Bids: best (highest) bid just below the spread, descending. Already
    // highest-first from the API.
    const bidsHtml = book.bids.length
      ? book.bids.map(row).join("")
      : `<div class="book-empty">No bids</div>`;

    $("asks").innerHTML = `<span class="book-pill">Asks</span>` + asksHtml;
    $("bids").innerHTML = `<span class="book-pill">Bids</span>` + bidsHtml;
  }

  function renderTrades(trades) {
    const el = $("trades");
    if (!trades.length) { el.innerHTML = `<div class="empty">No trades yet</div>`; return; }
    const newest = trades[0];
    const isNew = newest.id !== lastTradeId;
    el.innerHTML = trades.map((t) => `
      <div class="trade-row">
        <span class="time">${fmtTime(t.created_at)}</span>
        <span>${t.quantity}</span>
        <span class="price">${euro(t.price)}</span>
      </div>`).join("");
    if (isNew && lastTradeId !== null && el.firstElementChild) {
      el.firstElementChild.classList.add("flash-buy");
    }
    lastTradeId = newest.id;
  }

  function renderOpenOrders(orders) {
    const el = $("open-orders");
    if (!orders.length) { el.innerHTML = `<div class="empty">No open orders</div>`; return; }
    el.innerHTML = orders.map((o) => `
      <div class="order-row">
        <span class="tag ${o.side}">${o.side}</span>
        <span class="email">#${o.id}</span>
        <span>${o.filled}/${o.quantity}</span>
        <span>${o.remaining}</span>
        <span class="price-cell">${euro(o.price)}</span>
      </div>`).join("");
  }

  function renderStats(s) {
    $("t-last").textContent = euro(s.last_price);
    $("t-bid").textContent = euro(s.best_bid);
    $("t-ask").textContent = euro(s.best_ask);
    $("t-spread").textContent = s.spread == null ? "—" : euro(s.spread);
    $("t-vol").textContent = s.total_volume;
    // Last / Spread divider inside the order book.
    $("book-last").textContent = "Last: " + euro(s.last_price);
    $("book-spread").textContent = "Spread: " + (s.spread == null ? "—" : euro(s.spread));
  }

  function render(snapshot) {
    renderStats(snapshot.stats);
    renderBook(snapshot.book);
    renderTrades(snapshot.recent_trades);
    renderOpenOrders(snapshot.open_orders);
    updateChart(snapshot.recent_trades);
  }

  /* ---------------- Connection ---------------- */
  function setConn(online) {
    const c = $("conn");
    c.classList.toggle("online", online);
    c.classList.toggle("offline", !online);
    $("conn-text").textContent = online ? "live" : "reconnecting…";
  }

  let ws;
  let pollTimer;
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => { setConn(true); clearInterval(pollTimer); };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "snapshot") render(msg.data);
    };
    ws.onclose = () => { setConn(false); startPolling(); setTimeout(connect, 2500); };
    ws.onerror = () => ws.close();
  }

  async function fetchSnapshot() {
    try {
      const r = await fetch("/api/snapshot");
      if (r.ok) render(await r.json());
    } catch (_) { /* ignore */ }
  }
  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(fetchSnapshot, 3000);
  }

  /* ---------------- Form ---------------- */
  function initForm() {
    const sideInput = $("side");
    const submitBtn = $("submit-btn");
    const buyBtn = document.querySelector('.side-btn.buy');
    const sellBtn = document.querySelector('.side-btn.sell');

    function setSide(side) {
      sideInput.value = side;
      buyBtn.classList.toggle("active", side === "buy");
      sellBtn.classList.toggle("active", side === "sell");
      submitBtn.classList.toggle("buy", side === "buy");
      submitBtn.classList.toggle("sell", side === "sell");
      submitBtn.textContent = `Submit ${side} order`;
    }
    buyBtn.addEventListener("click", () => setSide("buy"));
    sellBtn.addEventListener("click", () => setSide("sell"));

    $("order-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const msg = $("form-msg");
      msg.className = "form-msg";
      msg.textContent = "";
      const payload = {
        email: $("email").value.trim(),
        side: sideInput.value,
        quantity: parseInt($("quantity").value, 10),
        price: parseFloat($("price").value),
      };
      submitBtn.disabled = true;
      try {
        const r = await fetch("/api/orders", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await r.json();
        if (!r.ok) {
          const detail = Array.isArray(data.detail)
            ? data.detail.map((d) => d.msg).join("; ")
            : data.detail || "Order rejected";
          throw new Error(detail);
        }
        const n = data.trades.length;
        msg.classList.add("success");
        msg.textContent = n
          ? `Order matched — ${n} trade${n > 1 ? "s" : ""} executed. Check your email.`
          : `Order resting on the book.`;
        $("price").value = "";
      } catch (err) {
        msg.classList.add("error");
        msg.textContent = err.message;
      } finally {
        submitBtn.disabled = false;
      }
    });
  }

  /* ---------------- Boot ---------------- */
  window.addEventListener("DOMContentLoaded", () => {
    initChart();
    initForm();
    fetchSnapshot();
    connect();
  });
})();
