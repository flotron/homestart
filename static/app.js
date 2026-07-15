const state = {
  apps: [],
  query: "",
  appType: "all",
  filePath: "",
  fileParent: "",
  fileRoots: [],
  fileRootEntries: [],
  fileDriveEntries: [],
  fileClipboard: null,
  fileView: "grid",
  features: { file_operations: true },
  view: "status",
  networkInterfaces: [],
  selectedNetwork: null,
  githubUpdate: null,
  resourceProcesses: [],
  processSort: { key: "cpu_percent", direction: "desc" },
  storeResults: [],
  selectedStoreApp: null,
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
const fileViewGrid = document.querySelector("#file-view-grid");
const fileViewList = document.querySelector("#file-view-list");
const refreshNetwork = document.querySelector("#refresh-network");
const networkInterfaces = document.querySelector("#network-interfaces");
const networkForm = document.querySelector("#network-form");
const networkInterface = document.querySelector("#network-interface");
const networkMode = document.querySelector("#network-mode");
const networkAddress = document.querySelector("#network-address");
const networkGateway = document.querySelector("#network-gateway");
const networkDns = document.querySelector("#network-dns");
const networkManagedBy = document.querySelector("#network-managed-by");
const updateForm = document.querySelector("#update-form");
const updateFile = document.querySelector("#update-file");
const updateStatus = document.querySelector("#update-status");
const updateApply = document.querySelector("#update-apply");
const githubUpdateStatus = document.querySelector("#github-update-status");
const githubUpdateCheck = document.querySelector("#github-update-check");
const githubUpdateApply = document.querySelector("#github-update-apply");

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
  state.apps.filter(matches).forEach((app) => {
    const node = template.content.cloneNode(true);
    const card = node.querySelector(".card");
    const icon = node.querySelector(".icon");
    const iconImage = node.querySelector(".icon img");
    const iconUpload = node.querySelector(".icon-upload");
    const iconUploadInput = node.querySelector(".icon-upload input");
    const title = node.querySelector("h2");
    const kind = node.querySelector(".kind");
    const badges = node.querySelector(".badges");
    const description = node.querySelector(".description");
    const meta = node.querySelector(".meta");
    const open = node.querySelector(".open");
    const stop = node.querySelector(".stop");
    const restart = node.querySelector(".restart");
    const uninstall = node.querySelector(".uninstall");
    app.action_key = app.icon_key || normalize(`${app.name}-${app.docker_name || app.service_name || ""}`);

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
        <h3></h3>
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
  node.querySelector(".store-namespace").textContent = item.namespace
    ? `${item.namespace}/${item.repo || ""}`
    : item.name;
  node.querySelector("p").textContent = item.description || "Docker Hub image";
  node.querySelector(".store-meta").textContent = [
    item.official ? "Official" : "",
    item.automated ? "Automated" : "",
    `${compactNumber(item.stars)} stars`,
    `${compactNumber(item.pulls)} pulls`,
  ].filter(Boolean).join(" · ");
  const link = node.querySelector(".store-link");
  link.href = item.page_url || `https://hub.docker.com/r/${encodeURIComponent(item.image || item.name)}`;
  link.title = `Open ${item.name} on Docker Hub`;
  node.querySelector("button").addEventListener("click", () => openStoreInstall(item));
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
  storeInstallHostPort.value = "";
  storeInstallContainerPort.value = "";
  storeInstallEnv.value = "";
  storeInstallVolumes.value = "";
  storeInstallRestart.value = "unless-stopped";
  storeInstallDialog.showModal();
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
    storeInstallDialog.close();
    window.alert(result.message || `${payload.name} installed.`);
    await load();
    await loadStatus();
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
      <button class="file-copy" type="button">Copy</button>
      <button class="file-delete" type="button">Delete</button>
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
  node.querySelector(".file-copy").addEventListener("click", () => copyFileEntry(entry));
  node.querySelector(".file-delete").addEventListener("click", () => deleteFileEntry(entry));
  if (!state.features.file_operations) {
    node.querySelector(".file-copy").disabled = true;
    node.querySelector(".file-delete").disabled = true;
  }
  return node;
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
  updateFileControls();
  loadFiles(state.filePath).catch(console.error);
}

async function pasteFileEntry() {
  if (!state.filePath || !state.fileClipboard || !state.features.file_operations) return;
  try {
    await runFileAction({ action: "copy", source: state.fileClipboard.path, destination: state.filePath });
  } catch (error) {
    window.alert(error.message);
  }
}

async function deleteFileEntry(entry) {
  if (!state.features.file_operations) return;
  const confirmed = window.confirm(`Delete "${entry.name}" permanently?`);
  if (!confirmed) return;
  try {
    await runFileAction({ action: "delete", path: entry.path });
  } catch (error) {
    window.alert(error.message);
  }
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
  node.querySelector("strong").textContent = item.name;
  node.querySelector("p").textContent = `${ipv4} · gateway ${item.gateway || "--"} · DNS ${(item.dns || []).join(", ") || "--"}`;
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
  networkManagedBy.textContent = `Managed by ${item.managed_by || "unknown"}${item.netplan_file ? ` · ${item.netplan_file}` : ""}`;
  renderNetworkInterfaces();
}

function renderNetworkInterfaces() {
  networkInterfaces.replaceChildren(...state.networkInterfaces.map(renderNetworkInterface));
}

async function loadNetworkSettings() {
  const response = await fetch("/api/settings/network", { cache: "no-store" });
  const data = await response.json();
  state.networkInterfaces = data.interfaces || [];

  if (!state.selectedNetwork && state.networkInterfaces.length) {
    selectNetworkInterface(state.networkInterfaces.find((item) => item.gateway) || state.networkInterfaces[0]);
  } else {
    const updated = state.networkInterfaces.find((item) => item.name === state.selectedNetwork?.name);
    if (updated) selectNetworkInterface(updated);
    else renderNetworkInterfaces();
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
    window.setTimeout(() => window.location.reload(), 3500);
  } catch (error) {
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
    window.setTimeout(() => window.location.reload(), 3500);
  } catch (error) {
    githubUpdateStatus.textContent = error.message;
    githubUpdateApply.disabled = !state.githubUpdate?.update_available;
  } finally {
    githubUpdateCheck.disabled = false;
  }
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

function setFileView(view) {
  state.fileView = view;
  filesNode.classList.toggle("grid-view", view === "grid");
  filesNode.classList.toggle("list-view", view === "list");
  fileViewGrid.classList.toggle("active", view === "grid");
  fileViewList.classList.toggle("active", view === "list");
  fileViewGrid.setAttribute("aria-pressed", String(view === "grid"));
  fileViewList.setAttribute("aria-pressed", String(view === "list"));
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
  if (view === "files") loadFiles(state.filePath).catch(console.error);
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
fileViewGrid.addEventListener("click", () => setFileView("grid"));
fileViewList.addEventListener("click", () => setFileView("list"));
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
loadFiles().catch(console.error);
setInterval(() => loadSystem().catch(console.error), 2000);
setInterval(() => loadStatus().catch(console.error), 15000);
setInterval(() => loadResources().catch(console.error), 2500);
