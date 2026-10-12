/* Companion web dashboard script: fetches /api/dashboard and opens a
   WebSocket to /ws/dashboard for live updates. Falls back to polling if the
   socket is unavailable. Vanilla JS, no dependencies. */
(function () {
  "use strict";

  function el(id) { return document.getElementById(id); }

  function setText(id, value) {
    var node = el(id);
    if (node) node.textContent = value == null ? "–" : value;
  }

  function render(data) {
    var c = (data && data.counts) || {};
    setText("c-5m", c.last_5m);
    setText("c-1h", c.last_1h);
    setText("c-24h", c.last_24h);
    setText("c-total", c.total);

    var tbody = document.querySelector("#top-pages tbody");
    if (tbody) {
      var pages = (data && data.top_pages) || [];
      if (pages.length) {
        tbody.innerHTML = pages.map(function (p) {
          return "<tr><td class=\"mono\">" + escapeHtml(p.url) +
                 "</td><td>" + p.views + "</td><td>" + p.unique_users + "</td></tr>";
        }).join("");
      } else {
        tbody.innerHTML = "<tr><td colspan=\"3\" class=\"muted\">no data</td></tr>";
      }
    }

    renderRetention(data && data.retention);
  }

  function renderRetention(cohorts) {
    if (typeof window.Chart === "undefined" || !cohorts || !cohorts.length) return;
    var canvas = el("retention-chart");
    if (!canvas) return;
    var labels = cohorts.slice(0, 10).map(function (c) { return c.cohort_date; });
    var series = [];
    var n = cohorts[0].retention.length;
    for (var d = 0; d < n; d++) {
      series.push({
        label: "D" + d,
        data: cohorts.slice(0, 10).map(function (c) { return c.retention[d]; }),
      });
    }
    new Chart(canvas, {
      type: "line",
      data: { labels: labels, datasets: series.map(function (s) {
        return { label: s.label, data: s.data, borderColor: "#4f8cff",
                 backgroundColor: "transparent", pointRadius: 2 };
      }) },
      options: { responsive: true, scales: { y: { beginAtZero: true, max: 100 } } },
    });
  }

  function escapeHtml(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function refresh() {
    fetch("/api/dashboard").then(function (r) { return r.json(); }).then(render).catch(function () {});
  }

  function connect() {
    var proto = location.protocol === "https:" ? "wss" : "ws";
    var ws = new WebSocket(proto + "://" + location.host + "/ws/dashboard");
    ws.onmessage = function (evt) {
      try { render(JSON.parse(evt.data).data); } catch (e) { /* ignore */ }
    };
    ws.onclose = function () { setTimeout(connect, 2000); }; // auto-reconnect
  }

  refresh();
  if (window.WebSocket) connect();
})();