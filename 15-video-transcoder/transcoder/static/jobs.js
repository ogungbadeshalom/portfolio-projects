// Poll-backed job list with live WebSocket upgrades once each row is known.
const tbody = document.querySelector("#jobs tbody");
const refresh = document.getElementById("refresh");

async function load() {
  const resp = await fetch("/api/jobs");
  const { jobs } = await resp.json();
  render(jobs);
}

function render(jobs) {
  tbody.innerHTML = "";
  for (const j of jobs) {
    const tr = document.createElement("tr");
    const statusClass = ["completed", "processing", "failed", "cancelled"].includes(j.status)
      ? j.status : "";
    const pct = (j.progress_pct || 0).toFixed(0);
    let actions = "";
    if (j.status === "completed") {
      actions = `<a class="dl" href="/api/jobs/${j.id}/download">zip</a>`;
    }
    tr.innerHTML = `
      <td>${j.id}</td>
      <td>${escapeHtml(j.filename)}</td>
      <td><span class="status ${statusClass}">${j.status}</span></td>
      <td><div class="bar"><span style="width:${pct}%"></span></div> ${pct}%</td>
      <td>${actions}</td>`;
    // Upgrade to live updates for non-terminal jobs.
    if (j.status === "queued" || j.status === "processing") {
      liveRow(tr, j.id);
    }
    tbody.appendChild(tr);
  }
}

function liveRow(tr, id) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/jobs/${id}`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "progress") {
      const bar = tr.querySelector(".bar > span");
      if (bar) bar.style.width = msg.progress_pct.toFixed(0) + "%";
    } else if (msg.type === "job") {
      const sp = tr.querySelector(".status");
      if (sp) { sp.textContent = msg.status; sp.className = "status " + msg.status; }
      if (["completed", "failed", "cancelled"].includes(msg.status)) ws.close();
    }
  };
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

refresh.addEventListener("click", load);
load();
setInterval(load, 3000);