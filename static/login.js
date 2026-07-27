const loading = document.querySelector("#auth-loading");
const loginForm = document.querySelector("#login-form");
const setupForm = document.querySelector("#setup-form");
const loginError = document.querySelector("#login-error");
const setupError = document.querySelector("#setup-error");
let loginRetryTimer = null;

function showError(node, message) {
  node.textContent = message;
  node.hidden = false;
}

async function jsonRequest(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    const error = new Error(data.error || "HomeStart could not complete the request");
    error.retryAfter = Number(data.retry_after || response.headers.get("Retry-After")) || 0;
    throw error;
  }
  return data;
}

function startLoginRetry(button, seconds) {
  window.clearInterval(loginRetryTimer);
  let remaining = Math.max(1, Math.ceil(seconds));
  const original = button.dataset.defaultLabel || button.textContent;
  button.dataset.defaultLabel = original;
  button.disabled = true;
  const render = () => {
    button.textContent = `Try again in ${remaining}s`;
    remaining -= 1;
    if (remaining < 0) {
      window.clearInterval(loginRetryTimer);
      loginRetryTimer = null;
      button.textContent = original;
      button.disabled = false;
    }
  };
  render();
  loginRetryTimer = window.setInterval(render, 1000);
}

async function initialize() {
  const response = await fetch("/api/auth/status", { cache: "no-store" });
  const status = await response.json();
  if (status.authenticated) {
    window.location.replace("/");
    return;
  }
  loading.hidden = true;
  setupForm.hidden = !status.setup_required;
  loginForm.hidden = status.setup_required;
  (status.setup_required ? document.querySelector("#setup-token") : document.querySelector("#login-username")).focus();
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  const button = loginForm.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    await jsonRequest("/api/auth/login", {
      username: document.querySelector("#login-username").value,
      password: document.querySelector("#login-password").value,
      remember: document.querySelector("#login-remember").checked,
    });
    window.location.replace("/");
  } catch (error) {
    showError(loginError, error.message);
    if (error.retryAfter) startLoginRetry(button, error.retryAfter);
  } finally {
    if (!loginRetryTimer) button.disabled = false;
  }
});

setupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setupError.hidden = true;
  const password = document.querySelector("#setup-password").value;
  if (password !== document.querySelector("#setup-password-confirm").value) {
    showError(setupError, "Passwords do not match");
    return;
  }
  const button = setupForm.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    await jsonRequest("/api/auth/setup", {
      setup_token: document.querySelector("#setup-token").value,
      username: document.querySelector("#setup-username").value,
      password,
      remember: document.querySelector("#setup-remember").checked,
    });
    window.location.replace("/");
  } catch (error) {
    showError(setupError, error.message);
  } finally {
    button.disabled = false;
  }
});

initialize().catch((error) => {
  loading.querySelector("h2").textContent = "Could not reach HomeStart";
  loading.querySelector("p").textContent = error.message;
});
