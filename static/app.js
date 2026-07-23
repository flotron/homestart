const state = {
  apps: [],
  query: "",
  appType: "all",
  filePath: "",
  fileParent: "",
  fileRoots: [],
  fileRootEntries: [],
  fileDriveEntries: [],
  fileClipboard: (() => {
    try { return JSON.parse(sessionStorage.getItem("homestart-file-clipboard") || "null"); }
    catch { return null; }
  })(),
  selectedFile: null,
  editingSambaShare: null,
  features: { file_operations: true },
  view: "status",
  networkInterfaces: [],
  selectedNetwork: null,
  githubUpdate: null,
  resourceProcesses: [],
  processSort: { key: "cpu_percent", direction: "desc" },
  storeResults: [],
  selectedStoreApp: null,
  favorites: new Set(JSON.parse(localStorage.getItem("homestart-favorites") || "[]")),
};

const navItems = [...document.querySelectorAll(".nav-item")];
const viewPanels = [...document.querySelectorAll("[data-view-panel]")];
const typeFilterItems = [...document.querySelectorAll(".type-filter-item")];
const appsNode = document.querySelector("#apps");
const hostNode = document.querySelector("#host");
const dashboardTitle = document.querySelector("#dashboard-title");
const dashboardSubtitle = document.querySelector("#dashboard-subtitle");
const template = document.querySelector("#app-card");
const search = document.querySelector("#search");
const refresh = document.querySelector("#refresh");
const openAppStore = document.querySelector("#open-app-store");
const closeAppStore = document.querySelector("#close-app-store");
const appStorePanel = document.querySelector("#app-store-panel");
const storeSearchForm = document.querySelector("#store-search-form");
const storeSearch = document.querySelector("#store-search");
const storeStatus = document.querySelector("#store-status");
const storeResults = document.querySelector("#store-results");
const storeInstallDialog = document.querySelector("#store-install-dialog");
const storeInstallForm = document.querySelector("#store-install-form");
const storeInstallTitle = document.querySelector("#store-install-title");
const storeInstallImage = document.querySelector("#store-install-image");
const storeInstallName = document.querySelector("#store-install-name");
const storeInstallHostPort = document.querySelector("#store-install-host-port");
const storeInstallContainerPort = document.querySelector("#store-install-container-port");
const storeInstallEnv = document.querySelector("#store-install-env");
const storeInstallVolumes = document.querySelector("#store-install-volumes");
const storeInstallRestart = document.querySelector("#store-install-restart");
const storeInstallCancel = document.querySelector("#store-install-cancel");
const storeInstallSubmit = document.querySelector("#store-install-submit");
const storeInstallProgress = document.querySelector("#store-install-progress");
const storeInstallStage = document.querySelector("#store-install-stage");
const storeInstallPercent = document.querySelector("#store-install-percent");
const storeInstallBar = document.querySelector("#store-install-bar");
const storeInstallMessage = document.querySelector("#store-install-message");
const storeInstallLog = document.querySelector("#store-install-log");
const refreshStatus = document.querySelector("#refresh-status");
const cpuValue = document.querySelector("#cpu-value");
const cpuBar = document.querySelector("#cpu-bar");
const cpuRing = document.querySelector("#cpu-ring");
const memoryValue = document.querySelector("#memory-value");
const memoryBar = document.querySelector("#memory-bar");
const memoryRing = document.querySelector("#memory-ring");
const gpuValue = document.querySelector("#gpu-value");
const gpuBar = document.querySelector("#gpu-bar");
const gpuRing = document.querySelector("#gpu-ring");
const gpuDetail = document.querySelector("#gpu-detail");
const gpuList = document.querySelector("#gpu-list");
const disksNode = document.querySelector("#disks");
const resourcesPanel = document.querySelector("#resources-panel");
const resourceHost = document.querySelector("#resource-host");
const resourceUptime = document.querySelector("#resource-uptime");
const resourceCpu = document.querySelector("#resource-cpu");
const resourceMemory = document.querySelector("#resource-memory");
const resourceContainers = document.querySelector("#resource-containers");
const resourceProcesses = document.querySelector("#resource-processes");
const resourceTasks = document.querySelector("#resource-tasks");
const processSortButtons = [...document.querySelectorAll("[data-process-sort]")];
const filesNode = document.querySelector("#files");
const filePathNode = document.querySelector("#file-path");
const filePathForm = document.querySelector("#file-path-form");
const fileUp = document.querySelector("#file-up");
const fileHome = document.querySelector("#file-home");
const fileNewFolder = document.querySelector("#file-new-folder");
const filePaste = document.querySelector("#file-paste");
const fileUpload = document.querySelector("#file-upload");
const fileDropStatus = document.querySelector("#file-drop-status");
const fileMain = document.querySelector(".file-main");
const fileRoots = document.querySelector("#file-roots");
const fileCount = document.querySelector("#file-count");
const fileLocationName = document.querySelector("#file-location-name");
const fileContextMenu = document.querySelector("#file-context-menu");
const fileContextName = document.querySelector("#file-context-name");
const fileContextKind = document.querySelector("#file-context-kind");
const fileContextActions = [...document.querySelectorAll("[data-file-context-action]")];
const sambaRefresh = document.querySelector("#samba-refresh");
const sambaStatus = document.querySelector("#samba-status");
const sambaShares = document.querySelector("#samba-shares");
const sambaShareForm = document.querySelector("#samba-share-form");
const sambaShareName = document.querySelector("#samba-share-name");
const sambaSharePath = document.querySelector("#samba-share-path");
const sambaShareUsers = document.querySelector("#samba-share-users");
const sambaUserList = document.querySelector("#samba-user-list");
const sambaShareWritable = document.querySelector("#samba-share-writable");
const sambaShareGuest = document.querySelector("#samba-share-guest");
const sambaShareBrowseable = document.querySelector("#samba-share-browseable");
const sambaUseCurrent = document.querySelector("#samba-use-current");
const sambaShareSubmit = document.querySelector("#samba-share-submit");
const sambaShareCancel = document.querySelector("#samba-share-cancel");
const sambaForceUserField = document.querySelector("#samba-force-user-field");
const sambaForceUser = document.querySelector("#samba-force-user");
const sambaCredentialUser = document.querySelector("#samba-credential-user");
const sambaCredentialPassword = document.querySelector("#samba-credential-password");
const sambaCredentialSave = document.querySelector("#samba-credential-save");
const refreshNetwork = document.querySelector("#refresh-network");
const networkInterfaces = document.querySelector("#network-interfaces");
const networkForm = document.querySelector("#network-form");
const networkInterface = document.querySelector("#network-interface");
const networkMode = document.querySelector("#network-mode");
const networkAddress = document.querySelector("#network-address");
const networkGateway = document.querySelector("#network-gateway");
const networkDns = document.querySelector("#network-dns");
const networkManagedBy = document.querySelector("#network-managed-by");
const monitorInterface = document.querySelector("#monitor-interface");
const monitorInterfaceDetail = document.querySelector("#monitor-interface-detail");
const updateForm = document.querySelector("#update-form");
const updateFile = document.querySelector("#update-file");
const updateStatus = document.querySelector("#update-status");
const updateApply = document.querySelector("#update-apply");
const githubUpdateStatus = document.querySelector("#github-update-status");
const githubUpdateCheck = document.querySelector("#github-update-check");
const githubUpdateApply = document.querySelector("#github-update-apply");
const healthBanner = document.querySelector("#health-banner");
const healthLabel = document.querySelector("#health-label");
const healthHost = document.querySelector("#health-host");
const healthUptime = document.querySelector("#health-uptime");
const summaryContainers = document.querySelector("#summary-containers");
const summaryServices = document.querySelector("#summary-services");
const summaryAlerts = document.querySelector("#summary-alerts");
const summaryNetwork = document.querySelector("#summary-network");
const summaryTemperature = document.querySelector("#summary-temperature");
const overviewAlerts = document.querySelector("#overview-alerts");
const restoreIgnoredAlerts = document.querySelector("#restore-ignored-alerts");
const historyChart = document.querySelector("#history-chart");
const historyRange = document.querySelector("#history-range");
const historyStats = document.querySelector("#history-stats");
const historyMeta = document.querySelector("#history-meta");
const historyTimeAxis = document.querySelector("#history-time-axis");
const bandwidthChart = document.querySelector("#bandwidth-chart");
const bandwidthStats = document.querySelector("#bandwidth-stats");
const bandwidthMeta = document.querySelector("#bandwidth-meta");
const bandwidthTimeAxis = document.querySelector("#bandwidth-time-axis");
const bandwidthSubtitle = document.querySelector("#bandwidth-subtitle");
const liveDownload = document.querySelector("#live-download");
const liveUpload = document.querySelector("#live-upload");
const liveDownloadTop = document.querySelector("#live-download-top");
const liveUploadTop = document.querySelector("#live-upload-top");
const liveInterface = document.querySelector("#live-interface");
const liveUpdated = document.querySelector("#live-updated");
let liveNetworkLoading = false;
const logsDialog = document.querySelector("#logs-dialog");
const logsTitle = document.querySelector("#logs-title");
const logsContent = document.querySelector("#logs-content");
const logsClose = document.querySelector("#logs-close");
const toastRegion = document.querySelector("#toast-region");
const generalSettingsForm = document.querySelector("#general-settings-form");
const backupCreate = document.querySelector("#backup-create");
const trashList = document.querySelector("#trash-list");

function toast(message, kind = "info") {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  toastRegion.appendChild(node);
  requestAnimationFrame(() => node.classList.add("visible"));
  setTimeout(() => { node.classList.remove("visible"); setTimeout(() => node.remove(), 250); }, 3600);
}

async function showDockerLogs(app) {
  logsTitle.textContent = `${app.name} logs`;
  logsContent.textContent = "Loading…";
  logsDialog.showModal();
  try {
    const response = await fetch(`/api/docker/logs?name=${encodeURIComponent(app.docker_name)}&tail=500`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Could not load logs");
    logsContent.textContent = data.logs || "No log output.";
    logsContent.scrollTop = logsContent.scrollHeight;
  } catch (error) { logsContent.textContent = error.message; }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[character]);
}

function chartPath(points, key, width, height, startTime, endTime, verticalMax) {
  let previousTime = null;
  const gapLimit = Math.max(120, (endTime - startTime) / 1200 * 3);
  return points.map((item) => {
    const value = item[key];
    if (value === null || value === undefined) return "";
    const timestamp = Number(item.captured_at) || startTime;
    const x = (timestamp - startTime) / Math.max(1, endTime - startTime) * width;
    const y = height - Math.max(0, Math.min(verticalMax, value)) / verticalMax * height;
    const command = previousTime === null || timestamp - previousTime > gapLimit ? "M" : "L";
    previousTime = timestamp;
    return `${command}${x.toFixed(1)},${y.toFixed(1)}`;
  }).filter(Boolean).join(" ");
}

function chartPoint(points, key, width, height, startTime, endTime, verticalMax, className) {
  if (points.length !== 1 || points[0][key] === null || points[0][key] === undefined) return "";
  const timestamp = Number(points[0].captured_at) || startTime;
  const value = Math.max(0, Math.min(verticalMax, Number(points[0][key]) || 0));
  const x = (timestamp - startTime) / Math.max(1, endTime - startTime) * width;
  const y = height - value / verticalMax * height;
  return `<circle class="chart-point ${className}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" />`;
}

function metricStats(points, key) {
  const values = points.map((item) => item[key]).filter((value) => value !== null && value !== undefined).map(Number).filter(Number.isFinite);
  if (!values.length) return null;
  return { current: values.at(-1), average: values.reduce((sum, value) => sum + value, 0) / values.length, maximum: Math.max(...values) };
}

function historyWindow(points, hours) {
  const now = Math.floor(Date.now() / 1000);
  if (hours !== "auto") return { start: now - Number(hours || 24) * 3600, end: now };
  const first = Number(points[0]?.captured_at) || now;
  const last = Number(points.at(-1)?.captured_at) || now;
  const span = Math.max(60, last - first);
  const padding = Math.max(15, span * 0.04);
  return { start: first - padding, end: last + padding };
}

function renderTimeAxis(node, startTime, endTime) {
  const formatter = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", ...(endTime - startTime > 86400 ? { day: "2-digit", month: "2-digit" } : {}) });
  node.replaceChildren(...[0, .25, .5, .75, 1].map((position) => {
    const label = document.createElement("span");
    label.textContent = formatter.format(new Date((startTime + (endTime - startTime) * position) * 1000));
    return label;
  }));
}

function renderHistory(points, hours) {
  if (!historyChart) return;
  if (!points.length) {
    historyChart.innerHTML = '<div class="empty-state">History will appear after HomeStart collects a few samples.</div>';
    historyStats.replaceChildren();
    historyTimeAxis.replaceChildren();
    historyMeta.textContent = "No samples in this period yet. HomeStart now collects one every 30 seconds in the background.";
    return;
  }
  const width = 800;
  const height = 220;
  const window = historyWindow(points, hours);
  const { start: startTime, end: endTime } = window;
  const allValues = points.flatMap((item) => [item.cpu, item.memory, item.gpu]).filter((value) => value !== null && value !== undefined).map(Number).filter(Number.isFinite);
  const observedMax = Math.max(1, ...allValues);
  const verticalMax = Math.min(100, Math.max(10, Math.ceil(observedMax * 1.2 / 10) * 10));
  const half = verticalMax / 2;
  historyChart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="System usage history">
    <g class="chart-grid"><path d="M0 0H${width} M0 ${height / 2}H${width} M0 ${height}H${width}" /></g>
    <g class="chart-axis"><text x="4" y="13">${verticalMax}%</text><text x="4" y="${height / 2 - 5}">${half}%</text><text x="4" y="${height - 6}">0%</text></g>
    <path class="chart-line cpu" d="${chartPath(points, "cpu", width, height, startTime, endTime, verticalMax)}" />
    <path class="chart-line memory" d="${chartPath(points, "memory", width, height, startTime, endTime, verticalMax)}" />
    <path class="chart-line gpu" d="${chartPath(points, "gpu", width, height, startTime, endTime, verticalMax)}" />
  </svg>`;
  renderTimeAxis(historyTimeAxis, startTime, endTime);
  const labels = { cpu: "CPU", memory: "Memory", gpu: "GPU" };
  historyStats.replaceChildren(...Object.entries(labels).map(([key, label]) => {
    const stats = metricStats(points, key);
    const node = document.createElement("article");
    node.className = `history-stat ${key}`;
    node.innerHTML = `<span>${label}</span><strong>${stats ? `${stats.current.toFixed(1)}%` : "--"}</strong><small>${stats ? `avg ${stats.average.toFixed(1)}% · max ${stats.maximum.toFixed(1)}%` : "not detected"}</small>`;
    return node;
  }));
  const first = new Date(points[0].captured_at * 1000).toLocaleString();
  const last = new Date(points.at(-1).captured_at * 1000).toLocaleString();
  const rangeLabel = hours === "auto" ? "showing all available data" : `selected range ${hours}h`;
  historyMeta.textContent = `${points.length} samples · ${first} to ${last} · ${rangeLabel} · scale 0–${verticalMax}%`;
}

function formatRate(bytesPerSecond) {
  const bits = Math.max(0, Number(bytesPerSecond) || 0) * 8;
  if (bits >= 1_000_000_000) return `${(bits / 1_000_000_000).toFixed(1)} Gbps`;
  if (bits >= 1_000_000) return `${(bits / 1_000_000).toFixed(1)} Mbps`;
  if (bits >= 1_000) return `${(bits / 1_000).toFixed(1)} Kbps`;
  return `${bits.toFixed(0)} bps`;
}

function bandwidthScale(maximum) {
  const targetBits = Math.max(1, Number(maximum) || 0) * 8 * 1.1;
  const magnitude = 10 ** Math.floor(Math.log10(targetBits));
  const fraction = targetBits / magnitude;
  const niceFraction = [1, 2, 2.5, 5, 10].find((value) => value >= fraction) || 10;
  return niceFraction * magnitude / 8;
}

function renderBandwidthHistory(points, hours, interfaceName) {
  const values = points.flatMap((item) => [item.rx_bps, item.tx_bps]).filter((value) => value !== null && value !== undefined).map(Number).filter(Number.isFinite);
  bandwidthSubtitle.textContent = `Traffic through ${interfaceName || "the default network interface"}.`;
  if (!values.length) {
    bandwidthChart.innerHTML = '<div class="empty-state">Bandwidth history will appear after the first background samples.</div>';
    bandwidthStats.replaceChildren(); bandwidthTimeAxis.replaceChildren();
    bandwidthMeta.textContent = "No bandwidth samples in this period yet.";
    return;
  }
  const width = 800; const height = 220;
  const { start, end } = historyWindow(points, hours);
  const verticalMax = bandwidthScale(Math.max(1, ...values));
  bandwidthChart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Network bandwidth history">
    <g class="chart-grid"><path d="M0 0H${width} M0 ${height / 2}H${width} M0 ${height}H${width}" /></g>
    <g class="chart-axis"><text x="4" y="13">${formatRate(verticalMax)}</text><text x="4" y="${height / 2 - 5}">${formatRate(verticalMax / 2)}</text><text x="4" y="${height - 6}">0 bps</text></g>
    <path class="chart-line download" d="${chartPath(points, "rx_bps", width, height, start, end, verticalMax)}" />
    <path class="chart-line upload" d="${chartPath(points, "tx_bps", width, height, start, end, verticalMax)}" />
    ${chartPoint(points, "rx_bps", width, height, start, end, verticalMax, "download")}
    ${chartPoint(points, "tx_bps", width, height, start, end, verticalMax, "upload")}
  </svg>`;
  renderTimeAxis(bandwidthTimeAxis, start, end);
  bandwidthStats.replaceChildren(...[["rx_bps", "Download", "download"], ["tx_bps", "Upload", "upload"]].map(([key, label, className]) => {
    const stats = metricStats(points, key); const node = document.createElement("article");
    node.className = `history-stat ${className}`;
    node.innerHTML = `<span>${label}</span><strong>${formatRate(stats?.current)}</strong><small>avg ${formatRate(stats?.average)} · max ${formatRate(stats?.maximum)}</small>`;
    return node;
  }));
  bandwidthMeta.textContent = `${points.length} displayed points · sampled every 2 seconds · retained for 7 days · adaptive scale up to ${formatRate(verticalMax)}`;
}

async function loadLiveNetwork() {
  if (liveNetworkLoading || document.hidden) return;
  liveNetworkLoading = true;
  try {
    const response = await fetch(`/api/network/live?time=${Date.now()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Live network unavailable");
    liveDownload.textContent = formatRate(data.rx_bps);
    liveUpload.textContent = formatRate(data.tx_bps);
    const downloadTop = data.top_consumers?.download;
    const uploadTop = data.top_consumers?.upload;
    liveDownloadTop.textContent = downloadTop ? `Top now: ${downloadTop.name} · ${formatRate(downloadTop.rx_bps)}` : "Top now: no Docker activity";
    liveUploadTop.textContent = uploadTop ? `Top now: ${uploadTop.name} · ${formatRate(uploadTop.tx_bps)}` : "Top now: no Docker activity";
    liveInterface.textContent = data.interface || "Default interface";
    liveUpdated.textContent = `Live · updated ${new Date(data.timestamp * 1000).toLocaleTimeString()}`;
  } catch (error) {
    liveUpdated.textContent = error.message;
  } finally {
    liveNetworkLoading = false;
  }
}

async function loadHistory() {
  const response = await fetch(`/api/metrics/history?hours=${historyRange?.value || 24}`, { cache: "no-store" });
  const data = await response.json();
  renderHistory(data.points || [], data.hours || historyRange?.value || 24);
  renderBandwidthHistory(data.network_points || data.points || [], data.hours || historyRange?.value || 24, data.network_interface || "");
}

async function loadOverview() {
  const response = await fetch("/api/overview", { cache: "no-store" });
  const data = await response.json();
  let ignored;
  try { ignored = new Set(JSON.parse(localStorage.getItem("homestart-ignored-alerts") || "[]")); }
  catch { ignored = new Set(); }
  const visibleAlerts = (data.alerts || []).filter((alert) => !ignored.has(alert.id || alert.title));
  const visibleHealth = visibleAlerts.some((alert) => alert.level === "critical") ? "critical" : visibleAlerts.length ? "warning" : "healthy";
  healthBanner.dataset.health = visibleHealth;
  healthLabel.textContent = visibleHealth === "healthy" ? "All systems operational" : visibleHealth === "critical" ? "Action required" : "System needs attention";
  healthHost.textContent = data.hostname || "--";
  healthUptime.textContent = `Uptime ${data.uptime || "--"}`;
  summaryContainers.textContent = `${data.summary.containers_running}/${data.summary.containers_total} running`;
  summaryServices.textContent = `${data.summary.services_ok}/${data.summary.services_total} active`;
  summaryAlerts.textContent = String(visibleAlerts.length);
  summaryNetwork.textContent = `↓ ${data.system.network?.rx_label || "--"} · ↑ ${data.system.network?.tx_label || "--"}`;
  summaryTemperature.textContent = data.system.temperature?.available ? `${data.system.temperature.celsius} °C` : "Not detected";
  overviewAlerts.replaceChildren();
  if (!visibleAlerts.length) overviewAlerts.innerHTML = '<div class="empty-state success">No active alerts. Everything looks good.</div>';
  visibleAlerts.forEach((alert) => {
    const node = document.createElement("div");
    node.className = `alert-item ${alert.level}`;
    node.innerHTML = `<span></span><div><strong></strong><p></p></div><button type="button">Ignore</button>`;
    node.querySelector("strong").textContent = alert.title;
    node.querySelector("p").textContent = alert.detail;
    node.querySelector("button").addEventListener("click", () => {
      ignored.add(alert.id || alert.title);
      localStorage.setItem("homestart-ignored-alerts", JSON.stringify([...ignored]));
      loadOverview().catch(console.error);
    });
    overviewAlerts.appendChild(node);
  });
  const ignoredActive = (data.alerts || []).filter((alert) => ignored.has(alert.id || alert.title)).length;
  restoreIgnoredAlerts.hidden = ignoredActive === 0;
  restoreIgnoredAlerts.textContent = `Restore ignored (${ignoredActive})`;
}

function normalize(value) {
  return String(value || "").toLowerCase();
}

function matches(app) {
  if (state.appType !== "all" && app.app_type !== state.appType) {
    return false;
  }

  const haystack = [
    app.name,
    app.kind,
    app.status,
    app.description,
    app.app_type,
    app.app_type_label,
    app.url,
    ...(app.tags || []),
    ...(app.ports || []),
  ].map(normalize).join(" ");
  return haystack.includes(normalize(state.query));
}

function buttonLabel(action) {
  if (action === "stop") return "stop";
  if (action === "restart") return "restart";
  return "uninstall";
}

async function runAppAction(app, action) {
  if (action === "uninstall" && !state.features.app_uninstall) {
    window.alert("App uninstall is disabled in HomeStart settings.");
    return;
  }
  if (action !== "uninstall" && app.docker_name && !state.features.docker_actions) {
    window.alert("Docker actions are disabled in HomeStart settings.");
    return;
  }
  if (action !== "uninstall" && app.service_name && !state.features.native_service_actions) {
    window.alert("Native service actions are disabled in HomeStart settings.");
    return;
  }

  const label = buttonLabel(action);
  if (action === "uninstall") {
    const confirmation = `UNINSTALL ${app.name}`;
    const typed = window.prompt(
      `This will remove ${app.name} from HomeStart.\n\nFor Docker apps, only the container is removed. Images and volumes are preserved.\n\nType "${confirmation}" to continue.`
    );
    if (typed === null) return;
    if (typed !== confirmation) {
      window.alert(`Confirmation did not match.\n\nExpected exactly:\n${confirmation}`);
      return;
    }
  } else {
    const confirmed = window.confirm(`Confirm ${label} for ${app.name}. This action can interrupt the service.`);
    if (!confirmed) return;
  }

  const busyButton = document.querySelector(`[data-action-key="${app.action_key || ""}-${action}"]`);
  if (busyButton) {
    busyButton.disabled = true;
    busyButton.textContent = action === "uninstall" ? "Removing..." : "Working...";
  }

  let result = {};
  try {
    const response = await fetch("/api/apps/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        docker_name: app.docker_name,
        service_name: app.service_name,
        app_name: app.name,
        action,
      }),
    });
    result = await response.json();
    if (!response.ok || !result.ok) {
      window.alert(result.error || `Could not ${label} ${app.name}`);
      await load();
      return;
    }
  } catch (error) {
    window.alert(error.message || `Could not ${label} ${app.name}`);
    await load();
    return;
  }

  await load();
  await loadStatus();
  if (action === "uninstall") {
    window.alert(result.message || `${app.name} was uninstalled.`);
    window.setTimeout(() => load().catch(console.error), 900);
  }
}

function render() {
  appsNode.replaceChildren();
  state.apps.filter(matches).sort((a, b) => Number(state.favorites.has(b.icon_key)) - Number(state.favorites.has(a.icon_key)) || String(a.name).localeCompare(String(b.name))).forEach((app) => {
    const node = template.content.cloneNode(true);
    const card = node.querySelector(".card");
    const icon = node.querySelector(".icon");
    const iconImage = node.querySelector(".icon img");
    const iconUpload = node.querySelector(".icon-upload");
    const iconUploadInput = node.querySelector(".icon-upload input");
    const title = node.querySelector("h2");
    const kind = node.querySelector(".kind");
    const favorite = node.querySelector(".favorite");
    const badges = node.querySelector(".badges");
    const description = node.querySelector(".description");
    const meta = node.querySelector(".meta");
    const open = node.querySelector(".open");
    const stop = node.querySelector(".stop");
    const restart = node.querySelector(".restart");
    const logs = node.querySelector(".logs");
    const uninstall = node.querySelector(".uninstall");
    app.action_key = app.icon_key || normalize(`${app.name}-${app.docker_name || app.service_name || ""}`);
    const favoriteKey = app.icon_key || app.action_key;
    favorite.textContent = state.favorites.has(favoriteKey) ? "★" : "☆";
    favorite.classList.toggle("active", state.favorites.has(favoriteKey));
    favorite.addEventListener("click", () => {
      state.favorites.has(favoriteKey) ? state.favorites.delete(favoriteKey) : state.favorites.add(favoriteKey);
      localStorage.setItem("homestart-favorites", JSON.stringify([...state.favorites]));
      render();
    });

    title.textContent = app.name || "App";
    icon.dataset.fallback = (app.name || "?").slice(0, 1).toUpperCase();
    if (app.icon_url) {
      iconImage.src = app.icon_url;
      iconImage.addEventListener("error", () => {
        iconImage.removeAttribute("src");
        icon.classList.add("fallback");
        iconUpload.classList.add("visible");
      });
    } else {
      icon.classList.add("fallback");
      iconUpload.classList.add("visible");
    }
    if (app.custom_icon) {
      iconUpload.classList.add("visible");
      iconUpload.title = "Replace custom icon";
    }
    iconUploadInput.addEventListener("change", () => uploadAppIcon(app, iconUploadInput));
    kind.textContent = app.kind || app.app_type_label || "Service";
    badges.replaceChildren(...(app.tags || [app.app_type_label]).filter(Boolean).map((tag) => {
      const badge = document.createElement("span");
      badge.className = `badge ${app.app_type || ""}`;
      badge.textContent = tag;
      return badge;
    }));
    description.textContent = app.description || app.image || "Installed service";
    meta.textContent = app.status || (app.ports || []).map((port) => `Port ${port}`).join(" · ");

    if (app.url) {
      open.href = app.url;
    } else {
      open.href = "#";
      open.textContent = "No web port";
      open.setAttribute("aria-disabled", "true");
      card.classList.add("disabled");
    }

    if (app.available === false) {
      open.setAttribute("aria-disabled", "true");
      open.href = "#";
      card.classList.add("disabled");
    }

    if (
      (app.docker_name && state.features.docker_actions)
      || (app.service_actionable && app.service_name && state.features.native_service_actions)
    ) {
      stop.dataset.actionKey = `${app.action_key}-stop`;
      restart.dataset.actionKey = `${app.action_key}-restart`;
      stop.addEventListener("click", () => runAppAction(app, "stop"));
      restart.addEventListener("click", () => runAppAction(app, "restart"));
    } else {
      stop.disabled = true;
      restart.disabled = true;
      stop.title = "This app has no linked Docker container or native service";
      restart.title = "This app has no linked Docker container or native service";
    }
    if (app.docker_name) logs.addEventListener("click", () => showDockerLogs(app));
    else { logs.disabled = true; logs.title = "Logs are available for Docker apps"; }

    uninstall.dataset.actionKey = `${app.action_key}-uninstall`;
    uninstall.addEventListener("click", () => {
      if (app.uninstallable && state.features.app_uninstall) {
        runAppAction(app, "uninstall");
        return;
      }
      window.alert(app.uninstall_reason || "This app cannot be uninstalled from HomeStart.");
    });
    if (app.uninstallable && state.features.app_uninstall) {
      uninstall.title = app.uninstall_reason || "Uninstall this app";
    } else {
      uninstall.classList.add("inactive");
      uninstall.setAttribute("aria-disabled", "true");
      uninstall.title = app.uninstall_reason || "This app cannot be uninstalled from HomeStart";
    }

    appsNode.appendChild(node);
  });
}

function formatPercent(value) {
  return Number.isFinite(value) ? `${value.toFixed(1)}%` : "--";
}

function compactNumber(value) {
  const number = Number(value) || 0;
  if (number >= 1_000_000_000) return `${(number / 1_000_000_000).toFixed(1)}B`;
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (number >= 1_000) return `${(number / 1_000).toFixed(1)}K`;
  return String(number);
}

function suggestedContainerName(image) {
  return String(image || "app")
    .split("/")
    .pop()
    .split(":")[0]
    .replace(/[^A-Za-z0-9_.-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64) || "app";
}

function renderStoreResult(item) {
  const node = document.createElement("article");
  node.className = "store-card";
  node.innerHTML = `
    <div class="store-card-head">
      <span class="store-icon"><img alt="" /></span>
      <div>
        <div class="store-title-row"><h3></h3><span class="verified-badge" hidden aria-label="Verified">✓</span></div>
        <span class="store-namespace"></span>
        <p></p>
      </div>
    </div>
    <div class="store-meta"></div>
    <div class="store-actions">
      <a class="store-link" target="_blank" rel="noopener noreferrer">Docker Hub</a>
      <button type="button">Install</button>
    </div>
  `;
  const icon = node.querySelector(".store-icon");
  const iconImage = node.querySelector(".store-icon img");
  icon.dataset.fallback = item.icon_label || (item.name || "?").slice(0, 1).toUpperCase();
  if (item.icon_url) {
    iconImage.src = item.icon_url;
    iconImage.addEventListener("error", () => {
      iconImage.removeAttribute("src");
      icon.classList.add("fallback");
    });
  } else {
    icon.classList.add("fallback");
  }
  node.querySelector("h3").textContent = item.repo || item.name;
  const verifiedBadge = node.querySelector(".verified-badge");
  if (item.verified) {
    verifiedBadge.hidden = false;
    verifiedBadge.title = item.verification_label || "Verified Publisher";
    verifiedBadge.setAttribute("aria-label", item.verification_label || "Verified Publisher");
  }
  node.querySelector(".store-namespace").textContent = item.namespace
    ? `${item.namespace}/${item.repo || ""}`
    : item.name;
  node.querySelector("p").textContent = item.description || "Docker Hub image";
  node.querySelector(".store-meta").textContent = [
    item.official ? "Official" : "",
    !item.official && item.verification_label ? item.verification_label : "",
    item.automated ? "Automated" : "",
    `${compactNumber(item.stars)} stars`,
    `${compactNumber(item.pulls)} pulls`,
  ].filter(Boolean).join(" · ");
  const link = node.querySelector(".store-link");
  link.href = item.page_url || `https://hub.docker.com/r/${encodeURIComponent(item.image || item.name)}`;
  link.textContent = item.link_label || "Docker Hub";
  link.title = `Open the image page for ${item.name}`;
  const install = node.querySelector("button");
  if (item.installed) {
    install.textContent = "Installed";
    install.disabled = true;
    install.title = `Installed as ${(item.installed_containers || []).join(", ")}`;
    node.classList.add("installed");
  } else {
    install.addEventListener("click", () => openStoreInstall(item));
  }
  return node;
}

function renderStoreResults() {
  if (!state.storeResults.length) {
    storeResults.replaceChildren();
    return;
  }
  storeResults.replaceChildren(...state.storeResults.map(renderStoreResult));
}

async function searchStore(event) {
  event.preventDefault();
  const query = storeSearch.value.trim();
  if (query.length < 2) {
    storeStatus.textContent = "Type at least 2 characters to search Docker Hub.";
    return;
  }
  storeStatus.textContent = "Searching Docker Hub...";
  storeResults.replaceChildren();
  const response = await fetch(`/api/store/search?query=${encodeURIComponent(query)}`, { cache: "no-store" });
  const result = await response.json();
  if (!response.ok || !result.ok) {
    storeStatus.textContent = result.error || "Could not search Docker Hub.";
    return;
  }
  state.storeResults = result.results || [];
  storeStatus.textContent = state.storeResults.length
    ? `${state.storeResults.length} Docker Hub results`
    : "No Docker Hub results found.";
  renderStoreResults();
}

function openStoreInstall(item) {
  state.selectedStoreApp = item;
  storeInstallTitle.textContent = item.name;
  storeInstallImage.textContent = item.image;
  storeInstallName.value = suggestedContainerName(item.image);
  storeInstallHostPort.value = item.host_port || "";
  storeInstallContainerPort.value = item.container_port || "";
  storeInstallEnv.value = "";
  storeInstallVolumes.value = item.volume || "";
  storeInstallRestart.value = "unless-stopped";
  storeInstallProgress.hidden = true;
  storeInstallLog.textContent = "";
  storeInstallDialog.showModal();
}

function renderInstallProgress(job) {
  const labels = { validating: "Validating", pulling: "Downloading image", creating: "Creating container", starting: "Starting container", completed: "Installed", failed: "Installation failed" };
  const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
  storeInstallProgress.hidden = false;
  storeInstallStage.textContent = labels[job.stage] || "Installing";
  storeInstallPercent.textContent = `${Math.round(progress)}%`;
  storeInstallBar.style.width = `${progress}%`;
  storeInstallMessage.textContent = job.message || "Working…";
  storeInstallLog.textContent = (job.log || []).join("\n");
}

async function watchStoreInstall(jobId, payload) {
  while (true) {
    const response = await fetch(`/api/store/install/status?job_id=${encodeURIComponent(jobId)}`, { cache: "no-store" });
    const job = await response.json();
    if (!response.ok || !job.ok) throw new Error(job.error || "Could not read installation status");
    renderInstallProgress(job);
    if (job.status === "failed") throw new Error(job.error || "Installation failed");
    if (job.status === "completed") {
      storeInstallSubmit.textContent = "Installed";
      toast(job.message || `${payload.name} installed`, "success");
      await Promise.all([load(), loadStatus()]);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

async function loadStoreTemplates() {
  storeStatus.textContent = "Recommended apps";
  const response = await fetch("/api/store/templates", { cache: "no-store" });
  const data = await response.json();
  state.storeResults = (data.templates || []).map((item) => ({ ...item, repo: item.name, namespace: "HomeStart template" }));
  renderStoreResults();
}

async function installStoreApp(event) {
  event.preventDefault();
  const item = state.selectedStoreApp;
  if (!item) return;
  const payload = {
    image: item.image,
    name: storeInstallName.value.trim(),
    host_port: storeInstallHostPort.value.trim(),
    container_port: storeInstallContainerPort.value.trim(),
    env: storeInstallEnv.value.split("\n").map((line) => line.trim()).filter(Boolean),
    volumes: storeInstallVolumes.value.split("\n").map((line) => line.trim()).filter(Boolean),
    restart_policy: storeInstallRestart.value,
  };
  const confirmed = window.confirm(`Install ${payload.image} as Docker container "${payload.name}"?`);
  if (!confirmed) return;

  storeInstallSubmit.disabled = true;
  storeInstallSubmit.textContent = "Installing...";
  try {
    const response = await fetch("/api/store/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      window.alert(result.error || "Could not install Docker app.");
      return;
    }
    await watchStoreInstall(result.job_id, payload);
  } finally {
    storeInstallSubmit.disabled = false;
    storeInstallSubmit.textContent = "Install";
  }
}

function setMeter(valueNode, barNode, value) {
  const percent = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
  valueNode.textContent = formatPercent(value);
  barNode.style.width = `${percent}%`;
}

function setMeterVisual(valueNode, barNode, ringNode, value) {
  setMeter(valueNode, barNode, value);
  const percent = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
  ringNode?.style.setProperty("--value", `${percent}%`);
}

function renderGpuList(gpus = []) {
  gpuList.replaceChildren();
  gpus.forEach((gpu) => {
    const row = document.createElement("div");
    row.className = "gpu-row";
    const usage = Number.isFinite(gpu.percent) ? `${gpu.percent.toFixed(1)}%` : "--";
    const memory = gpu.memory_total_label ? ` · ${gpu.memory_used_label} / ${gpu.memory_total_label}` : "";
    const freq = gpu.frequency_mhz ? ` · ${gpu.frequency_mhz} MHz` : "";
    row.textContent = `GPU ${gpu.index ?? ""} · ${gpu.name || "GPU"} · ${usage}${freq}${memory}`;
    gpuList.appendChild(row);
  });
}

async function loadSystem() {
  const response = await fetch("/api/system", { cache: "no-store" });
  const data = await response.json();

  setMeterVisual(cpuValue, cpuBar, cpuRing, data.cpu?.percent);
  setMeterVisual(memoryValue, memoryBar, memoryRing, data.memory?.percent);

  if (data.gpu?.available) {
    setMeterVisual(gpuValue, gpuBar, gpuRing, data.gpu.percent);
    const freq = data.gpu.frequency_mhz ? `${data.gpu.frequency_mhz} MHz` : "no frequency";
    const count = data.gpu.count > 1 ? `${data.gpu.count} GPUs · ` : "";
    gpuDetail.textContent = data.gpu.percent === null ? `${count}${freq} · calculating usage` : `${count}${freq}`;
    renderGpuList(data.gpus || []);
  } else {
    setMeterVisual(gpuValue, gpuBar, gpuRing, null);
    gpuDetail.textContent = "No counter available";
    renderGpuList([]);
  }
}

function formatTime(timestamp) {
  return new Date(timestamp * 1000).toLocaleString("en-US", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function fileIcon(entry) {
  if (entry.type === "directory") return "";
  const extension = entry.name?.includes(".") ? entry.name.split(".").pop().slice(0, 4).toUpperCase() : "";
  const icons = {
    archive: "ZIP",
    audio: "AUD",
    directory: "DIR",
    file: "FILE",
    image: "IMG",
    pdf: "PDF",
    text: "TXT",
    video: "VID",
  };
  return extension || icons[entry.kind] || icons[entry.type] || "FILE";
}

function fileTypeLabel(entry) {
  const labels = {
    archive: "Archive",
    audio: "Audio",
    directory: "Folder",
    file: "File",
    image: "Image",
    pdf: "PDF",
    text: "Text",
    video: "Video",
  };
  return labels[entry.kind] || labels[entry.type] || "File";
}

function statusClass(value) {
  return value === "active" || value?.startsWith("Up") ? "good" : "warn";
}

function renderDisk(disk) {
  const node = document.createElement("article");
  node.className = "row-card";
  node.innerHTML = `
    <div>
      <strong></strong>
      <p></p>
    </div>
    <span></span>
    <div class="meter"><span></span></div>
  `;
  const title = [disk.device, disk.model].filter(Boolean).join(" · ");
  const mounts = disk.mountpoints?.length ? disk.mountpoints.join(", ") : "Not mounted";
  const details = [
    disk.transport ? disk.transport.toUpperCase() : "",
    disk.filesystems?.length ? disk.filesystems.join(", ") : "",
    mounts,
  ].filter(Boolean).join(" · ");

  node.querySelector("strong").textContent = title || disk.device;
  node.querySelector("p").textContent = `${details} · ${disk.used_label} used of ${disk.total_label}`;
  node.querySelector("span").textContent = `${disk.percent.toFixed(1)}%`;
  node.querySelector(".meter span").style.width = `${disk.percent}%`;
  return node;
}

function renderResourceContainer(container) {
  const node = document.createElement("div");
  node.className = "resource-row";
  node.innerHTML = `
    <span></span>
    <span></span>
    <span></span>
    <span></span>
    <span></span>
  `;
  const cells = node.querySelectorAll("span");
  cells[0].textContent = container.name || "--";
  cells[1].textContent = container.status || "--";
  cells[1].classList.add(statusClass(container.status));
  cells[2].textContent = container.cpu || "0%";
  cells[3].textContent = container.memory || "--";
  cells[4].textContent = container.ports?.length ? container.ports.join(", ") : "--";
  return node;
}

function renderResourceProcess(process) {
  const node = document.createElement("div");
  node.className = "resource-row";
  node.innerHTML = `
    <span></span>
    <span></span>
    <span></span>
    <span></span>
    <span></span>
  `;
  const cells = node.querySelectorAll("span");
  cells[0].textContent = `${process.cpu_percent.toFixed(1)}%`;
  cells[1].textContent = `${process.memory_percent.toFixed(1)}%`;
  cells[2].textContent = process.pid;
  cells[3].textContent = process.user;
  cells[4].textContent = process.command;
  return node;
}

function sortedResourceProcesses() {
  const { key, direction } = state.processSort;
  const multiplier = direction === "asc" ? 1 : -1;
  return [...state.resourceProcesses].sort((left, right) => {
    const leftValue = Number(left?.[key]) || 0;
    const rightValue = Number(right?.[key]) || 0;
    if (leftValue !== rightValue) return (leftValue - rightValue) * multiplier;
    return String(left.command || "").localeCompare(String(right.command || ""));
  });
}

function renderResourceProcesses() {
  const { key, direction } = state.processSort;
  processSortButtons.forEach((button) => {
    const active = button.dataset.processSort === key;
    button.classList.toggle("active", active);
    button.setAttribute("aria-sort", active ? (direction === "desc" ? "descending" : "ascending") : "none");
    const label = button.dataset.processSort === "memory_percent" ? "MEM" : "CPU";
    button.textContent = active ? `${label} ${direction === "desc" ? "↓" : "↑"}` : label;
  });
  resourceProcesses.replaceChildren(...sortedResourceProcesses().map(renderResourceProcess));
}

async function loadStatus() {
  const response = await fetch("/api/status", { cache: "no-store" });
  const data = await response.json();

  disksNode.replaceChildren(...(data.disks || []).map(renderDisk));
}

async function uploadAppIcon(app, input) {
  const file = input.files?.[0];
  input.value = "";
  if (!file || !app.icon_key) return;
  try {
    const content = await readFileAsDataUrl(file);
    const response = await fetch("/api/apps/icon", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ app_key: app.icon_key, filename: file.name, content }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error || "Could not save icon");
    }
    await load();
  } catch (error) {
    window.alert(error.message);
  }
}

async function loadResources() {
  if (!resourcesPanel.open) return;

  const response = await fetch("/api/resources", { cache: "no-store" });
  const data = await response.json();

  resourceHost.textContent = data.hostname || "--";
  resourceUptime.textContent = data.uptime || "--";
  resourceCpu.textContent = [
    `user ${formatPercent(data.cpu?.user)}`,
    `system ${formatPercent(data.cpu?.system)}`,
    `iowait ${formatPercent(data.cpu?.iowait)}`,
  ].join(" · ");
  resourceMemory.textContent = `${data.memory?.used_label || "--"} / ${data.memory?.total_label || "--"}`;
  resourceTasks.textContent = `Tasks ${data.tasks?.total ?? "--"} (${data.tasks?.threads ?? "--"} threads), ${data.tasks?.running ?? "--"} running, ${data.tasks?.sleeping ?? "--"} sleeping, ${data.tasks?.other ?? "--"} other`;
  resourceContainers.replaceChildren(...(data.containers || []).map(renderResourceContainer));
  state.resourceProcesses = data.processes || [];
  renderResourceProcesses();
}

function renderFileEntry(entry) {
  const node = document.createElement("div");
  node.className = `file-entry ${entry.type}`;
  node.innerHTML = `
    <button class="file-name" type="button">
      <span class="file-thumb"><span class="file-icon"></span></span>
      <span class="file-text">
        <span class="file-label"></span>
        <span class="file-subtitle"></span>
      </span>
    </button>
    <span class="file-type"></span>
    <span class="file-size"></span>
    <span class="file-modified"></span>
    <span class="file-actions">
      <button class="file-open" type="button"></button>
      <button class="file-more" type="button" aria-label="More actions">•••</button>
    </span>
  `;
  node.querySelector(".file-icon").textContent = fileIcon(entry);
  node.querySelector(".file-label").textContent = entry.name;
  node.querySelector(".file-type").textContent = fileTypeLabel(entry);
  node.querySelector(".file-size").textContent = entry.size || "";
  node.querySelector(".file-modified").textContent = formatTime(entry.modified);
  node.querySelector(".file-subtitle").textContent = entry.type === "directory"
    ? "Folder"
    : [fileTypeLabel(entry), entry.size].filter(Boolean).join(" · ");
  node.querySelector(".file-open").textContent = entry.type === "directory" ? "Open" : "View";
  if (state.fileClipboard?.path === entry.path) {
    node.classList.add("copied");
  }

  const openEntry = () => {
    if (entry.type === "directory") {
      loadFiles(entry.path);
    } else {
      window.open(`/api/file/open?path=${encodeURIComponent(entry.path)}`, "_blank", "noreferrer");
    }
  };
  node.querySelector(".file-name").addEventListener("click", openEntry);
  node.querySelector(".file-open").addEventListener("click", openEntry);
  node.querySelector(".file-more").addEventListener("click", (event) => openFileContextMenu(entry, node, event.clientX, event.clientY));
  node.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    openFileContextMenu(entry, node, event.clientX, event.clientY);
  });
  let holdTimer = null;
  let held = false;
  let holdStart = null;
  node.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse") return;
    held = false;
    holdStart = { x: event.clientX, y: event.clientY };
    holdTimer = window.setTimeout(() => {
      held = true;
      openFileContextMenu(entry, node, event.clientX, event.clientY);
    }, 550);
  });
  ["pointerup", "pointercancel"].forEach((name) => node.addEventListener(name, () => window.clearTimeout(holdTimer)));
  node.addEventListener("pointermove", (event) => {
    if (holdStart && Math.hypot(event.clientX - holdStart.x, event.clientY - holdStart.y) > 10) window.clearTimeout(holdTimer);
  });
  node.querySelector(".file-name").addEventListener("click", (event) => {
    if (held) {
      event.preventDefault();
      event.stopImmediatePropagation();
      held = false;
    }
  }, true);
  return node;
}

function closeFileContextMenu() {
  fileContextMenu.hidden = true;
  document.querySelectorAll(".file-entry.selected").forEach((node) => node.classList.remove("selected"));
  state.selectedFile = null;
}

function openFileContextMenu(entry, node, x = 0, y = 0) {
  closeFileContextMenu();
  state.selectedFile = entry;
  node.classList.add("selected");
  fileContextName.textContent = entry.name;
  fileContextKind.textContent = entry.type === "directory" ? "Folder" : [fileTypeLabel(entry), entry.size].filter(Boolean).join(" · ");
  fileContextActions.forEach((button) => {
    const action = button.dataset.fileContextAction;
    button.disabled = !state.features.file_operations && ["copy", "rename", "delete"].includes(action);
  });
  fileContextMenu.hidden = false;
  const width = 230;
  const bounds = node.getBoundingClientRect();
  fileContextMenu.style.left = `${Math.max(8, Math.min(window.innerWidth - width - 8, x || bounds.right - width))}px`;
  fileContextMenu.style.top = `${Math.max(8, Math.min(window.innerHeight - 310, y || bounds.bottom))}px`;
}

async function runFileContextAction(action) {
  const entry = state.selectedFile;
  if (!entry) return;
  closeFileContextMenu();
  if (action === "open") {
    if (entry.type === "directory") loadFiles(entry.path);
    else window.open(`/api/file/open?path=${encodeURIComponent(entry.path)}`, "_blank", "noreferrer");
  } else if (action === "download") {
    window.location.href = `/api/file/download?path=${encodeURIComponent(entry.path)}`;
  } else if (action === "copy") await copyFileEntry(entry);
  else if (action === "rename") await renameFileEntry(entry);
  else if (action === "delete") await deleteFileEntry(entry);
}

function updateFileControls() {
  const operationsEnabled = Boolean(state.features.file_operations);
  const hasFolder = Boolean(state.filePath);
  const canOperate = hasFolder && operationsEnabled;
  fileNewFolder.disabled = !canOperate;
  fileUpload.disabled = !canOperate;
  filePaste.disabled = !canOperate || !state.fileClipboard;
  filePaste.textContent = state.fileClipboard ? `Paste ${state.fileClipboard.name}` : "Paste";
  if (!operationsEnabled) {
    fileDropStatus.textContent = "File operations are disabled";
  } else if (!hasFolder) {
    fileDropStatus.textContent = "Open a location to upload or create files";
  } else {
    fileDropStatus.textContent = "Drop files here to upload";
  }
  fileDropStatus.classList.toggle("disabled", !operationsEnabled);
}

function fileRootLabel(root) {
  if (root === "/") return "Root";
  const parts = root.split("/").filter(Boolean);
  return parts.at(-1) || root;
}

function currentFolderName(path) {
  if (!path) return "Locations";
  if (path === "/") return "Root";
  const parts = path.split("/").filter(Boolean);
  return parts.at(-1) || path;
}

async function runFileAction(payload) {
  const result = await postFileAction(payload);
  await loadFiles(state.filePath);
  return result;
}

async function postFileAction(payload) {
  const response = await fetch("/api/files/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) {
    throw new Error(result.error || "File operation failed");
  }
  return result;
}

async function mountDriveEntry(entry) {
  if (!state.features.file_operations || state.features.file_mounts === false) return;
  try {
    const result = await postFileAction({ action: "mount_readonly", device: entry.path });
    await loadFiles(result.path || state.filePath);
  } catch (error) {
    window.alert(error.message);
    await loadFiles(state.filePath);
  }
}

async function unmountDriveEntry(entry) {
  if (!state.features.file_operations || state.features.file_mounts === false) return;
  const confirmed = window.confirm(`Unmount ${entry.label || entry.name || entry.path}?`);
  if (!confirmed) return;
  try {
    await postFileAction({ action: "unmount", device: entry.path });
    await loadFiles("");
  } catch (error) {
    window.alert(error.message);
    await loadFiles(state.filePath);
  }
}

async function createFolder() {
  if (!state.filePath || !state.features.file_operations) return;
  const name = window.prompt("New folder name");
  if (!name) return;
  try {
    await runFileAction({ action: "mkdir", parent: state.filePath, name });
  } catch (error) {
    window.alert(error.message);
  }
}

async function copyFileEntry(entry) {
  if (!state.features.file_operations) return;
  state.fileClipboard = {
    path: entry.path,
    name: entry.name,
    type: entry.type,
  };
  sessionStorage.setItem("homestart-file-clipboard", JSON.stringify(state.fileClipboard));
  updateFileControls();
  document.querySelectorAll(".file-entry.copied").forEach((item) => item.classList.remove("copied"));
  const matchingEntry = [...document.querySelectorAll(".file-entry")].find((item) => item.querySelector(".file-label")?.textContent === entry.name);
  matchingEntry?.classList.add("copied");
  fileDropStatus.textContent = `Copied ${entry.name}. Open the destination folder and press Paste.`;
  toast(`${entry.name} copied`, "success");
}

async function pasteFileEntry() {
  if (!state.filePath || !state.fileClipboard || !state.features.file_operations) return;
  const destination = state.filePath;
  const clipboard = { ...state.fileClipboard };
  filePaste.disabled = true;
  filePaste.textContent = `Pasting ${clipboard.name}…`;
  try {
    const result = await postFileAction({ action: "copy", source: clipboard.path, destination });
    await loadFiles(destination);
    toast(result.message || `${clipboard.name} pasted`, "success");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    updateFileControls();
  }
}

async function deleteFileEntry(entry) {
  if (!state.features.file_operations) return;
  const confirmed = window.confirm(`Move "${entry.name}" to HomeStart trash?`);
  if (!confirmed) return;
  try {
    await runFileAction({ action: "delete", path: entry.path });
  } catch (error) {
    window.alert(error.message);
  }
}

async function renameFileEntry(entry) {
  const name = window.prompt("New name", entry.name);
  if (!name || name === entry.name) return;
  try {
    await runFileAction({ action: "rename", path: entry.path, name });
    toast(`Renamed to ${name}`, "success");
  } catch (error) { toast(error.message, "error"); }
}

async function loadGeneralSettings() {
  const response = await fetch("/api/settings/general", { cache: "no-store" });
  const data = await response.json();
  document.querySelector("#setting-title").value = data.dashboard?.title || "HomeStart";
  document.querySelector("#setting-subtitle").value = data.dashboard?.subtitle || "Dashboard";
  document.querySelector("#setting-accent").value = data.appearance?.accent || "#38bdf8";
  document.querySelector("#setting-theme").value = data.appearance?.theme || "dark";
  document.querySelector("#setting-density").value = data.appearance?.density || "comfortable";
  document.querySelector("#setting-cpu-alert").value = data.alerts?.cpu_percent ?? 90;
  document.querySelector("#setting-memory-alert").value = data.alerts?.memory_percent ?? 90;
  document.querySelector("#setting-disk-alert").value = data.alerts?.disk_percent ?? 90;
  document.querySelector("#setting-temperature-alert").value = data.alerts?.temperature_c ?? 85;
  document.documentElement.style.setProperty("--accent", data.appearance?.accent || "#38bdf8");
  document.documentElement.dataset.theme = data.appearance?.theme || "dark";
  document.body.dataset.density = data.appearance?.density || "comfortable";
}

async function saveGeneralSettings(event) {
  event.preventDefault();
  const payload = {
    dashboard: { title: document.querySelector("#setting-title").value.trim(), subtitle: document.querySelector("#setting-subtitle").value.trim() },
    appearance: { accent: document.querySelector("#setting-accent").value, theme: document.querySelector("#setting-theme").value, density: document.querySelector("#setting-density").value },
    alerts: { cpu_percent: Number(document.querySelector("#setting-cpu-alert").value), memory_percent: Number(document.querySelector("#setting-memory-alert").value), disk_percent: Number(document.querySelector("#setting-disk-alert").value), temperature_c: Number(document.querySelector("#setting-temperature-alert").value) },
  };
  const response = await fetch("/api/settings/general", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const data = await response.json();
  if (!response.ok || !data.ok) return toast(data.error || "Could not save settings", "error");
  toast("Settings saved", "success");
  await Promise.all([loadGeneralSettings(), loadSystem(), loadOverview()]);
}

async function createBackupFromUi() {
  backupCreate.disabled = true;
  try {
    const response = await fetch("/api/backups/download", { cache: "no-store" });
    if (!response.ok) throw new Error("Backup failed");
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename=([^;]+)/i)?.[1]?.replace(/["']/g, "") || "homestart-backup.tar.gz";
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast(`Backup ${filename} ready to save`, "success");
  } catch (error) { toast(error.message, "error"); }
  finally { backupCreate.disabled = false; }
}

async function loadTrash() {
  const response = await fetch("/api/trash", { cache: "no-store" });
  const data = await response.json();
  trashList.replaceChildren();
  if (!data.items?.length) { trashList.innerHTML = '<div class="empty-state">Trash is empty.</div>'; return; }
  data.items.forEach((item) => {
    const row = document.createElement("div"); row.className = "row-card";
    row.innerHTML = `<div><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.original)} · ${new Date(item.deleted_at * 1000).toLocaleString()}</p></div><button type="button">Restore</button>`;
    row.querySelector("button").addEventListener("click", async () => {
      const response = await fetch("/api/trash/restore", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({key:item.key}) });
      const result = await response.json();
      if (!response.ok || !result.ok) return toast(result.error || "Restore failed", "error");
      toast(`Restored to ${result.path}`, "success"); await loadTrash();
    });
    trashList.appendChild(row);
  });
}

function renderRoots() {
  const roots = state.fileRootEntries.length
    ? state.fileRootEntries
    : state.fileRoots.map((root) => ({ path: root, name: fileRootLabel(root), kind: "folder" }));
  const activeRoot = roots
    .map((rootEntry) => rootEntry.path)
    .filter((root) => rootContainsPath(root, state.filePath))
    .sort((a, b) => b.length - a.length)[0];
  const locationNodes = roots.map((rootEntry) => {
    const root = rootEntry.path;
    const wrapper = document.createElement("div");
    wrapper.className = "root-tree";
    const node = document.createElement("button");
    node.type = "button";
    node.className = "root-entry";
    node.innerHTML = `
      <span class="root-icon"></span>
      <span>
        <strong></strong>
        <small></small>
      </span>
    `;
    const icon = node.querySelector(".root-icon");
    icon.classList.add(rootEntry.kind || "folder");
    node.querySelector("strong").textContent = rootEntry.name || fileRootLabel(root);
    const details = [rootEntry.size, rootEntry.filesystem, rootEntry.device].filter(Boolean).join(" · ");
    node.querySelector("small").textContent = details || root;
    node.title = root;
    if (root === activeRoot) {
      node.classList.add("active");
      wrapper.classList.add("active");
    }
    node.addEventListener("click", () => loadFiles(root));
    wrapper.appendChild(node);
    if (root === activeRoot) renderCurrentPathBranch(wrapper, root);
    return wrapper;
  });

  const driveNodes = state.fileDriveEntries.length
    ? [
        sectionLabel("Physical disks"),
        ...state.fileDriveEntries.map(renderDriveEntry),
      ]
    : [];
  fileRoots.replaceChildren(sectionLabel("Locations"), ...locationNodes, ...driveNodes);
}

function sectionLabel(label) {
  const node = document.createElement("div");
  node.className = "root-section-label";
  node.textContent = label;
  return node;
}

function renderDriveEntry(entry) {
  const wrapper = document.createElement("div");
  wrapper.className = "drive-tree";
  wrapper.appendChild(renderDriveNode(entry, true));
  (entry.children || []).forEach((child) => renderDriveChildren(wrapper, child));
  return wrapper;
}

function renderDriveChildren(parent, entry) {
  parent.appendChild(renderDriveNode(entry, false));
  (entry.children || []).forEach((child) => renderDriveChildren(parent, child));
}

function firstAllowedMount(entry) {
  return (entry.mountpoints || []).find((mount) => mount.allowed && mount.path);
}

function renderDriveNode(entry, isDisk) {
  const mount = firstAllowedMount(entry);
  const node = document.createElement("div");
  node.className = `drive-entry ${isDisk ? "disk" : "partition"}`;
  node.style.setProperty("--depth", entry.depth || 0);
  node.classList.toggle("unavailable", !mount && !entry.can_mount);
  const title = entry.label || entry.model || entry.name || entry.path;
  const details = [
    entry.size,
    entry.filesystem,
    entry.path,
    mount?.path || "not mounted",
  ].filter(Boolean).join(" · ");
  node.innerHTML = `
    <span class="drive-icon ${entry.kind || "disk"}"></span>
    <span>
      <strong></strong>
      <small></small>
    </span>
    <span class="drive-actions"></span>
  `;
  node.querySelector("strong").textContent = title;
  node.querySelector("small").textContent = details;
  node.title = details;
  if (mount && rootContainsPath(mount.path, state.filePath)) {
    node.classList.add("active");
  }
  if (mount) {
    node.tabIndex = 0;
    node.addEventListener("click", () => loadFiles(mount.path));
    node.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        loadFiles(mount.path);
      }
    });
  }

  const actions = node.querySelector(".drive-actions");
  const mountingEnabled = state.features.file_operations && state.features.file_mounts !== false;
  if (entry.can_mount && mountingEnabled) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "drive-action";
    button.textContent = "Mount RO";
    button.title = "Mount read-only";
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      mountDriveEntry(entry).catch(console.error);
    });
    actions.appendChild(button);
  }
  if (entry.can_unmount && mountingEnabled) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "drive-action";
    button.textContent = "Unmount";
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      unmountDriveEntry(entry).catch(console.error);
    });
    actions.appendChild(button);
  }
  return node;
}

function rootContainsPath(root, path) {
  if (!path) return false;
  if (root === "/") return path === "/" || path.startsWith("/");
  return path === root || path.startsWith(`${root}/`);
}

function renderCurrentPathBranch(wrapper, root) {
  if (!rootContainsPath(root, state.filePath) || state.filePath === root || !state.filePath) return;
  const rootParts = root.split("/").filter(Boolean);
  const pathParts = state.filePath.split("/").filter(Boolean);
  const branchParts = pathParts.slice(root === "/" ? 0 : rootParts.length);
  if (!branchParts.length) return;

  const branch = document.createElement("div");
  branch.className = "root-branch";
  let current = root === "/" ? "" : root;
  branchParts.forEach((part, index) => {
    current = root === "/" ? `${current}/${part}` : `${current}/${part}`;
    const child = document.createElement("button");
    child.type = "button";
    child.className = "root-child";
    child.style.setProperty("--depth", index);
    child.innerHTML = "<span></span><strong></strong>";
    child.querySelector("strong").textContent = part;
    child.classList.toggle("current", current === state.filePath);
    const target = current;
    child.addEventListener("click", () => loadFiles(target));
    branch.appendChild(child);
  });
  wrapper.appendChild(branch);
}

function renderNetworkInterface(item) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = "row-card network-card";
  node.innerHTML = `
    <div>
      <strong></strong>
      <p></p>
    </div>
    <span class="pill"></span>
  `;
  const ipv4 = item.ipv4?.length ? item.ipv4.map((address) => address.cidr).join(", ") : "No IPv4 address";
  const speed = interfaceSpeedLabel(item);
  node.querySelector("strong").textContent = item.label || item.name;
  node.querySelector("p").textContent = [
    item.label ? item.name : "",
    speed,
    ipv4,
    `gateway ${item.gateway || "--"}`,
    `DNS ${(item.dns || []).join(", ") || "--"}`,
  ].filter(Boolean).join(" · ");
  const pill = node.querySelector(".pill");
  pill.textContent = `${item.state || "unknown"} · ${item.mode || "unknown"}`;
  pill.classList.add(item.state === "UP" ? "good" : "warn");
  if (state.selectedNetwork?.name === item.name) {
    node.classList.add("active");
  }
  node.addEventListener("click", () => selectNetworkInterface(item));
  return node;
}

function selectNetworkInterface(item) {
  state.selectedNetwork = item;
  networkInterface.value = item.name;
  networkMode.value = item.mode === "dhcp" ? "dhcp" : "static";
  networkAddress.value = item.ipv4?.[0]?.cidr || "";
  networkGateway.value = item.gateway || "";
  networkDns.value = (item.dns || []).join(", ");
  const hardware = item.label ? `${item.label}${interfaceSpeedLabel(item) ? ` · ${interfaceSpeedLabel(item)}` : ""} · ` : "";
  networkManagedBy.textContent = `${hardware}Managed by ${item.managed_by || "unknown"}${item.netplan_file ? ` · ${item.netplan_file}` : ""}`;
  renderNetworkInterfaces();
}

function renderNetworkInterfaces() {
  networkInterfaces.replaceChildren(...state.networkInterfaces.map(renderNetworkInterface));
}

async function loadNetworkSettings() {
  const response = await fetch("/api/settings/network", { cache: "no-store" });
  const data = await response.json();
  state.networkInterfaces = data.interfaces || [];
  renderMonitorInterfaces(data.monitor || {});

  if (!state.selectedNetwork && state.networkInterfaces.length) {
    selectNetworkInterface(state.networkInterfaces.find((item) => item.gateway) || state.networkInterfaces[0]);
  } else {
    const updated = state.networkInterfaces.find((item) => item.name === state.selectedNetwork?.name);
    if (updated) selectNetworkInterface(updated);
    else renderNetworkInterfaces();
  }
}

function interfaceSpeedLabel(item) {
  if (!item.speed_mbps) return "";
  return item.speed_mbps >= 1000 ? `${item.speed_mbps / 1000} Gbps` : `${item.speed_mbps} Mbps`;
}

function renderMonitorInterfaces(monitor) {
  if (!monitorInterface) return;
  const items = monitor.interfaces || [];
  const automatic = document.createElement("option");
  automatic.value = "auto";
  automatic.textContent = `Automatic${monitor.active ? ` · ${monitor.active}` : ""}`;
  const options = items.map((item) => {
    const option = document.createElement("option");
    option.value = item.name;
    const connection = item.carrier || String(item.state).toLowerCase() === "up" ? "connected" : "disconnected";
    option.textContent = [item.label, item.name, interfaceSpeedLabel(item), connection].filter(Boolean).join(" · ");
    return option;
  });
  monitorInterface.replaceChildren(automatic, ...options);
  monitorInterface.value = monitor.selection_missing ? "auto" : (monitor.selected || "auto");
  const active = items.find((item) => item.name === monitor.active);
  if (monitor.selection_missing) {
    monitorInterfaceDetail.textContent = `The saved interface is no longer present. Using ${monitor.active || "automatic detection"}.`;
  } else if (active) {
    const address = active.ipv4?.[0] ? ` · ${active.ipv4[0]}` : "";
    monitorInterfaceDetail.textContent = `${active.label} · ${active.name}${address}`;
  } else {
    monitorInterfaceDetail.textContent = "No physical network interface detected.";
  }
}

async function changeMonitorInterface() {
  monitorInterface.disabled = true;
  try {
    const response = await fetch("/api/network/monitor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interface: monitorInterface.value }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || "Could not change monitored interface");
    await loadNetworkSettings();
    await loadLiveNetwork();
    await loadHistory();
  } catch (error) {
    monitorInterfaceDetail.textContent = error.message;
  } finally {
    monitorInterface.disabled = false;
  }
}

async function applyNetworkSettings(event) {
  event.preventDefault();
  if (!state.selectedNetwork) return;

  const confirmText = `APPLY ${networkInterface.value}`;
  const entered = window.prompt(`Changing IP settings can disconnect this host. Type "${confirmText}" to continue.`);
  if (entered !== confirmText) return;

  const response = await fetch("/api/settings/network", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      interface: networkInterface.value,
      mode: networkMode.value,
      address: networkAddress.value.trim(),
      gateway: networkGateway.value.trim(),
      dns: networkDns.value.split(",").map((item) => item.trim()).filter(Boolean),
    }),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) {
    window.alert(result.error || "Could not apply network settings");
    return;
  }

  window.alert(`Network settings applied. Backup: ${result.backup || "none"}`);
  await loadNetworkSettings();
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(reader.result));
    reader.addEventListener("error", reject);
    reader.readAsDataURL(file);
  });
}

async function applyUpdate(event) {
  event.preventDefault();
  const file = updateFile.files?.[0];
  if (!file) {
    updateStatus.textContent = "Select a .tar.gz update package first.";
    return;
  }
  const confirmed = window.confirm(`Apply update package "${file.name}"? HomeStart will restart after the update.`);
  if (!confirmed) return;

  updateApply.disabled = true;
  updateStatus.textContent = "Uploading update package...";
  try {
    const content = await readFileAsDataUrl(file);
    const response = await fetch("/api/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: file.name, content }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error || "Could not apply update");
    }
    updateStatus.textContent = `Update applied. ${result.changed?.length || 0} files changed. Backup: ${result.backup}. Restarting...`;
    waitForHomeStartRestart(updateStatus);
  } catch (error) {
    if (error instanceof TypeError || /failed to fetch/i.test(error.message || "")) {
      updateStatus.textContent = "Connection interrupted while HomeStart restarted. Waiting for the server…";
      waitForHomeStartRestart(updateStatus);
      return;
    }
    updateStatus.textContent = error.message;
    updateApply.disabled = false;
  }
}

function renderGithubUpdateStatus(data) {
  state.githubUpdate = data;
  if (!githubUpdateStatus || !githubUpdateApply) return;
  githubUpdateApply.disabled = !data?.update_available || !data?.download_url;

  if (!data?.ok) {
    githubUpdateStatus.textContent = data?.error || "Could not check GitHub releases.";
    return;
  }
  const current = data.current_version || "unknown";
  const latest = data.latest_version || "none";
  githubUpdateStatus.textContent = `${data.message || "GitHub checked."} Current: ${current}. Latest: ${latest}.`;
}

async function checkGithubUpdate() {
  if (!githubUpdateCheck) return;
  githubUpdateCheck.disabled = true;
  githubUpdateStatus.textContent = "Checking GitHub releases...";
  try {
    const response = await fetch("/api/update/check", { cache: "no-store" });
    const data = await response.json();
    renderGithubUpdateStatus(data);
  } catch (error) {
    renderGithubUpdateStatus({ ok: false, error: error.message });
  } finally {
    githubUpdateCheck.disabled = false;
  }
}

async function applyGithubUpdate() {
  const latest = state.githubUpdate?.latest_version || "latest";
  const confirmed = window.confirm(`Install HomeStart ${latest} from GitHub? HomeStart will restart after the update.`);
  if (!confirmed) return;

  githubUpdateApply.disabled = true;
  githubUpdateCheck.disabled = true;
  githubUpdateStatus.textContent = "Downloading and applying GitHub update...";
  try {
    const response = await fetch("/api/update/github", { method: "POST" });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error || "Could not apply GitHub update");
    }
    if (!result.restart) {
      renderGithubUpdateStatus(result);
      return;
    }
    githubUpdateStatus.textContent = `Update applied from GitHub. ${result.changed?.length || 0} files changed. Restarting...`;
    waitForHomeStartRestart(githubUpdateStatus);
  } catch (error) {
    if (error instanceof TypeError || /failed to fetch/i.test(error.message || "")) {
      githubUpdateStatus.textContent = "Connection interrupted while HomeStart restarted. Waiting for the server…";
      waitForHomeStartRestart(githubUpdateStatus);
      return;
    }
    githubUpdateStatus.textContent = error.message;
    githubUpdateApply.disabled = !state.githubUpdate?.update_available;
  } finally {
    githubUpdateCheck.disabled = false;
  }
}

async function waitForHomeStartRestart(statusNode) {
  const deadline = Date.now() + 90000;
  await new Promise((resolve) => setTimeout(resolve, 2500));
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`/health?restart=${Date.now()}`, { cache: "no-store" });
      if (response.ok) {
        statusNode.textContent = "HomeStart is back online. Reloading…";
        window.setTimeout(() => window.location.reload(), 400);
        return;
      }
    } catch { /* A temporary connection failure is expected during restart. */ }
    statusNode.textContent = "HomeStart is restarting…";
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  statusNode.textContent = "HomeStart did not return automatically. Reload this page to check the service.";
}

async function loadFiles(path = "") {
  const response = await fetch(`/api/files?path=${encodeURIComponent(path)}`, { cache: "no-store" });
  const data = await response.json();
  if (!response.ok || data.error) {
    window.alert(data.error || "Could not open the folder");
    return;
  }

  state.filePath = data.path || "";
  state.fileParent = data.parent || "";
  state.fileRoots = data.roots || [];
  state.fileRootEntries = data.root_entries || state.fileRoots.map((root) => ({ path: root }));
  state.fileDriveEntries = data.drive_entries || [];
  filePathNode.value = state.filePath || "";
  filePathNode.placeholder = "Available roots";
  fileLocationName.textContent = currentFolderName(state.filePath);
  const entries = data.entries || [];
  const folderCount = entries.filter((entry) => entry.type === "directory").length;
  const fileOnlyCount = entries.length - folderCount;
  fileCount.textContent = state.filePath
    ? `${entries.length} item${entries.length === 1 ? "" : "s"} · ${folderCount} folder${folderCount === 1 ? "" : "s"} · ${fileOnlyCount} file${fileOnlyCount === 1 ? "" : "s"}`
    : `${entries.length} location${entries.length === 1 ? "" : "s"}`;
  fileUp.disabled = !state.fileParent && !state.filePath;
  updateFileControls();
  renderRoots();
  filesNode.replaceChildren(...entries.map(renderFileEntry));
  if (sambaUseCurrent) sambaUseCurrent.disabled = !state.filePath;
}

function sambaAccessLabel(share) {
  if (share.guest_ok) return "Guest access";
  if (share.valid_users?.length) return share.valid_users.join(", ");
  return "No explicit users";
}

function renderSambaShare(share) {
  const node = document.createElement("article");
  node.className = `samba-share-card${share.enabled ? "" : " disabled"}`;
  const heading = document.createElement("div");
  heading.className = "samba-share-heading";
  const text = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = share.name;
  const path = document.createElement("p");
  path.textContent = share.path;
  text.append(title, path);
  const pill = document.createElement("span");
  pill.className = `pill ${share.enabled ? "good" : "warn"}`;
  pill.textContent = share.enabled ? "Shared" : "Disabled";
  heading.append(text, pill);

  const details = document.createElement("div");
  details.className = "samba-share-details";
  [
    ["Access", sambaAccessLabel(share)],
    ["Permissions", share.read_only ? "Read only" : "Read and write"],
    ["Discovery", share.browseable ? "Visible" : "Hidden"],
    ["Managed by", share.managed ? "HomeStart" : "Existing Samba config"],
  ].forEach(([label, value]) => {
    const item = document.createElement("span");
    const labelNode = document.createElement("small");
    labelNode.textContent = label;
    const valueNode = document.createElement("b");
    valueNode.textContent = value;
    item.append(labelNode, valueNode);
    details.appendChild(item);
  });

  const actions = document.createElement("div");
  actions.className = "samba-share-actions";
  if (share.managed) {
    const edit = document.createElement("button");
    edit.type = "button";
    edit.textContent = "Edit share";
    edit.addEventListener("click", () => editSambaShare(share));
    actions.appendChild(edit);
  }
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.textContent = share.enabled ? "Stop sharing" : "Share again";
  toggle.addEventListener("click", () => changeSambaShare(share.enabled ? "disable" : "enable", share));
  actions.appendChild(toggle);
  if (share.managed) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Delete share";
    remove.addEventListener("click", () => changeSambaShare("delete", share));
    actions.appendChild(remove);
  }
  node.append(heading, details, actions);
  return node;
}

async function loadSambaShares() {
  if (!sambaShares) return;
  sambaStatus.textContent = "Checking Samba…";
  try {
    const response = await fetch("/api/samba/shares", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Could not read Samba shares");
    if (!data.available) {
      sambaStatus.textContent = data.message || "Samba is not available.";
      sambaShares.innerHTML = '<div class="empty-state">Install and configure Samba to manage network shares here.</div>';
      sambaShareForm.hidden = true;
      return;
    }
    sambaShareForm.hidden = false;
    sambaStatus.textContent = `${data.shares.length} shared folder${data.shares.length === 1 ? "" : "s"} detected · ${data.users.length} Samba user${data.users.length === 1 ? "" : "s"}. Passwords are never exposed.`;
    sambaShares.replaceChildren(...(data.shares.length
      ? data.shares.map(renderSambaShare)
      : [Object.assign(document.createElement("div"), { className: "empty-state", textContent: "No Samba shares detected." })]));
    sambaUserList.replaceChildren(...data.users.map((user) => {
      const option = document.createElement("option");
      option.value = user.name;
      option.label = user.description || user.name;
      return option;
    }));
  } catch (error) {
    sambaStatus.textContent = error.message;
    sambaShares.replaceChildren();
  }
}

async function postSambaAction(payload) {
  const response = await fetch("/api/samba/shares", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || "Samba operation failed");
  await loadSambaShares();
  return result;
}

async function changeSambaShare(action, share) {
  const wording = action === "delete" ? "delete this HomeStart share" : action === "disable" ? "stop sharing this folder" : "share this folder again";
  if (!window.confirm(`${wording}: ${share.name}? The files themselves will not be deleted.`)) return;
  try {
    await postSambaAction({ action, name: share.name });
  } catch (error) {
    window.alert(error.message);
  }
}

async function createSambaShare(event) {
  event.preventDefault();
  sambaShareSubmit.disabled = true;
  const wasEditing = Boolean(state.editingSambaShare);
  try {
    await postSambaAction({
      action: state.editingSambaShare ? "update" : "create",
      name: sambaShareName.value.trim(),
      path: sambaSharePath.value.trim(),
      valid_users: sambaShareUsers.value,
      read_only: !sambaShareWritable.checked,
      guest_ok: sambaShareGuest.checked,
      browseable: sambaShareBrowseable.checked,
      force_user: sambaForceUser.value.trim(),
    });
    resetSambaShareForm();
    if (wasEditing) window.alert("Share updated. Reconnect the Windows network share so the new permissions take effect.");
  } catch (error) {
    window.alert(error.message);
  } finally {
    sambaShareSubmit.disabled = false;
  }
}

function updateSambaForceUserVisibility() {
  sambaForceUserField.hidden = !(sambaShareGuest.checked && sambaShareWritable.checked);
}

function resetSambaShareForm() {
  state.editingSambaShare = null;
  sambaShareForm.reset();
  sambaShareName.readOnly = false;
  sambaShareBrowseable.checked = true;
  sambaSharePath.value = state.filePath || "";
  sambaShareSubmit.textContent = "Create share";
  sambaShareCancel.hidden = true;
  updateSambaForceUserVisibility();
}

function editSambaShare(share) {
  state.editingSambaShare = share.name;
  sambaShareName.value = share.name;
  sambaShareName.readOnly = true;
  sambaSharePath.value = share.path || "";
  sambaShareUsers.value = (share.valid_users || []).join(", ");
  sambaShareWritable.checked = !share.read_only;
  sambaShareGuest.checked = Boolean(share.guest_ok);
  sambaShareBrowseable.checked = Boolean(share.browseable);
  sambaForceUser.value = share.force_user || "";
  sambaShareSubmit.textContent = "Save changes";
  sambaShareCancel.hidden = false;
  updateSambaForceUserVisibility();
  sambaShareForm.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function saveSambaCredential() {
  const username = sambaCredentialUser.value.trim();
  const password = sambaCredentialPassword.value;
  if (!username || !password) {
    window.alert("Enter an existing Linux user and a new Samba password.");
    return;
  }
  sambaCredentialSave.disabled = true;
  try {
    await postSambaAction({ action: "set_password", username, password });
    sambaCredentialPassword.value = "";
    window.alert(`Samba credentials updated for ${username}.`);
  } catch (error) {
    window.alert(error.message);
  } finally {
    sambaCredentialSave.disabled = false;
  }
}

function openTypedFilePath(event) {
  event.preventDefault();
  loadFiles(filePathNode.value.trim()).catch(console.error);
}

function handleFilePathKeydown(event) {
  if (event.key !== "Enter") return;
  event.preventDefault();
  loadFiles(filePathNode.value.trim()).catch(console.error);
}

async function uploadDroppedFiles(files) {
  if (!state.filePath || !state.features.file_operations || !files.length) return;
  fileDropStatus.textContent = `Uploading ${files.length} file${files.length === 1 ? "" : "s"}...`;
  try {
    for (const file of files) {
      const content = await readFileAsDataUrl(file);
      await runFileAction({ action: "upload", parent: state.filePath, name: file.name, content });
    }
    fileDropStatus.textContent = "Upload complete";
    await loadFiles(state.filePath);
  } catch (error) {
    fileDropStatus.textContent = error.message;
    window.alert(error.message);
  }
}

function setFileDropActive(active) {
  fileDropStatus.classList.toggle("active", active);
}

async function load() {
  const response = await fetch("/api/apps", { cache: "no-store" });
  const data = await response.json();

  if (hostNode) {
    hostNode.textContent = `http://${data.host}`;
  }
  dashboardTitle.textContent = data.dashboard?.title || "HomeStart";
  dashboardSubtitle.textContent = data.dashboard?.subtitle || "Dashboard";
  document.title = `${dashboardTitle.textContent} dashboard`;
  state.features = data.features || {};
  if (openAppStore) {
    openAppStore.hidden = state.features.docker_app_store === false || state.features.docker_actions === false;
    if (openAppStore.hidden) appStorePanel.hidden = true;
  }
  state.apps = data.apps || [];
  if (state.view === "files") updateFileControls();

  render();
}

function setView(view) {
  state.view = view;
  navItems.forEach((item) => {
    item.classList.toggle("active", item.dataset.view === view);
  });
  viewPanels.forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === view);
  });

  if (view === "apps") load().catch(console.error);
  if (view === "status") loadStatus().catch(console.error);
  if (view === "files") {
    loadFiles(state.filePath).catch(console.error);
    loadSambaShares().catch(console.error);
  }
  if (view === "settings") loadNetworkSettings().catch(console.error);
}

navItems.forEach((item) => {
  item.addEventListener("click", () => setView(item.dataset.view));
});

search.addEventListener("input", () => {
  state.query = search.value;
  render();
});

typeFilterItems.forEach((item) => {
  item.addEventListener("click", () => {
    state.appType = item.dataset.appType;
    typeFilterItems.forEach((button) => {
      button.classList.toggle("active", button === item);
    });
    render();
  });
});

refresh.addEventListener("click", load);
openAppStore.addEventListener("click", () => {
  appStorePanel.hidden = false;
  storeSearch.focus();
  loadStoreTemplates().catch((error) => { storeStatus.textContent = error.message; });
});
closeAppStore.addEventListener("click", () => {
  appStorePanel.hidden = true;
});
storeSearchForm.addEventListener("submit", (event) => searchStore(event).catch((error) => {
  storeStatus.textContent = error.message;
}));
storeInstallForm.addEventListener("submit", (event) => installStoreApp(event).catch((error) => {
  window.alert(error.message);
}));
storeInstallCancel.addEventListener("click", () => storeInstallDialog.close());
refreshStatus.addEventListener("click", loadStatus);
resourcesPanel.addEventListener("toggle", () => loadResources().catch(console.error));
processSortButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const key = button.dataset.processSort;
    if (state.processSort.key === key) {
      state.processSort.direction = state.processSort.direction === "desc" ? "asc" : "desc";
    } else {
      state.processSort = { key, direction: "desc" };
    }
    renderResourceProcesses();
  });
});
refreshNetwork.addEventListener("click", () => loadNetworkSettings().catch(console.error));
networkForm.addEventListener("submit", applyNetworkSettings);
updateForm.addEventListener("submit", applyUpdate);
githubUpdateCheck.addEventListener("click", () => checkGithubUpdate().catch(console.error));
githubUpdateApply.addEventListener("click", () => applyGithubUpdate().catch(console.error));
fileUp.addEventListener("click", () => loadFiles(state.fileParent));
fileHome.addEventListener("click", () => loadFiles(""));
fileNewFolder.addEventListener("click", createFolder);
filePaste.addEventListener("click", pasteFileEntry);
fileUpload.addEventListener("change", () => {
  const selected = [...(fileUpload.files || [])];
  fileUpload.value = "";
  uploadDroppedFiles(selected).catch(console.error);
});
fileContextActions.forEach((button) => button.addEventListener("click", () => {
  runFileContextAction(button.dataset.fileContextAction).catch((error) => toast(error.message, "error"));
}));
document.addEventListener("pointerdown", (event) => {
  if (!fileContextMenu.hidden && !fileContextMenu.contains(event.target) && !event.target.closest(".file-more")) closeFileContextMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeFileContextMenu();
});
restoreIgnoredAlerts.addEventListener("click", () => {
  localStorage.removeItem("homestart-ignored-alerts");
  loadOverview().catch(console.error);
});
filePathForm.addEventListener("submit", openTypedFilePath);
filePathNode.addEventListener("keydown", handleFilePathKeydown);
fileMain.addEventListener("dragover", (event) => {
  if (!state.filePath || !state.features.file_operations) return;
  event.preventDefault();
  setFileDropActive(true);
});
fileMain.addEventListener("dragleave", () => setFileDropActive(false));
fileMain.addEventListener("drop", (event) => {
  if (!state.filePath || !state.features.file_operations) return;
  event.preventDefault();
  setFileDropActive(false);
  uploadDroppedFiles([...event.dataTransfer.files]).catch(console.error);
});
load().catch((error) => {
  if (hostNode) {
    hostNode.textContent = "Could not load apps";
  }
  console.error(error);
});
loadSystem().catch(console.error);
loadStatus().catch(console.error);
loadOverview().catch(console.error);
loadHistory().catch(console.error);
loadLiveNetwork().catch(console.error);
loadNetworkSettings().catch(console.error);
loadGeneralSettings().catch(console.error);
loadTrash().catch(console.error);
loadFiles().catch(console.error);
setInterval(() => loadSystem().catch(console.error), 2000);
setInterval(() => loadStatus().catch(console.error), 15000);
setInterval(() => loadOverview().catch(console.error), 30000);
setInterval(() => loadResources().catch(console.error), 2500);
setInterval(() => loadLiveNetwork().catch(console.error), 2000);
setInterval(() => loadHistory().catch(console.error), 2000);
historyRange?.addEventListener("change", () => loadHistory().catch(console.error));
if (sambaRefresh) sambaRefresh.addEventListener("click", () => loadSambaShares().catch(console.error));
if (sambaShareForm) sambaShareForm.addEventListener("submit", createSambaShare);
if (sambaShareCancel) sambaShareCancel.addEventListener("click", resetSambaShareForm);
if (sambaShareGuest) sambaShareGuest.addEventListener("change", updateSambaForceUserVisibility);
if (sambaShareWritable) sambaShareWritable.addEventListener("change", updateSambaForceUserVisibility);
if (sambaCredentialSave) sambaCredentialSave.addEventListener("click", saveSambaCredential);
if (sambaUseCurrent) sambaUseCurrent.addEventListener("click", () => {
  sambaSharePath.value = state.filePath || "";
  if (!sambaShareName.value && state.filePath) sambaShareName.value = currentFolderName(state.filePath);
});
monitorInterface?.addEventListener("change", () => changeMonitorInterface().catch(console.error));
logsClose?.addEventListener("click", () => logsDialog.close());
generalSettingsForm?.addEventListener("submit", saveGeneralSettings);
backupCreate?.addEventListener("click", createBackupFromUi);
