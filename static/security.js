const securityUsers = document.querySelector("#security-users");
const securityCreateForm = document.querySelector("#security-create-user");
const securityPasswordForm = document.querySelector("#security-change-password");
const securityProxyForm = document.querySelector("#security-proxy-form");
const securityProxyRequest = document.querySelector("#security-proxy-request");
const securityStatus = document.querySelector("#security-status");

function securityMessage(message, error = false) {
  if (!securityStatus) return;
  securityStatus.textContent = message;
  securityStatus.classList.toggle("error", error);
}

async function securityJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) throw new Error(payload.error || "Request failed");
  return payload;
}

async function loadSecurityUsers() {
  if (!securityUsers) return;
  const payload = await securityJson(await fetch("/api/auth/users", { cache: "no-store" }));
  securityUsers.replaceChildren(...payload.users.map((user) => {
    const row = document.createElement("div");
    row.className = "security-user-row";
    const identity = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = user.username;
    const detail = document.createElement("small");
    detail.textContent = user.id === payload.current_user_id ? "Current account · Full access" : "Full access";
    identity.append(name, detail);
    row.append(identity);
    if (user.id !== payload.current_user_id) {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "danger secondary";
      remove.textContent = "Delete";
      remove.addEventListener("click", async () => {
        if (!window.confirm(`Delete HomeStart user "${user.username}"?`)) return;
        try {
          await securityJson(await fetch("/api/auth/users", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "delete", user_id: user.id }),
          }));
          securityMessage(`Deleted ${user.username}`);
          await loadSecurityUsers();
        } catch (error) {
          securityMessage(error.message, true);
        }
      });
      row.append(remove);
    }
    return row;
  }));
}

async function loadProxySecurity() {
  if (!securityProxyForm) return;
  const payload = await securityJson(await fetch("/api/auth/security", { cache: "no-store" }));
  securityProxyForm.querySelector('[name="cookie_secure"]').value = payload.cookie_secure || "auto";
  securityProxyForm.querySelector('[name="trusted_proxies"]').value = (payload.trusted_proxies || []).join("\n");
  const request = payload.request || {};
  const route = request.trusted_proxy ? `trusted proxy ${request.peer_ip}` : "direct or untrusted connection";
  const scheme = request.https ? "HTTPS" : "HTTP";
  const cookie = request.cookie_will_be_secure ? "Secure cookie enabled" : "Secure cookie not used";
  securityProxyRequest.textContent = `${scheme} · ${route} · client ${request.effective_client_ip || "--"} · ${cookie}`;
}

securityCreateForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const username = securityCreateForm.querySelector('[name="username"]').value;
  const password = securityCreateForm.querySelector('[name="password"]').value;
  const confirmation = securityCreateForm.querySelector('[name="confirmation"]').value;
  if (password !== confirmation) return securityMessage("Passwords do not match", true);
  try {
    await securityJson(await fetch("/api/auth/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "create", username, password }),
    }));
    securityCreateForm.reset();
    securityMessage(`Created ${username}`);
    await loadSecurityUsers();
  } catch (error) {
    securityMessage(error.message, true);
  }
});

securityPasswordForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const currentPassword = securityPasswordForm.querySelector('[name="current_password"]').value;
  const newPassword = securityPasswordForm.querySelector('[name="new_password"]').value;
  const confirmation = securityPasswordForm.querySelector('[name="confirmation"]').value;
  if (newPassword !== confirmation) return securityMessage("Passwords do not match", true);
  try {
    const payload = await securityJson(await fetch("/api/auth/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }));
    window.alert(payload.message);
    window.location.replace("/login.html");
  } catch (error) {
    securityMessage(error.message, true);
  }
});

securityProxyForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const mode = securityProxyForm.querySelector('[name="cookie_secure"]').value;
  const proxies = securityProxyForm.querySelector('[name="trusted_proxies"]').value
    .split(/[\n,]+/)
    .map((value) => value.trim())
    .filter(Boolean);
  if (mode === "always" && securityProxyRequest?.textContent.startsWith("HTTP")) {
    if (!window.confirm("Always secure cookies cannot be sent over direct HTTP. Save this only if you will access HomeStart through HTTPS.")) return;
  }
  try {
    await securityJson(await fetch("/api/auth/security", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cookie_secure: mode, trusted_proxies: proxies }),
    }));
    securityMessage("Proxy and cookie security saved");
    await loadProxySecurity();
  } catch (error) {
    securityMessage(error.message, true);
  }
});

window.HomeStartAuth?.ready.then(() => Promise.all([
  loadSecurityUsers(),
  loadProxySecurity(),
])).catch(() => {});
