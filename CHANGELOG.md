# Changelog

All notable HomeStart changes should be recorded here before building a new
installer or update package. Keep entries focused on user-visible behavior,
packaging, security, and migration notes.

## 20260723-2230

- History SVGs now use the panel's real rendered width instead of a fixed
  800-pixel internal canvas.
- Fixed the wide-screen letterboxing that visually compressed samples into the
  center of the chart while the HTML time axis still occupied the full panel.
- Network and system samples now align horizontally with their corresponding
  timestamps from the first available point through the latest point.

## 20260723-2200

- Network history now keeps the real two-second download and upload peak from
  every displayed time bucket instead of diluting short speed tests with an
  average.
- Average bandwidth remains available separately for accurate summary cards.
- Fixed-range charts crop their axis to the samples that actually exist inside
  the selected period, removing unexplained empty leading and trailing spans.
- Network history reports collector freshness and detected sampling gaps so
  missing data is never presented as zero traffic.
- Future-dated samples caused by a corrected server clock are excluded from the
  active chart window.
- Adaptive network scaling now includes the real recorded maximum and rounds it
  to a predictable readable ceiling instead of clipping speed-test peaks.

## 20260723-2100

- Rebuilt the main navigation as consistent text cards with descriptive
  subtitles and removed the isolated house icon from Overview.
- Reorganized Settings into a File Browser-style workspace with separate
  General, Backups, Network and Updates navigation cards.
- Moved the network refresh action into the Network settings card.
- History windows now use the Linux server timestamp instead of the browser
  clock and no longer add a large empty tail in Available data mode.
- Network chart scaling now focuses on the 98th percentile plus current values,
  keeping recent traffic readable after isolated multi-gigabit peaks.
- Peaks above the visual scale remain available in tooltips and are counted in
  the graph metadata.

## 20260723-2030

- Replaced the browser-dependent time-zone datalist with a real select menu.
- Time-zone choices are grouped by IANA region and combine Python tzdata with
  the regions reported directly by `timedatectl`.
- The server's current region remains selectable even if it is absent from one
  of the available time-zone sources.

## 20260723-2000

- Moved Trash from Settings into File Browser and added original path, item
  type, recursive size, deletion time and total disk usage.
- Added permanent deletion, empty-all and configurable automatic retention:
  never, 7, 30 or 90 days. Existing installations default to never.
- Added a permanent date and clock that follows the Linux server time zone.
- Settings can now change the server's real IANA time-zone region through
  `timedatectl`.
- Added hover and touch tooltips to system and network history charts with the
  exact server-local timestamp and all values at the nearest sample.

## 20260723-1900

- Fixed writable guest-share setup when a folder was created by the root-run
  HomeStart service: automatic selection now walks up to the nearest non-root
  Linux owner.
- Saving a writable guest share grants its top-level folder to that selected
  Linux user, with rollback if Samba validation or reload fails.
- New folders and uploaded files created in File Browser now inherit the owner
  and group of their parent folder instead of remaining root-owned.
- Editing a share now reminds Windows clients to reconnect so new permissions
  replace the cached SMB session.

## 20260723-1830

- Fixed writable guest shares by mapping guest writes to the non-root Linux
  owner of the shared folder instead of Samba's unprivileged guest account.
- Added safe file and directory creation masks for writable guest shares.
- Added Edit share for HomeStart-managed shares, including path, authorized
  users, guest access, read/write mode, visibility and guest write identity.
- Guest shares are never allowed to force writes as the Linux root account.

## 20260723-1800

- Added a responsive Samba Share Manager below File Browser.
- Existing effective shares show their folder, availability, discovery,
  read/write mode and authorized Samba users.
- Existing shares can be disabled and restored without deleting their files or
  rewriting their original share blocks.
- New shares can use the currently open File Browser folder and are kept in a
  separate HomeStart-managed Samba include file.
- Every change is checked with `testparm` before Samba reloads; failed changes
  roll back automatically.
- Samba password hashes are never exposed to the browser or stored in
  HomeStart release files.
- Samba passwords can be set or reset for an existing Linux account without
  exposing the value to HomeStart history or configuration.

## 20260723-1730

- Network Settings now shows the same runtime manufacturer/model information
  as Overview, together with the Linux interface name and negotiated speed.
- The IPv4 editor repeats the selected adapter identity above its Netplan
  details.
- Virtual bridges are no longer presented as detected physical adapters.

## 20260723-1500

- Removed File Browser grid view and rebuilt its single list layout for narrow
  screens, with a compact toolbar, smaller rows, and a mobile locations panel.
- Added single-item selection and an action menu opened by right-click, the
  three-dot button, or a 550 ms touch hold, with open, download, copy, rename,
  and trash actions.
- Named every stopped container directly in the corresponding overview alert.
- Added locally persisted alert ignoring plus a visible control to restore all
  currently ignored alerts.

## 20260723-1330

- Replaced the CSS-drawn CPU, memory, and GPU illustrations with a consistent
  professional SVG icon set, using restrained hardware-specific accent colors.
- Reworked the mobile Apps view with larger app icons and favorite targets,
  compact cards, scrollable badges, a sticky filter bar, and a touch-friendly
  three-column action layout.
- Kept App Store cards and top actions compact on narrow screens.

## 20260723-1230

- Prioritized Docker Official Images, Verified Publishers, and sponsored open
  source results ahead of unverified community images in App Store searches.
- Added a Twitter-style blue check beside trusted image names, with a tooltip
  that distinguishes Official, Verified Publisher, and sponsored OSS status.
- Cached concurrent verification checks for six hours to keep later searches
  fast without relying on unverified namespace guesses.

## 20260723-1130

- Added the current top downloading and uploading Docker container beside the
  live host bandwidth values, including each winner's two-second rate.
- Read per-container Linux network namespaces without requiring an additional
  monitoring package, and refresh container discovery every 15 seconds.

## 20260723-1000

- Added direct Docker Hub URL recognition to App Store search, including both
  namespaced `/r/owner/image` and official `/_/image` pages.
- A pasted image URL now loads that exact repository card instead of treating
  the full URL as search keywords.

## 20260723-0130

- Fixed new network history collapsing into one invisible point because its
  downsampling bucket was based on the selected range instead of available data.
- Kept full two-second resolution until the available series exceeds roughly
  1,200 points, then increases aggregation progressively.
- Added visible markers for the first single download/upload sample.

## 20260723-0030

- Changed live network polling and background network history sampling to every
  2 seconds.
- Added a dedicated raw network history table with seven-day retention, while
  keeping CPU, memory, and GPU sampling at 30 seconds.
- Downsampled long ranges to at most about 1,200 displayed points so day-scale
  charts remain responsive without discarding the stored two-second samples.

## 20260722-2345

- Hid recommended App Store entries when a container already uses the same
  Docker image, regardless of its container name or image tag.
- Marked installed images in manual Docker Hub search results and disabled
  duplicate installation from those cards and from the install API.
- Replaced recommended-app search links with direct image pages on Docker Hub,
  GHCR, or Codeberg as appropriate.

## 20260722-2230

- Moved Docker App Store installations into background jobs so the request and
  interface no longer remain blocked during large image downloads.
- Added live installation stages, approximate progress, the latest Docker layer
  messages, a details log, and the final container state.

## 20260722-2100

- Removed scheduled automatic backups and their interval setting.
- Changed manual backup creation to download the archive through the browser,
  allowing the user to choose a folder on Windows or a network drive when the
  browser is configured to ask where downloads should be saved.
- Stopped retaining newly created manual backups on the HomeStart server.

## 20260722-1930

- Smoothed the adaptive network chart scale by replacing large fixed jumps with
  progressive 1, 2, 2.5, 5, and 10 multiples at each order of magnitude.
- Reduced scale headroom to 10 percent. A measured peak near 7 Gbps now selects
  a readable 10 Gbps ceiling instead of jumping from 8 Gbps to 40 Gbps.

## 20260722-1830

- Added a live network panel that updates download and upload every second,
  including interface name and last update time.
- Kept historical bandwidth independent: HomeStart still stores one 30-second
  sample for seven days and refreshes the chart automatically every 30 seconds.
- Separated live and historical network counters so one-second polling cannot
  distort the consolidated history samples.
- Live polling pauses while the browser tab is hidden to avoid needless work.

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



## 20260723-1700

- Network monitoring now follows the connected physical interface behind the
  active default route and recovers automatically when a NIC is replaced.
- Added an Automatic/manual monitoring selector to the bandwidth panel.
- Network choices show runtime hardware information reported by Linux,
  including vendor/model when available, driver fallback, link state, speed,
  interface name, and local address.
- Switching interfaces resets byte counters so unrelated NIC totals cannot
  create false traffic spikes.
- Hardware details remain local runtime data and are never embedded in release
  files or saved as machine-specific defaults.
