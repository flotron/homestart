"use strict";

(() => {
  const installButton = document.querySelector("#install-app");
  let deferredInstallPrompt = null;

  function hideInstallButton() {
    if (installButton) installButton.hidden = true;
  }

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    if (installButton) installButton.hidden = false;
  });

  installButton?.addEventListener("click", async () => {
    if (!deferredInstallPrompt) return;
    installButton.disabled = true;
    try {
      await deferredInstallPrompt.prompt();
      await deferredInstallPrompt.userChoice;
    } finally {
      deferredInstallPrompt = null;
      installButton.disabled = false;
      hideInstallButton();
    }
  });

  window.addEventListener("appinstalled", () => {
    deferredInstallPrompt = null;
    hideInstallButton();
  });

  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js", {
        scope: "/",
        updateViaCache: "none",
      }).catch(() => {
        /*
         * HomeStart remains a normal web dashboard if this browser or reverse
         * proxy does not permit service workers.
         */
      });
    });
  }
})();
