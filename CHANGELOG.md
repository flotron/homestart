# Changelog

All notable HomeStart changes should be recorded here before building a new
installer or update package. Keep entries focused on user-visible behavior,
packaging, security, and migration notes.

## 20260722-1700

- Added an `Available data` history range that expands the samples to a readable
  timeline while keeping explicit 1h, 6h, 24h, and 7-day ranges available.
- Moved current/average/maximum summaries above the charts and added five real
  time-axis labels for easier interpretation.
- Added a Network bandwidth history chart with download/upload current,
  average, maximum, adaptive units, and automatic scale.
- Network collection now follows only the default-route interface instead of
  summing Docker bridges and virtual adapters, preventing duplicated traffic.

## 20260722-1530

- Fixed performance history depending on an open browser: HomeStart now samples
  CPU, memory, GPU, network, and temperature every 30 seconds in a background
  worker even when nobody has the dashboard open.
- Reworked the performance chart to use real timestamps and break lines across
  collection gaps instead of stretching a few samples across the full period.
- Added an adaptive vertical scale so low but meaningful server activity is no
  longer flattened against a fixed 0–100% axis.
- Added current, average, and maximum values plus sample count and capture range.

## 20260722-1400

- Fixed online updates sometimes showing `Failed to fetch` when systemd
  restarted HomeStart before the browser received the success response.
- The server now flushes update responses and waits three seconds before
  restarting.
- The browser now treats a temporary disconnect as an expected restart,
  monitors `/health`, and reloads automatically when HomeStart returns.

## 20260722-1320

- Fixed File Browser paste becoming unreliable after navigating to a destination
  because the copy action triggered an unnecessary asynchronous folder reload.
- Preserved the copied item in session storage so Paste remains available after
  a browser refresh during the same session.
- Added visible copy/paste progress and success feedback.
- Pasting into a folder that already contains the item now creates `- copy`,
  `- copy 2`, and so on instead of failing.

## 20260722-1200

- Added a professional Overview with system health, host summary, local alerts,
  and responsive CPU, memory, and GPU history charts.
- Added seven-day metric retention in the existing local SQLite database.
- Added configurable alert thresholds, dashboard title, subtitle, accent color,
  theme, and interface density in Settings.
- Added Docker log viewing from app cards and favorite app ordering.
- Added curated Docker templates with suggested ports and persistent volumes.
- Added local HomeStart backups for configuration, history, and custom icons,
  including restore with an automatic pre-restore safety backup.
- Changed File Browser deletion to a recoverable HomeStart trash operation.
- Added file and folder rename, direct downloads, and ZIP downloads for folders.
- Added toast notifications for new workflows and improved responsive Overview
  layouts for phones.
- Added automated tests, package validation, GitHub Actions checks, and tagged
  release generation with installer and online-update assets.
- Added contributor and architecture documentation and expanded the README.

## 20260714-1200

- Added stop/restart actions for native service apps such as Tailscale, backed
  by a whitelist of known/configured systemd units and controlled by
  `features.native_service_actions`.
- Added native service app discovery for installed system services that do not
  expose a local web UI, starting with Tailscale/tailscaled so it appears in
  Apps as a Native Linux service when installed.
- Added a Docker Hub link to each App Store result so users can inspect the
  image page before installing it.
- Improved Docker Hub App Store results with visual icons, namespace/repository
  labels, automated/official badges, richer cards, and local relevance sorting
  so stronger image-name matches appear before weak description matches.
- Added an Apps section App Store backed by Docker Hub search, allowing users
  to find images and install Docker containers from HomeStart with optional
  port, environment, volume, and restart-policy settings.
- Added `features.docker_app_store` so the Docker Hub installer can be disabled
  independently from the rest of the Apps UI.
- Fixed per-process CPU usage reporting so HomeStart no longer divides `ps`
  CPU percentages by the number of CPU cores, which made active processes show
  as `0.0%` on multi-core systems.
- Added Windows-style sorting controls to the System Resources process viewer,
  so CPU and memory usage can be toggled from highest-to-lowest or
  lowest-to-highest.
- Docker app URLs now prefer HTTP-like container ports over non-web ports such
  as SSH, databases, or mail ports, so apps exposing both web and SSH choose
  the browser port instead of the first published port.
- Uninstall confirmation now shows an explicit mismatch message when the typed
  confirmation text is incorrect, instead of silently cancelling.
- Hardened Docker app actions so uninstall verifies the container exists before
  removal, confirms it is gone afterward, returns Docker errors clearly, and
  shows a success message in the UI.
- Docker uninstall now reports container diagnostics such as restart policy and
  Compose labels, and warns if another container with the same name reappears
  after removal.
- App action buttons no longer fail silently; unavailable uninstall actions now
  explain why they cannot run, and active actions show an in-progress state.
- Added generic native web-app discovery from Apache and Nginx virtual host
  configuration, using detected document roots and listen ports instead of
  app-specific rules.
- Removed the experimental CLI chat feature completely from distributable code,
  static assets, routes, styles, and package contents.
- Added a startup migration that removes the old preserved CLI-chat app entry
  from local `config.json` when upgrading from older installs.
- Added File Browser actions to mount unmounted partitions read-only under
  `/mnt/homestart` using `ro,nosuid,nodev,noexec`, plus unmount support for
  HomeStart-managed mounts.
- Added `features.file_mounts` so disk mounting can be disabled independently
  from regular File Browser operations.
- Reworked the File Browser sidebar to show physical disks as parent devices
  with partitions/LVM volumes underneath, including unmounted devices as
  disabled entries instead of hiding them.
- Simplified File Browser delete confirmation to a normal confirmation prompt
  instead of requiring the file or folder name to be typed.
- Improved the File Browser sidebar so the current path is shown as an expanded
  tree branch under the active root.
- Added a broader liquid-glass visual treatment across dashboard panels,
  resource sections, app cards, and File Browser surfaces.
- Reworked the CPU, RAM, and GPU status icons so they visually match a chip,
  memory module, and graphics card, plus circular usage indicators.
- Added custom app icon uploads from app cards; uploaded icons are stored under
  local `data/` and are excluded from distributable packages.
- Simplified the app-card custom icon upload affordance to a plain plus sign.
- Added richer File Browser root metadata so physical disks and USB-mounted
  locations can show disk/USB icons and device details.
- Added GitHub release update checks from Settings; HomeStart can download and
  apply a `homestart-update-*.tar.gz` asset from the configured repository.
- Installed `package.json` metadata during fresh installs so version checks can
  compare the installed version against GitHub releases.

## 20260713-1820

- Fixed File Browser empty Locations view showing "File operations are
  disabled" even when file operations were enabled.
- The drop/status banner now distinguishes between disabled operations and
  simply needing to open a folder before upload/create/paste actions are
  available.

## 20260713-1815

- Reworked File Browser colors back into the dark HomeStart dashboard theme
  while keeping the new visual grid explorer.
- Removed the experimental CLI chat integration from the default Supported Apps list.
- Removed experimental CLI-chat default configuration and public README promotion from the distributable package.

## 20260713-1445

- Redesigned the File Browser into a more visual desktop-style explorer.
- Added a large grid view for folders and files, with a list view toggle for
  dense directory inspection.
- Added a cleaner file sidebar with friendly location labels and full paths.
- Moved upload, new folder, paste, up, roots, and view controls into the File
  Browser workspace header.
- Added a visible Upload button while keeping drag-and-drop uploads.
- Added folder/file counts and current location naming above the file grid.

## 20260710-1735

- Prepared HomeStart for public GitHub distribution.
- Expanded `README.md` with project description, installation guide, basic
  usage tutorial, configuration notes, update flow, packaging, and security
  model.
- Added `.gitignore` to keep local config, runtime databases, packages,
  backups, logs, and local development artifacts out of source control.

## 20260710-1720

- Installer and update archives now include `package.json` metadata with
  `package_type`.
- The HomeStart updater now requires package metadata and accepts only packages
  marked as `update`.
- Uploading an installer archive to Settings > Updates is now rejected with a
  clear error instead of being applied as an update.

## 20260710-1715

- Ookla Speedtest results are now stored locally in `data/homestart.db`.
- Added `/api/speedtest/history` for previous Speedtest runs.
- Speedtest UI now loads the latest stored result and shows a clickable history
  table.
- History is local runtime data, so it is preserved by updates and excluded
  from installer/update packages.

## 20260710-1710

- File Browser path display is now an address bar.
- Users can type or paste a full path and press Enter or `Go` to navigate
  directly, with the backend still enforcing configured `file_roots`.

## 20260710-1705

- File Browser now supports drag-and-drop uploads into the currently open
  folder.
- Added a File Browser clipboard: `Copy` stores the selected file or folder,
  and `Paste` copies it into the current folder.
- Mounted physical disks and USB drives now appear as File Browser sidebar
  shortcuts when their mount points are inside configured `file_roots`.
- Added visible File Browser drop/operation status so the interface behaves
  more like a desktop file explorer.
- Upload, copy, delete, and folder creation remain gated by
  `features.file_operations` and constrained to configured `file_roots`.

## 20260710-1653

- Expanded File Browser into a more OS-like explorer while keeping operations
  constrained to configured `file_roots`.
- Added `features.file_operations` to control create, copy, and delete
  capabilities.
- Added `New folder` support.
- Added per-file actions for open/view, copy, and delete.
- Delete now requires strong confirmation by typing `DELETE <name>`.
- Copy prompts for a destination folder or destination path.
- File open responses now prefer inline display so the browser tries to open
  supported files instead of downloading them immediately.
- Updated the example configuration so installers can expose broader or
  narrower file roots without hardcoded personal paths.

## 20260710-1636

- Reworked  CLI supported-app detection to avoid hardcoded user home
  paths from development machines.
-  now looks for authenticated config in a portable order:
  `supported_apps.._home`, `_HOME`, `$HOME/.`, standard
  `/home/*/.` locations, and `/root/.`.
- If multiple authenticated  homes are found, HomeStart now asks the user
  to configure `supported_apps.._home` instead of guessing.
- When HomeStart runs as root,  commands run as the owner of the selected
  auth directory to avoid creating root-owned files in a user profile.
- Removed personal path assumptions from Speedtest/ supported-app
  wrappers.

## 20260710-1623

- Fixed Apps action buttons overflowing after `Uninstall` was added.
- Increased app card minimum width from 220px to 260px.
- Changed action layout to wrap buttons when a card is too narrow.
- Added stable button minimum widths so actions no longer spill into adjacent
  cards.

## 20260710-1608

- Clarified Supported apps as visual wrappers/adaptations around CLI tools.
- Added a real Ookla Speedtest supported-app wrapper at `/speedtest`.
- Speedtest can now run the installed `speedtest` CLI from HomeStart and show
  download, upload, ping, ISP, and selected server details.
- Fixed  CLI Chat configuration that previously relied on development
  machine paths.
- Updated  CLI Chat toward portable runtime paths; unauthenticated 
  installations now report that authentication is required instead of failing
  on missing local development paths.

## 20260710-1520

- Status now renders a separate usage bar for each detected GPU.
- GPU rows show per-device usage percentage plus frequency and memory details
  when those counters are available.

## 20260710-1510

- Apps now expose Docker running state in `/api/apps`.
- Docker apps marked as stopped or exited now disable the `Open` button.
- After a successful Docker `Stop`, the Apps view immediately greys out `Open`
  before refreshing from the backend.
- `Stop` is disabled for Docker containers that are already stopped; `Restart`
  remains available.

## 20260710-1508

- Added this changelog to the installable and update packages so future 
  chats can quickly recover project history from the distributed artifact.
- Updated the package builder to copy `CHANGELOG.md` into every generated
  installer and update archive.

## 20260710-1506

- Fixed Apps cards so `Open`, `Stop`, `Restart`, and `Uninstall` stay inside
  each card after adding the uninstall action.
- Changed app action layout to a stable two-column grid for narrower screens.
- Hardened package validation to reject temporary backup files such as
  `*.bak`, `*.bak-*`, and `*.backup`.
- Rebuilt clean installer and update packages after confirming they do not
  include local/private paths.

## 20260710-1457

- Added the Apps `Uninstall` action.
- Docker uninstall removes only the container with `docker rm -f`; images and
  volumes are preserved.
- Native Linux and supported apps require an explicit `uninstall_command` in
  `config.json` before HomeStart enables uninstall.
- Added strong uninstall confirmation requiring the exact text
  `UNINSTALL <app name>`.
- Hardened package generation and update validation so releases refuse local
  or private files such as `config.json`, `data/`, `dist/`, `backups/`, Git
  metadata, SQLite databases, logs, environment files, and installed service
  units.
- Updated `README.md` and `config.example.json` for uninstall and packaging
  behavior.



