const runButton = document.querySelector("#speedtest-run");
const statusNode = document.querySelector("#speedtest-status");
const historyNode = document.querySelector("#speedtest-history");
const nodes = {
  download: document.querySelector("#download"),
  upload: document.querySelector("#upload"),
  ping: document.querySelector("#ping"),
  jitter: document.querySelector("#jitter"),
  isp: document.querySelector("#isp"),
  server: document.querySelector("#server"),
  location: document.querySelector("#location"),
  resultUrl: document.querySelector("#result-url"),
};

function valueOrDash(value) {
  return value === null || value === undefined || value === "" ? "--" : value;
}

function setMetric(node, value) {
  node.textContent = Number.isFinite(value) ? value.toFixed(2) : "--";
}

function metricLabel(value, suffix = "") {
  return Number.isFinite(value) ? `${value.toFixed(2)}${suffix}` : "--";
}

function formatTime(timestamp) {
  return new Date(timestamp).toLocaleString("en-US", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function renderResult(summary = {}) {
  setMetric(nodes.download, summary.download_mbps);
  setMetric(nodes.upload, summary.upload_mbps);
  setMetric(nodes.ping, summary.ping_ms);
  setMetric(nodes.jitter, summary.jitter_ms);
  nodes.isp.textContent = valueOrDash(summary.isp);
  nodes.server.textContent = valueOrDash(summary.server);
  nodes.location.textContent = valueOrDash(summary.location);
  if (summary.result_url) {
    nodes.resultUrl.href = summary.result_url;
    nodes.resultUrl.textContent = summary.result_url;
  } else {
    nodes.resultUrl.href = "#";
    nodes.resultUrl.textContent = "--";
  }
}

function renderHistory(results = []) {
  if (!results.length) {
    historyNode.innerHTML = `<div class="speedtest-history-empty">No speedtests recorded yet.</div>`;
    return;
  }

  historyNode.replaceChildren(...results.map((item) => {
    const summary = item.summary || {};
    const row = document.createElement("div");
    row.className = "speedtest-history-row";
    row.innerHTML = `
      <span></span>
      <span></span>
      <span></span>
      <span></span>
      <span></span>
    `;
    const cells = row.querySelectorAll("span");
    cells[0].textContent = formatTime(item.created_at);
    cells[1].textContent = metricLabel(summary.download_mbps, " Mbps");
    cells[2].textContent = metricLabel(summary.upload_mbps, " Mbps");
    cells[3].textContent = metricLabel(summary.ping_ms, " ms");
    cells[4].textContent = [summary.server, summary.location].filter(Boolean).join(" · ") || "--";
    row.addEventListener("click", () => renderResult(summary));
    return row;
  }));
}

async function loadHistory() {
  const response = await fetch("/api/speedtest/history?limit=30", { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || "Could not load speedtest history");
  }
  renderHistory(payload.results || []);
  if (payload.results?.length) {
    renderResult(payload.results[0].summary || {});
  }
}

async function runSpeedtest() {
  runButton.disabled = true;
  statusNode.textContent = "Running...";
  try {
    const response = await fetch("/api/speedtest/run", { method: "POST" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Speedtest failed");
    }
    renderResult(payload.summary || {});
    await loadHistory();
    statusNode.textContent = "Completed";
  } catch (error) {
    statusNode.textContent = error.message;
  } finally {
    runButton.disabled = false;
  }
}

runButton.addEventListener("click", runSpeedtest);
loadHistory().catch((error) => {
  statusNode.textContent = error.message;
});
