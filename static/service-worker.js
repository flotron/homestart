"use strict";

const SHELL_CACHE_PREFIX = "homestart-shell-";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const cacheNames = await caches.keys();
    await Promise.all(
      cacheNames
        .filter((name) => name.startsWith(SHELL_CACHE_PREFIX))
        .map((name) => caches.delete(name)),
    );
    await self.clients.claim();
  })());
});

/*
 * HomeStart deliberately does not cache authenticated pages, API responses,
 * file downloads, or update assets. The worker supplies the installable app
 * lifecycle while every request continues to use the server and its current
 * authentication state.
 */
self.addEventListener("fetch", () => {});
