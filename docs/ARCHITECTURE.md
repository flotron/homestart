# HomeStart architecture

HomeStart is a self-contained HTTP service for a trusted local network.

- `app.py` provides static files, JSON APIs, host inspection, Docker actions,
  file operations, metrics, backups, network settings, and updates.
- `static/` contains the dependency-free browser application.
- `data/homestart.db` stores local metric and Speedtest history.
- `data/backups/`, `data/trash/`, `data/app-icons/`, `data/compose-apps/`, and
  `data/app-data/` contain local runtime data and are never included in releases.
- Recommended applications come from the versioned
  `flotron/homestart-apps` catalog. HomeStart validates and caches the catalog,
  renders only its declared inputs, then runs the generated project through the
  host's Docker Compose plugin.
- `scripts/build_package.sh` creates separate installer and update archives.
- `.github/workflows/` validates every change and builds tagged releases.

Online updates download only `homestart-update-*.tar.gz`. The updater validates
the package manifest, rejects private/runtime files, preserves local config and
data, backs up replaced files, and restarts the service.
