# HomeStart architecture

HomeStart is a self-contained HTTP service for a trusted local network.

- `app.py` is a backward-compatible executable shim. Existing manual commands,
  systemd units and online updates continue to start HomeStart in the same way.
- `homestart/server.py` owns the current process lifecycle and the domain code
  that has not been extracted yet.
- `homestart/api/router.py` dispatches JSON API requests and converts domain
  errors into HTTP responses. The HTTP handler itself remains a small adapter
  around Python's standard-library server.
- `homestart/config.py` owns defaults, recursive config merging and JSON
  persistence.
- `homestart/files/copy.py` owns background copy jobs, native GNU `cp`
  supervision, progress, speed, ETA and cancellation.
- `homestart/system/network.py` contains side-effect-free parsers and network
  interface selection.
- `homestart/updates/github.py` handles GitHub release metadata and asset
  downloads; package validation and installation remain in the server.
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

## Compatibility boundary

The refactor is deliberately incremental. `homestart.server` keeps compatibility
wrappers for functions that moved into domain modules, which lets existing
tests and integrations continue to use the current names. New work should put
domain logic in the closest package and leave only orchestration in
`server.py`.

No framework migration is required by this structure. HomeStart continues to
use `ThreadingHTTPServer`, `SimpleHTTPRequestHandler`, the Python standard
library and PyYAML.

Online updates download only `homestart-update-*.tar.gz`. The updater validates
the package manifest, rejects private/runtime files, preserves local config and
data, backs up replaced files, installs both `app.py` and the `homestart/`
package, and restarts the service.
