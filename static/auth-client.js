(() => {
  const nativeFetch = window.fetch.bind(window);
  let authStatus = null;

  const ready = nativeFetch("/api/auth/status", { cache: "no-store" })
    .then(async (response) => {
      const payload = await response.json();
      if (!payload.authenticated) {
        window.location.replace("/login.html");
        throw new Error("Authentication required");
      }
      authStatus = payload;
      document.documentElement.dataset.authenticated = "true";
      const username = document.querySelector("#session-username");
      if (username) username.textContent = payload.user?.username || "User";
      return payload;
    });

  window.fetch = async (input, options = {}) => {
    const status = await ready;
    const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
    const method = String(options.method || (typeof input !== "string" && input.method) || "GET").toUpperCase();
    const requestOptions = { ...options };
    if (url.origin === window.location.origin && !["GET", "HEAD", "OPTIONS"].includes(method)) {
      const headers = new Headers(options.headers || (typeof input !== "string" ? input.headers : undefined));
      headers.set("X-CSRF-Token", status.csrf_token);
      requestOptions.headers = headers;
    }
    const response = await nativeFetch(input, requestOptions);
    if (response.status === 401) {
      window.location.replace("/login.html");
    }
    return response;
  };

  async function logout() {
    try {
      await window.fetch("/api/auth/logout", { method: "POST" });
    } finally {
      window.location.replace("/login.html");
    }
  }

  window.HomeStartAuth = {
    ready,
    logout,
    status: () => authStatus,
  };

  document.querySelector("#session-logout")?.addEventListener("click", logout);
})();
