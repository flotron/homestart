# HomeStart architecture

HomeStart is a self-contained HTTP service for a trusted local network.

- `app.py` is a backward-compatible executable shim. Existing manual commands,
  systemd units and online updates continue to start HomeStart in the same way.
- `homestart/server.py` owns the current process lifecycle and the domain code
  that has not been extracted yet.
- `homestart/api/router.py` dispatches JSON API requests and converts domain
  errors into HTTP responses. The HTTP handler itself remains a small adapter
  around Python's standard-library server.
- `homestart/auth/manager.py` owns local users, one-time initial setup, scrypt
  password verification, opaque persistent sessions and CSRF tokens. These
  users gate the web UI but intentionally do not map to Linux or Samba users.
- `homestart/config.py` owns defaults, recursive config merging and JSON
  persistence.
- `homestart/files/copy.py` owns background copy jobs, native GNU `cp`
  supervision, progress, speed, ETA and cancellation.
- `homestart/metrics/store.py` owns SQLite schemas, retention, metric history,
  peak-preserving network buckets and per-app bandwidth rankings.
- `homestart/samba/manager.py` owns Samba parsing, share credentials,
  validation, transactional configuration writes and service reloads.
- `homestart/system/network.py` contains side-effect-free parsers and network
  interface selection.
- `homestart/system/network_config.py` contains NetworkManager terse-output
  parsing, architecture normalization and portable configuration helpers.
- `homestart/docker/projects.py` owns managed Compose project discovery,
  lifecycle actions, protected data removal and template risk analysis.
- `homestart/docker/store.py` owns declarative catalog validation, placeholder
  expansion, installer input normalization, Compose rendering and pure Docker
  Hub result helpers. Remote fetches and long-running install orchestration
  remain in the server boundary for now.
- `homestart/updates/github.py` handles GitHub release metadata and asset
  downloads.
- `homestart/updates/package.py` validates, stages, preflights, atomically
  applies and records rollback metadata for update packages.
- `static/` contains the dependency-free browser application.
- `data/homestart.db` stores local metric and Speedtest history.
- `data/auth-users.json` stores salted password hashes with mode `0600`.
  `data/auth-sessions.db` stores only hashes of opaque session tokens and is
  intentionally excluded from backups.
- `data/backups/`, `data/trash/`, `data/app-icons/`, `data/compose-apps/`, and
  `data/app-data/` contain local runtime data and are never included in releases.
- Recommended applications come from the versioned
  `flotron/homestart-apps` catalog. HomeStart validates and caches the catalog,
  renders only its declared inputs, then runs the generated project through the
  host's Docker Compose plugin.
- Network configuration is selected per interface. A Netplan declaration
  remains authoritative; otherwise a managed NetworkManager device is changed
  through `nmcli`. Unknown managers are never rewritten.
- App templates may declare `amd64`, `arm64` and `arm/v7`. HomeStart combines
  that declaration with a best-effort Docker manifest inspection. This is a
  portability mechanism, not evidence that any particular ARM board was tested.
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

Release archives also contain a compatibility copy at `scripts/homestart/`.
This lets an updater from before the package split install the modular server
through its existing `scripts/` allowlist. `app.py` uses that copy only when the
canonical top-level package is unavailable; subsequent updates can install and
use `homestart/` normally.

Every release is tested through an update matrix against the immediately
previous release and the last pre-modular release. Synthetic runtime fixtures
represent configuration, SQLite history, trash metadata, icons and Compose app
data. Their hashes must remain unchanged after migration.

Before replacing installed files, the update package is extracted to a staging
directory and its Python package is compiled and imported. A write failure
restores already replaced files in-process. On systemd installations, a
separate transient verifier checks the expected version and `/health` after
restart and restores `transaction.json` automatically if startup fails.
